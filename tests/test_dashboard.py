"""운영 집계·운영 기록 API (OP-01~04). SQLite 메모리 DB 만 쓴다."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.constants import llm as llm_constants
from app.models import AuditLog, Category, Inquiry, LlmCall, SupportGroup, SupportGroupMember, Ticket, TicketStatusHistory
from test_auth import TABLES, add_user, bearer, client, error_code, login  # noqa: F401
from test_inquiries import create_sqlite_tables

API = "/api/v1"
KST = timezone(timedelta(hours=9))
QUERY = {"from": "2026-10-01", "to": "2026-10-31"}


def at(day, hour=12):
    return datetime(2026, 10, day, hour, tzinfo=KST).astimezone(timezone.utc)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    create_sqlite_tables(engine, TABLES + ["categories", "inquiries", "tickets", "ticket_status_history", "llm_calls"])
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def users(client, db):
    people = {
        "employee": add_user(db, "E0001", name="직원"),
        "agent": add_user(db, "E0002", name="나담당", service_role="AGENT"),
        "colleague": add_user(db, "E0003", name="가동료", service_role="AGENT"),
        "admin": add_user(db, "E0009", name="관리자", service_role="ADMIN"),
    }
    db.add_all([Category(code="NET", name="네트워크"), Category(code="SW", name="SW")])
    db.add_all([SupportGroup(id=1, name="네트워크팀"), SupportGroup(id=2, name="SW팀"),
                SupportGroup(id=3, name="해체팀", is_active=False)])
    db.flush()
    for user_id in (people["agent"].id, people["colleague"].id):
        db.add(SupportGroupMember(group_id=1, user_id=user_id, member_role="AGENT", assignable=True))
    db.commit()
    return {name: {"id": user.id, "headers": bearer(login(client, user.employee_no))} for name, user in people.items()}


_seq = iter(range(1, 10_000))


def add_inquiry(db, user_id, status="IN_PROGRESS", created_at=None, category="NET", action=None, result=None):
    row = Inquiry(user_id=user_id, status=status, category_code=category, action=action, resolution_result=result,
                  created_at=created_at or at(10))
    db.add(row)
    db.flush()
    return row


def add_ticket(db, user_id, work=None, group=1, assignee=None, created_at=None, category="NET", urgency="P2",
               jira="SYNCED", assign="ASSIGNED", transition="IDLE", inquiry_status="RECEIVED"):
    n = next(_seq)
    inquiry = add_inquiry(db, user_id, inquiry_status, created_at, category)
    row = Ticket(receipt_no=f"RCPT-{n}", draft_id=n, inquiry_id=inquiry.id, session_id=n, summary="요약", category_code=category,
                 urgency=urgency, group_id=group, assignee_id=assignee, work_status=work, jira_sync_status=jira,
                 assign_status=assign, transition_status=transition, created_at=created_at or at(10))
    db.add(row)
    db.flush()
    return row


def get(client, users, who, path, **params):
    return client.get(f"{API}{path}", headers=users[who]["headers"], params=params or QUERY)


# ------------------------------------------------------------------ 공통


@pytest.mark.parametrize("path", ["/dashboard/overview", "/dashboard/ai-usage", "/dashboard/me"])
@pytest.mark.parametrize("params", [{"from": "2026-10-02", "to": "2026-10-01"}, {"from": "2025-01-01", "to": "2026-10-01"}])
def test_invalid_period(client, users, path, params):
    res = get(client, users, "admin", path, **params)
    assert (res.status_code, error_code(res)) == (400, "INVALID_REQUEST")


@pytest.mark.parametrize("path", ["/dashboard/overview", "/dashboard/ai-usage", "/dashboard/me"])
def test_invalid_date_format(client, users, path):
    assert get(client, users, "admin", path, **{"from": "어제"}).status_code == 422


def test_invalid_interval(client, users):
    assert get(client, users, "admin", "/dashboard/overview", interval="YEAR").status_code == 422


def test_one_year_is_allowed(client, users):
    assert get(client, users, "admin", "/dashboard/overview", **{"from": "2025-10-31", "to": "2026-10-31"}).status_code == 200


def test_default_period_is_last_30_days(client, users):
    period = client.get(f"{API}/dashboard/overview", headers=users["admin"]["headers"]).json()["period"]
    days = datetime.fromisoformat(period["to"]) - datetime.fromisoformat(period["from"])
    assert (days.days, period["interval"]) == (29, "DAY")


@pytest.mark.parametrize("who, path, status", [
    ("employee", "/dashboard/overview", 403), ("agent", "/dashboard/overview", 403),
    ("employee", "/dashboard/ai-usage", 403), ("agent", "/dashboard/ai-usage", 403),
    ("employee", "/dashboard/me", 403), ("agent", "/dashboard/me", 200), ("admin", "/dashboard/me", 200),
])
def test_permissions(client, users, who, path, status):
    assert get(client, users, who, path).status_code == status


# ------------------------------------------------------------------ OP-01


def test_overview_totals_keep_ai_and_closed_apart(client, db, users):
    me = users["employee"]["id"]
    add_inquiry(db, me, "AI_RESOLVED")
    add_inquiry(db, me, "IN_PROGRESS", action="ANSWER")                 # 미확인
    add_inquiry(db, me, "IN_PROGRESS", action="ASK_MORE")
    add_inquiry(db, me, "UNCONFIRMED")                                  # 저장값만으로 미확인으로 세지 않는다
    add_inquiry(db, me, "CLOSED_UNRESOLVED")
    add_ticket(db, me, "CLS", assignee=users["agent"]["id"], inquiry_status="HANDED_OFF")
    add_ticket(db, me, "WIP", assignee=users["agent"]["id"], inquiry_status="HANDED_OFF")
    add_ticket(db, me, "FIN", assignee=users["agent"]["id"], inquiry_status="HANDED_OFF")
    add_ticket(db, me, None, jira="NEEDS_ADMIN", assign="PENDING")
    db.commit()

    assert get(client, users, "admin", "/dashboard/overview").json()["totals"] == {
        "inquiryCount": 9, "aiResolvedCount": 1, "unconfirmedCount": 1, "unresolvedCount": 1, "ticketCount": 4,
        "receivedCount": 1, "inProgressCount": 1, "awaitingConfirmCount": 1, "closedCount": 1, "needsAdminCount": 1,
    }


def test_overview_answered_inquiry_with_ticket_is_not_unconfirmed(client, db, users):
    me = users["employee"]["id"]
    ticket = add_ticket(db, me, "WIP", assignee=users["agent"]["id"])
    inquiry = db.get(Inquiry, ticket.inquiry_id)
    inquiry.status, inquiry.action = "IN_PROGRESS", "ANSWER"
    db.commit()

    assert get(client, users, "admin", "/dashboard/overview").json()["totals"]["unconfirmedCount"] == 0


def test_overview_counts_only_period_in_kst(client, db, users):
    me = users["employee"]["id"]
    add_inquiry(db, me, created_at=datetime(2026, 10, 1, 0, 0, tzinfo=KST).astimezone(timezone.utc))  # 포함 (시작 경계)
    add_inquiry(db, me, created_at=datetime(2026, 9, 30, 23, 59, tzinfo=KST).astimezone(timezone.utc))  # 제외
    add_inquiry(db, me, created_at=datetime(2026, 10, 31, 23, 59, tzinfo=KST).astimezone(timezone.utc))  # 포함 (끝 경계)
    add_inquiry(db, me, created_at=datetime(2026, 11, 1, 0, 0, tzinfo=KST).astimezone(timezone.utc))  # 제외
    db.commit()

    body = get(client, users, "admin", "/dashboard/overview").json()
    assert body["totals"]["inquiryCount"] == 2
    assert body["trend"][0] == {"date": "2026-10-01", "inquiryCount": 1, "aiResolvedCount": 0, "ticketCount": 0, "closedCount": 0}


def test_overview_trend_fills_empty_days(client, users):
    trend = get(client, users, "admin", "/dashboard/overview").json()["trend"]
    assert len(trend) == 31
    assert trend[-1]["date"] == "2026-10-31"


def test_overview_week_buckets_start_from_period_start(client, db, users):
    add_inquiry(db, users["employee"]["id"], created_at=at(8))
    db.commit()

    trend = get(client, users, "admin", "/dashboard/overview", interval="WEEK", **QUERY).json()["trend"]
    assert [t["date"] for t in trend] == ["2026-10-01", "2026-10-08", "2026-10-15", "2026-10-22", "2026-10-29"]
    assert trend[1]["inquiryCount"] == 1


def test_overview_month_buckets_clip_first_month(client, db, users):
    add_inquiry(db, users["employee"]["id"], created_at=at(20))
    db.commit()

    trend = get(client, users, "admin", "/dashboard/overview", interval="MONTH",
                **{"from": "2026-09-15", "to": "2026-11-02"}).json()["trend"]
    assert [t["date"] for t in trend] == ["2026-09-15", "2026-10-01", "2026-11-01"]
    assert trend[1]["inquiryCount"] == 1


def test_overview_breakdowns(client, db, users):
    me, agent, colleague = users["employee"]["id"], users["agent"]["id"], users["colleague"]["id"]
    add_inquiry(db, me, "AI_RESOLVED", category="SW")
    add_ticket(db, me, "CLS", assignee=agent, urgency="P1")
    add_ticket(db, me, "WIP", assignee=colleague)
    add_ticket(db, me, "RDY", assignee=None)
    add_ticket(db, me, "WIP", group=3, assignee=agent, category="SW")   # 비활성 그룹, 구성원 아님
    db.commit()

    body = get(client, users, "admin", "/dashboard/overview").json()
    assert body["byCategory"] == [
        {"categoryCode": "NET", "name": "네트워크", "inquiryCount": 3, "aiResolvedCount": 0, "ticketCount": 3, "closedCount": 1},
        {"categoryCode": "SW", "name": "SW", "inquiryCount": 2, "aiResolvedCount": 1, "ticketCount": 1, "closedCount": 0},
    ]
    assert body["byUrgency"] == [{"urgency": "P1", "ticketCount": 1}, {"urgency": "P2", "ticketCount": 3},
                                 {"urgency": "P3", "ticketCount": 0}, {"urgency": "P4", "ticketCount": 0}]
    assert body["byGroup"] == [
        {"groupId": 1, "name": "네트워크팀", "rdy": 1, "wip": 1, "fin": 0, "cls": 1},
        {"groupId": 2, "name": "SW팀", "rdy": 0, "wip": 0, "fin": 0, "cls": 0},
        {"groupId": 3, "name": "해체팀", "rdy": 0, "wip": 1, "fin": 0, "cls": 0},
    ]
    wip_at = "2026-10-10T12:00:00+09:00"          # WIP 이력이 없으면 접수 시각이 시작 시각이다
    assert body["byMember"] == [
        {"userId": colleague, "name": "가동료", "groupId": 1, "rdy": 0, "wip": 1, "fin": 0, "cls": 0, "oldestWipSince": wip_at},
        {"userId": agent, "name": "나담당", "groupId": 1, "rdy": 0, "wip": 0, "fin": 0, "cls": 1, "oldestWipSince": None},
        {"userId": agent, "name": "나담당", "groupId": 3, "rdy": 0, "wip": 1, "fin": 0, "cls": 0, "oldestWipSince": wip_at},
    ]


def add_wip_entry(db, ticket, changed_at):
    db.add(TicketStatusHistory(ticket_id=ticket.id, from_status="RDY", to_status="WIP", source="JIRA", changed_at=changed_at))


def test_overview_member_oldest_wip_since(client, db, users):
    me, agent, colleague = users["employee"]["id"], users["agent"]["id"], users["colleague"]["id"]
    old = add_ticket(db, me, "WIP", assignee=agent, created_at=at(2))
    add_wip_entry(db, old, at(3))
    newer = add_ticket(db, me, "WIP", assignee=agent, created_at=at(5))
    add_wip_entry(db, newer, at(6))
    returned = add_ticket(db, me, "WIP", assignee=colleague, created_at=at(1))     # FIN 에서 되돌아온 건은 다시 WIP 가 된 시각부터
    add_wip_entry(db, returned, at(2))
    add_wip_entry(db, returned, at(8))
    add_ticket(db, me, "RDY", assignee=colleague, created_at=at(1))                # 아직 시작 전
    add_ticket(db, me, "WIP", assignee=colleague, created_at=at(1), assign="PENDING")   # 예약은 처리 중이 아니다
    db.commit()

    by_member = {m["userId"]: m for m in get(client, users, "admin", "/dashboard/overview").json()["byMember"]}
    assert by_member[agent]["oldestWipSince"] == "2026-10-03T12:00:00+09:00"
    assert by_member[colleague]["oldestWipSince"] == "2026-10-08T12:00:00+09:00"


def test_overview_member_oldest_wip_since_ignores_selected_period(client, db, users):
    me, agent = users["employee"]["id"], users["agent"]["id"]
    ticket = add_ticket(db, me, "WIP", assignee=agent, created_at=at(2))            # 선택 기간(10.20~10.31) 밖에서 접수
    add_wip_entry(db, ticket, at(3))
    db.commit()

    body = get(client, users, "admin", "/dashboard/overview", **{"from": "2026-10-20", "to": "2026-10-31"}).json()
    member = next(m for m in body["byMember"] if m["userId"] == agent)
    assert (member["wip"], member["oldestWipSince"]) == (0, "2026-10-03T12:00:00+09:00")   # 기간 집계에는 안 잡혀도 멈춘 건은 보인다


def test_overview_ticket_without_work_status_is_not_in_work_counts(client, db, users):
    add_ticket(db, users["employee"]["id"], None, jira="PENDING", assign="PENDING")
    db.commit()

    body = get(client, users, "admin", "/dashboard/overview").json()
    assert body["totals"]["ticketCount"] == 1
    assert body["byGroup"][0] == {"groupId": 1, "name": "네트워크팀", "rdy": 0, "wip": 0, "fin": 0, "cls": 0}


# ------------------------------------------------------------------ OP-02


def test_me_counts_mine_and_my_groups(client, db, users):
    me, agent, colleague = users["employee"]["id"], users["agent"]["id"], users["colleague"]["id"]
    add_ticket(db, me, "WIP", assignee=agent)
    add_ticket(db, me, "CLS", assignee=agent, group=2)                  # 내 접수지만 소속 그룹 밖
    add_ticket(db, me, "RDY", assignee=colleague)
    add_ticket(db, me, "RDY", group=2, assignee=None)                   # 소속 그룹 밖
    db.commit()

    body = get(client, users, "agent", "/dashboard/me").json()
    assert body["period"] == {"from": "2026-10-01", "to": "2026-10-31"}
    assert body["me"] == {"rdy": 0, "wip": 1, "fin": 0, "cls": 1}
    assert body["groups"] == [{
        "groupId": 1, "name": "네트워크팀", "rdy": 1, "wip": 1, "fin": 0, "cls": 0,
        "members": [
            {"userId": colleague, "name": "가동료", "rdy": 1, "wip": 0, "fin": 0, "cls": 0},
            {"userId": agent, "name": "나담당", "rdy": 0, "wip": 1, "fin": 0, "cls": 0},
        ],
    }]


def test_me_without_group(client, users):
    body = get(client, users, "admin", "/dashboard/me").json()
    assert (body["me"], body["groups"]) == ({"rdy": 0, "wip": 0, "fin": 0, "cls": 0}, [])


def test_me_skips_inactive_group(client, db, users):
    db.add(SupportGroupMember(group_id=3, user_id=users["agent"]["id"], member_role="AGENT", assignable=True))
    db.commit()

    assert [g["groupId"] for g in get(client, users, "agent", "/dashboard/me").json()["groups"]] == [1]


# ------------------------------------------------------------------ OP-03


def add_call(db, purpose="CLASSIFY", model="m1", adapter="Claude", latency=100, tokens=(1000, 100), success=True, created_at=None):
    db.add(LlmCall(purpose=purpose, model=model, adapter=adapter, latency_ms=latency, input_tokens=tokens[0],
                   output_tokens=tokens[1], success=success, created_at=created_at or at(10)))


@pytest.fixture
def priced(monkeypatch):
    monkeypatch.setattr(llm_constants, "MODEL_PRICES_USD_PER_MTOK", {"m1": (3.0, 15.0)})
    monkeypatch.setattr(llm_constants, "MONTHLY_BUDGET_USD", 30.0)


def test_ai_usage_totals(client, db, users, priced):
    me = users["employee"]["id"]
    add_inquiry(db, me, "AI_RESOLVED")
    add_inquiry(db, me, "AI_RESOLVED")
    add_inquiry(db, me, "CLOSED_UNRESOLVED")
    add_call(db, tokens=(1_000_000, 100_000))                           # 3 + 1.5 USD
    add_call(db, purpose="ANSWER", latency=300, tokens=(None, None), success=False)
    add_call(db, purpose="ANSWER", latency=None, tokens=(1_000_000, 0))  # 3 USD
    db.commit()

    body = get(client, users, "admin", "/dashboard/ai-usage").json()
    assert body["totals"] == {
        "aiConsultationCount": 3, "aiResolvedCount": 2, "aiResolvedRate": 0.667, "callCount": 3, "failedCount": 1,
        "avgLatencyMs": 200, "inputTokens": 2_000_000, "outputTokens": 100_000, "estimatedCost": 7.5,
        "unpricedModels": [], "budget": 31.0, "budgetUsageRate": 0.242,
    }
    assert body["byPurpose"] == [
        {"purpose": "ANSWER", "callCount": 2, "failedCount": 1, "avgLatencyMs": 300, "inputTokens": 1_000_000, "outputTokens": 0},
        {"purpose": "CLASSIFY", "callCount": 1, "failedCount": 0, "avgLatencyMs": 100, "inputTokens": 1_000_000, "outputTokens": 100_000},
    ]
    assert body["byModel"] == [{"model": "m1", "adapter": "Claude", "callCount": 3, "inputTokens": 2_000_000,
                                "outputTokens": 100_000, "estimatedCost": 7.5}]
    day = next(t for t in body["trend"] if t["date"] == "2026-10-10")
    assert day == {"date": "2026-10-10", "aiConsultationCount": 3, "aiResolvedCount": 2, "callCount": 3, "estimatedCost": 7.5}


def test_ai_usage_unpriced_model_is_reported_not_counted_as_zero(client, db, users, priced):
    add_call(db, model="m1", tokens=(1_000_000, 0))
    add_call(db, model="unknown", tokens=(1_000_000, 0))
    add_call(db, model="mock", adapter="Mock", tokens=(1_000_000, 0))
    db.commit()

    body = get(client, users, "admin", "/dashboard/ai-usage").json()
    assert (body["totals"]["estimatedCost"], body["totals"]["unpricedModels"]) == (3.0, ["unknown"])
    assert {m["model"]: m["estimatedCost"] for m in body["byModel"]} == {"m1": 3.0, "unknown": None, "mock": 0.0}


def test_ai_usage_empty_and_no_budget(client, users, monkeypatch):
    monkeypatch.setattr(llm_constants, "MONTHLY_BUDGET_USD", None)
    totals = get(client, users, "admin", "/dashboard/ai-usage").json()["totals"]
    assert (totals["aiResolvedRate"], totals["avgLatencyMs"], totals["budget"], totals["budgetUsageRate"]) == (0, None, None, None)


def test_ai_usage_trend_month(client, db, users, priced):
    add_call(db, created_at=at(10))
    db.commit()

    trend = get(client, users, "admin", "/dashboard/ai-usage", interval="MONTH", **{"from": "2026-09-15", "to": "2026-10-31"}).json()["trend"]
    assert [(t["date"], t["callCount"]) for t in trend] == [("2026-09-15", 0), ("2026-10-01", 1)]


# ------------------------------------------------------------------ OP-04


@pytest.fixture
def logs(db, users):
    db.add_all([
        AuditLog(event_type="REASSIGN", target_type="ticket", target_id=42, actor_id=users["admin"]["id"], result="a → b",
                 reason="휴가", created_at=at(1)),
        AuditLog(event_type="CONFIRM", target_type="ticket", target_id=43, actor_id=users["employee"]["id"], created_at=at(2)),
        AuditLog(event_type="DOCUMENT_DEACTIVATE", target_type="document", target_id=42, created_at=at(3)),
    ])
    db.commit()


def audit(client, users, who="admin", **params):
    return client.get(f"{API}/audit-logs", headers=users[who]["headers"], params=params)


def test_audit_logs_default_newest_first(client, users, logs):
    body = audit(client, users).json()
    assert [i["eventType"] for i in body["items"]] == ["DOCUMENT_DEACTIVATE", "CONFIRM", "REASSIGN"]
    assert (body["size"], body["totalCount"]) == (50, 3)
    assert body["items"][0]["actor"] is None
    assert body["items"][2]["actor"]["id"] == users["admin"]["id"]
    assert (body["items"][2]["result"], body["items"][2]["reason"]) == ("a → b", "휴가")
    assert body["items"][2]["createdAt"].endswith("+09:00")


@pytest.mark.parametrize("params, expected", [
    ({"eventType": ["CONFIRM", "REASSIGN"]}, ["CONFIRM", "REASSIGN"]),
    ({"targetType": "ticket", "targetId": 42}, ["REASSIGN"]),
    ({"targetType": "document"}, ["DOCUMENT_DEACTIVATE"]),
    ({"createdFrom": "2026-10-02", "createdTo": "2026-10-02"}, ["CONFIRM"]),
    ({"sort": "createdAt,asc"}, ["REASSIGN", "CONFIRM", "DOCUMENT_DEACTIVATE"]),
])
def test_audit_logs_filters(client, users, logs, params, expected):
    assert [i["eventType"] for i in audit(client, users, **params).json()["items"]] == expected


def test_audit_logs_actor_filter(client, users, logs):
    items = audit(client, users, actorId=users["employee"]["id"]).json()["items"]
    assert [i["eventType"] for i in items] == ["CONFIRM"]


@pytest.mark.parametrize("params", [{"targetId": 42}, {"createdFrom": "2026-10-03", "createdTo": "2026-10-02"}])
def test_audit_logs_invalid(client, users, logs, params):
    res = audit(client, users, **params)
    assert (res.status_code, error_code(res)) == (400, "INVALID_REQUEST")


def test_audit_logs_size_limit(client, users, logs):
    assert audit(client, users, size=101).status_code == 422


@pytest.mark.parametrize("who", ["employee", "agent"])
def test_audit_logs_admin_only(client, users, logs, who):
    assert audit(client, users, who).status_code == 403


def test_audit_logs_ticket_link(client, db, users):
    no_ticket = add_inquiry(db, users["employee"]["id"])
    ticket = add_ticket(db, users["employee"]["id"])
    assert no_ticket.id == ticket.id != ticket.inquiry_id   # 번호가 겹쳐도 대상 종류가 다르면 연결하지 않는지 보려는 조건
    expected = {
        "CONFIRM": (ticket.id, ticket.receipt_no),
        "SENSITIVE_INPUT": (ticket.id, ticket.receipt_no),
        "URGENT_CLOSED": (None, None),
        "DOCUMENT_ACTIVATE": (None, None),
        "USER_CREATE": (None, None),
        "FAQ_DELETE": (None, None),
    }
    db.add_all([
        AuditLog(event_type="CONFIRM", target_type="ticket", target_id=ticket.id, created_at=at(1)),
        AuditLog(event_type="SENSITIVE_INPUT", target_type="inquiry", target_id=ticket.inquiry_id, created_at=at(2)),
        AuditLog(event_type="URGENT_CLOSED", target_type="inquiry", target_id=no_ticket.id, created_at=at(3)),
        AuditLog(event_type="DOCUMENT_ACTIVATE", target_type="document", target_id=ticket.id, created_at=at(4)),
        AuditLog(event_type="USER_CREATE", target_type="user", target_id=ticket.id, created_at=at(5)),
        AuditLog(event_type="FAQ_DELETE", target_type="faq", target_id=ticket.id, created_at=at(6)),
    ])
    db.commit()
    body = audit(client, users).json()
    assert {i["eventType"]: (i["ticketId"], i["receiptNo"]) for i in body["items"]} == expected
    assert body["totalCount"] == len(body["items"]) == len(expected)


def test_audit_logs_ticket_not_found_is_null(client, users, logs):
    items = audit(client, users, targetType="ticket", targetId=42).json()["items"]
    assert [(i["ticketId"], i["receiptNo"]) for i in items] == [(None, None)]
