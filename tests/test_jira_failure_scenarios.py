"""M5-4-1 실패 상황 시나리오 — Jira 가 꺼졌거나 배정할 사람이 없을 때, 접수가 남고 관리자가 다시 처리할 수 있는가.

단위 테스트(test_jira_create_service·test_integration_retry 등)는 실패 한 가지씩을 본다. 이 파일은 실제 흐름을 처음부터 끝까지 잇는다.
    접수(DB) → 실행기(worker.run_round) → 장애·소진 → 관리자 화면 API(목록·재처리·수동 배정) → 복구 → 실행기가 끝까지 처리
실제 JiraClient 를 쓰고 HTTP 응답만 흉내 낸다(JiraSim). 연결 거부·시간 초과·인증 만료가 클라이언트의 오류 분류를 거쳐 나온다.
SQLite 메모리 DB 만 쓰며 실제 Jira 는 부르지 않는다.
"""
import json
import re
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from app.integrations.jira import worker
from app.integrations.jira.client import JiraClient
from app.main import app
from app.models import Base, IntegrationJob, TimeOff
from app.services.integration_retry import jira_opener
from app.services.jira_create import enqueue_jira_create
from app.utils import datetime_utils
from test_auth import add_user, client, error_code  # noqa: F401
from test_inquiries import headers, owner  # noqa: F401
from test_tickets import TICKETS, admin, as_user, db, ids, make_ticket, staff, team  # noqa: F401

BASE = datetime_utils.now()
RECEIPT_FIELD = "customfield_10043"
RDY, WIP = "10004", "10005"           # Jira 상태 id (field_mapping.yaml)


class JiraSim:
    """Jira 서버 모의. 이슈를 기억하고(중복 생성 확인용), 스위치로 장애를 흉내 낸다.

    down                True 면 연결 자체가 안 된다 (서버 꺼짐·네트워크 단절)
    fail_status         값이 있으면 모든 요청을 그 HTTP 상태로 거절한다 (503 점검 중, 401 토큰 만료)
    assign_fail_status  값이 있으면 담당자 지정 요청만 그 상태로 거절한다
    lose_response       True 면 이슈 생성은 처리하되 응답이 오기 전에 시간 초과가 난다 (생성됐는지 모르는 상태)
    """

    def __init__(self):
        self.down, self.fail_status, self.assign_fail_status, self.lose_response = False, None, None, False
        self.issues: dict[str, dict] = {}
        self.calls: list[tuple[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        if self.down:
            raise httpx.ConnectError("Connection refused")
        if self.fail_status:
            return httpx.Response(self.fail_status, json={"errorMessages": ["Jira 가 요청을 받지 못합니다"]})
        method, path = request.method, request.url.path
        if (method, path) == ("POST", "/rest/api/3/search/jql"):
            receipt = re.search(r"RCPT-\d+", json.loads(request.content)["jql"]).group(0)
            found = [{"id": i["id"], "key": k, "fields": {RECEIPT_FIELD: i["receipt"]}}
                     for k, i in self.issues.items() if i["receipt"] == receipt]
            return httpx.Response(200, json={"issues": found, "isLast": True})
        if (method, path) == ("POST", "/rest/api/3/issue"):
            fields = json.loads(request.content)["fields"]
            key = f"ITHD-{901 + len(self.issues)}"
            self.issues[key] = {"id": str(30000 + len(self.issues)), "receipt": fields[RECEIPT_FIELD], "status": RDY,
                                "assignee": None}
            if self.lose_response:
                raise httpx.ReadTimeout("응답 대기 시간 초과")
            return httpx.Response(201, json={"id": self.issues[key]["id"], "key": key})
        match = re.fullmatch(r"/rest/api/3/issue/(ITHD-\d+)(/assignee)?", path)
        if match and match.group(1) in self.issues:
            issue = self.issues[match.group(1)]
            if method == "PUT" and match.group(2):
                if self.assign_fail_status:
                    return httpx.Response(self.assign_fail_status, json={"errorMessages": ["담당자 지정 실패"]})
                issue["assignee"] = json.loads(request.content)["accountId"]
                return httpx.Response(204)
            if method == "GET" and not match.group(2):
                return httpx.Response(200, json={"fields": {
                    "status": {"id": issue["status"], "name": "x"},
                    "assignee": {"accountId": issue["assignee"]} if issue["assignee"] else None,
                    "customfield_10069": None,
                }})
        return httpx.Response(404, json={"errorMessages": ["Issue does not exist"]})     # 없거나 삭제된 이슈

    def client(self) -> JiraClient:
        return JiraClient("https://jira.example", "test@example.com", "dummy", transport=httpx.MockTransport(self))

    def issues_of(self, receipt_no: str) -> list[tuple[str, dict]]:
        return [(k, i) for k, i in self.issues.items() if i["receipt"] == receipt_no]

    def posts(self) -> int:
        return self.calls.count(("POST", "/rest/api/3/issue"))


@pytest.fixture(autouse=True)
def webhook_table(db):
    """run_round 가 웹훅 이벤트도 읽으므로 표를 만들어 둔다."""
    Base.metadata.tables["jira_webhook_events"].create(db.bind, checkfirst=True)


@pytest.fixture
def jira(admin):
    """관리자 재처리 API 도 같은 모의 Jira 를 쓴다 (API 는 요청마다 새 클라이언트를 연다)."""
    sim = JiraSim()
    app.dependency_overrides[jira_opener] = lambda: sim.client
    yield sim
    app.dependency_overrides.pop(jira_opener, None)


def new_order(db, owner, group, vpn, **over):
    """문의자가 접수 확정을 마친 새 접수와 그 Jira 생성 작업."""
    values = dict(
        summary="VPN 접속 불가", target_system="VPN", symptom="인증 서버 연결 실패", occurred_at="오늘 오전",
        category_code="NET", inquiry_type_id=vpn.id, urgency="P3", urgency_reason="개인 업무 중단",
        business_impact="사내 시스템 접속 불가", tried_actions="재설치", work_status=None,
        jira_sync_status="PENDING", assign_status="PENDING") | over
    ticket = make_ticket(db, owner, group, **values)
    enqueue_jira_create(db, ticket)
    db.commit()
    return ticket


@pytest.fixture
def order(db, owner, staff, team):
    """담당 후보는 E0005(1건 처리 중)·E0006(0건). 자동배정이면 E0006 이 뽑힌다."""
    return new_order(db, owner, staff["net"], team["vpn"])


def at(minutes: float):
    return BASE + timedelta(minutes=minutes)


def run(db, sim, minutes, **kw):
    """주어진 시각에 실행기를 한 회차 돌린다. 오류 없이 끝났는지는 호출하는 쪽이 본다."""
    return worker.run_round(db, sim.client(), now=at(minutes), **kw)


def outcomes(report):
    return [(t, r.outcome) for t, r in zip(report.result_types, report.results)]


def job_of(db, ticket, job_type):
    db.expire_all()
    return db.scalars(select(IntegrationJob).where(IntegrationJob.ticket_id == ticket.id, IntegrationJob.job_type == job_type)
                      .order_by(IntegrationJob.id.desc())).first()


def needs_admin_ids(client, admin):
    return ids(client.get(TICKETS, params={"needsAdmin": "true"}, headers=admin))


def retry(client, admin, ticket, job, reason="Jira 복구 후 재처리"):
    return client.post(f"{TICKETS}/{ticket.id}/integration-jobs", headers=admin,
                       json={"retryOfJobId": job.id, "reason": reason})


# ------------------------------------------------------------------ 1. Jira 꺼짐 → 생성 실패


def test_jira_down_at_creation_keeps_ticket_then_admin_retry_recovers(client, db, order, jira, admin, headers):
    """Jira 가 꺼진 동안 접수하면: 접수는 남고 → 재시도(1분·5분 뒤)가 끝나면 관리자 확인 대상 → 복구 후 재처리하면 한 번만 만들어진다."""
    jira.down = True

    first, early, second, third = (run(db, jira, m) for m in (0, 0.5, 1.1, 6.2))

    assert [r.errors for r in (first, early, second, third)] == [[]] * 4
    assert outcomes(first) == [("JIRA_CREATE", "RETRY_SCHEDULED")]
    assert early.results == []                                         # 1분이 되기 전이라 Jira 를 부르지 않는다
    assert outcomes(second) == [("JIRA_CREATE", "RETRY_SCHEDULED")]
    assert outcomes(third) == [("JIRA_CREATE", "NEEDS_ADMIN")]
    assert jira.issues == {} and jira.posts() == 0                     # 연결이 안 되니 이슈를 만들지도 못했다

    # 접수는 사라지지 않았다: 관리자 확인 목록에 나오고, 문의자도 접수번호를 그대로 본다
    db.refresh(order)
    assert (order.jira_sync_status, order.jira_key) == ("NEEDS_ADMIN", None)
    assert order.id in needs_admin_ids(client, admin)
    mine = client.get(f"{TICKETS}/{order.id}", headers=headers).json()
    assert (mine["receiptNo"], mine["jiraSyncStatus"], mine["needsAdmin"]) == (order.receipt_no, "NEEDS_ADMIN", True)
    failed = job_of(db, order, "JIRA_CREATE")
    assert (failed.status, failed.attempts) == ("NEEDS_ADMIN", 3) and failed.last_error

    # Jira 가 돌아와도 실행기가 알아서 되살리지 않는다. 관리자 판단이 필요하다
    jira.down = False
    idle = run(db, jira, 30)
    assert idle.results == [] and jira.issues == {}

    # 관리자가 재처리하면 새 작업이 등록되고, 다음 회차에 한 번만 만들어져 배정까지 이어진다
    assert retry(client, admin, order, failed).status_code == 201
    done = run(db, jira, 31)
    assert done.errors == [] and ("JIRA_CREATE", "CREATED") in outcomes(done)
    db.refresh(order)
    assert (order.jira_sync_status, order.assign_status) == ("SYNCED", "ASSIGNED")
    assert len(jira.issues_of(order.receipt_no)) == 1 and jira.posts() == 1
    assert order.id not in needs_admin_ids(client, admin)


# ------------------------------------------------------------------ 2. 생성 응답 유실


def test_lost_create_response_links_existing_issue_without_duplicate(db, order, jira):
    """Jira 가 이슈를 만들었는데 응답만 못 받았다: 다시 만들지 않고 찾아서 연결한다 (중복 이슈 없음)."""
    jira.lose_response = True

    first = run(db, jira, 0)

    db.refresh(order)
    assert outcomes(first) == [("JIRA_CREATE", "VERIFY_SCHEDULED")] and order.jira_sync_status == "VERIFYING"
    assert len(jira.issues_of(order.receipt_no)) == 1                  # 이미 만들어져 있다

    jira.lose_response = False
    second = run(db, jira, 2)

    db.refresh(order)
    assert second.errors == [] and order.jira_sync_status == "SYNCED"
    assert order.jira_key == jira.issues_of(order.receipt_no)[0][0]
    assert len(jira.issues_of(order.receipt_no)) == 1 and jira.posts() == 1


# ------------------------------------------------------------------ 3. 인증 만료(토큰 오류)


def test_expired_token_goes_straight_to_admin_without_retries_then_recovers(client, db, order, jira, admin):
    """토큰 만료(401)는 다시 해도 같은 결과라 재시도 없이 바로 관리자 확인으로 넘긴다. 토큰을 바꾼 뒤 재처리하면 복구된다."""
    jira.fail_status = 401

    only = run(db, jira, 0)

    assert outcomes(only) == [("JIRA_CREATE", "NEEDS_ADMIN")]
    failed = job_of(db, order, "JIRA_CREATE")
    assert (failed.attempts, failed.status) == (1, "NEEDS_ADMIN")
    assert order.id in needs_admin_ids(client, admin)

    jira.fail_status = None                          # 관리자가 토큰을 새로 발급해 서버 설정을 바꿨다
    assert retry(client, admin, order, failed, "토큰 교체").status_code == 201
    run(db, jira, 5)
    db.refresh(order)
    assert order.jira_sync_status == "SYNCED"


# ------------------------------------------------------------------ 4. 배정할 사람 없음


def test_no_available_assignee_keeps_ticket_then_manager_assigns_by_hand(client, db, order, team, jira, admin):
    """담당 후보가 모두 부재면: 티켓은 Jira 에 만들어지고, 배정만 관리자 확인으로 남는다 → 수동 배정하면 Jira 담당자까지 반영된다."""
    today = datetime_utils.to_kst(at(0)).date()
    for member in (team["busy"], team["free"]):
        db.add(TimeOff(user_id=member.id, time_off_type="ANNUAL", start_date=today, end_date=today))
    db.commit()

    created = run(db, jira, 0)

    db.refresh(order)
    assert created.errors == [] and ("JIRA_CREATE", "CREATED") in outcomes(created)
    assert (order.jira_sync_status, order.assign_status, order.assignee_id) == ("SYNCED", "NEEDS_ADMIN", None)
    assert jira.issues_of(order.receipt_no)[0][1]["assignee"] is None  # Jira 담당자도 비어 있다
    assert order.id in needs_admin_ids(client, admin)

    res = client.put(f"{TICKETS}/{order.id}/assignment", headers=admin,
                     json={"groupId": order.group_id, "assigneeId": team["free"].id, "reason": "전원 부재로 수동 배정"})
    assert res.status_code == 200, res.text
    assigned = run(db, jira, 1)

    db.refresh(order)
    assert assigned.errors == []
    assert (order.assign_status, order.assignee_id) == ("ASSIGNED", team["free"].id)
    assert jira.issues_of(order.receipt_no)[0][1]["assignee"] == "acc-E0006"
    assert order.id not in needs_admin_ids(client, admin)


# ------------------------------------------------------------------ 5. Jira 꺼짐 → 담당자 배정 실패


def test_jira_rejects_assignment_exhausts_retries_then_admin_retry_recovers(client, db, order, team, jira, admin):
    """티켓 생성은 됐지만 담당자 지정이 계속 실패하면: 티켓은 남고 배정만 관리자 확인이 된다. 복구 후 재처리하면 배정된다."""
    jira.assign_fail_status = 503

    first, second, third, fourth = (run(db, jira, m) for m in (0, 1.1, 2.2, 3.3))

    # 담당자 지정 요청이 실패하면 적용됐는지 알 수 없다. 다시 지정하지 않고 조회로만 3번 확인한 뒤 관리자에게 넘긴다
    assert ("JIRA_CREATE", "CREATED") in outcomes(first)
    assert [outcomes(r)[-1] for r in (first, second, third, fourth)] == [("JIRA_ASSIGN", o) for o in
                                                                          ("VERIFY_SCHEDULED",) * 3 + ("NEEDS_ADMIN",)]
    db.refresh(order)
    assert (order.jira_sync_status, order.assign_status) == ("SYNCED", "NEEDS_ADMIN")
    assert order.assignee_id == team["free"].id                         # 예약된 담당자는 보존된다
    assert jira.issues_of(order.receipt_no)[0][1]["assignee"] is None
    assert order.id in needs_admin_ids(client, admin)

    jira.assign_fail_status = None
    failed = job_of(db, order, "JIRA_ASSIGN")
    assert failed.status == "NEEDS_ADMIN" and retry(client, admin, order, failed).status_code == 201
    done = run(db, jira, 31)

    db.refresh(order)
    assert done.errors == [] and (order.assign_status, order.assignee_id) == ("ASSIGNED", team["free"].id)
    assert jira.issues_of(order.receipt_no)[0][1]["assignee"] == "acc-E0006"


# ------------------------------------------------------------------ 6. Jira 꺼짐 중 주기 대조


def test_periodic_sync_survives_jira_outage_and_catches_up(db, order, jira):
    """주기 대조 중 Jira 가 꺼져도 오류 없이 넘어가고, 돌아오면 그동안 Jira 에서 바뀐 상태를 맞춘다."""
    run(db, jira, 0)
    db.refresh(order)
    assert order.jira_sync_status == "SYNCED" and order.work_status == "RDY"
    jira.issues[order.jira_key]["status"] = WIP        # 담당자가 Jira 에서 처리를 시작했다 (웹훅은 오지 못했다고 가정)

    jira.down = True
    outage = run(db, jira, 5, sync=True)
    db.refresh(order)
    assert outage.errors == [] and order.work_status == "RDY"

    jira.down = False
    back = run(db, jira, 7, sync=True)
    db.refresh(order)
    assert back.errors == [] and order.work_status == "WIP"


# ------------------------------------------------------------------ 7. Jira 에서 삭제된 이슈가 주기 대조를 막지 않는다


def test_issues_deleted_in_jira_do_not_starve_periodic_sync_of_healthy_tickets(db, owner, staff, team, order, jira):
    """테스트 이슈를 Jira 에서 지운 접수가 여럿 쌓여 있어도, 정상 접수는 계속 주기 대조를 받는다."""
    run(db, jira, 0)
    db.refresh(order)
    order.work_status_confirmed_at = at(-10)           # 정상 접수는 대조할 때가 됐다
    ghosts = [make_ticket(db, owner, staff["net"], jira_key=f"ITHD-70{n}", work_status="WIP", assign_status="ASSIGNED")
              for n in range(1, 5)]                    # Jira 에는 없는 키 4건 (한 번도 대조된 적 없음 → 대기열 맨 앞)
    db.commit()
    jira.issues[order.jira_key]["status"] = WIP

    first = run(db, jira, 5, sync=True)
    second = run(db, jira, 7, sync=True)

    db.refresh(order)
    assert first.errors == [] and second.errors == []
    assert order.work_status == "WIP", "삭제된 이슈 접수 때문에 정상 접수가 주기 대조에서 밀렸다"
    assert all(t.work_status == "WIP" for t in ghosts)                 # 삭제된 접수는 값을 바꾸지 않는다
