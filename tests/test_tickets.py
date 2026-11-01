"""접수 API (TK-01~06·08) — SQLite 메모리 DB. 문의는 Mock 모델로 판단 흐름을 돌려 만든다."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import (
    AssignmentLog,
    AuditLog,
    Category,
    ChatSession,
    Inquiry,
    InquiryAssessment,
    InquiryType,
    IntegrationJob,
    SupportGroup,
    SupportGroupMember,
    Ticket,
    TicketDraft,
    TicketStatusHistory,
)
from test_auth import add_user, bearer, client, error_code, login  # noqa: F401 (픽스처)
from test_flow_correct import DOC
from test_inquiries import ANSWER, INQUIRY_TABLES, ai, ai_reply, create_sqlite_tables, headers, owner, start, taxonomy  # noqa: F401

DRAFTS = "/api/v1/ticket-drafts"
TICKETS = "/api/v1/tickets"


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    create_sqlite_tables(engine, INQUIRY_TABLES + ["integration_jobs", "assignment_logs", "ticket_status_history"])
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def answered(client, ai, headers, taxonomy):
    """AI 답변까지 받은 문의 id. 세부 유형 NET-02, 긴급도 P3, 추천 그룹 네트워크팀."""
    ai.replies = [ai_reply("ANSWER", inquiry_type_code="NET-02"), ANSWER]
    ai.documents = (DOC,)
    return start(client, headers).json()["inquiry"]["id"]


def create_draft(client, headers, inquiry_id):
    return client.post(f"/api/v1/inquiries/{inquiry_id}/ticket-drafts", headers=headers)


def patch_draft(client, headers, draft_id, body):
    return client.patch(f"{DRAFTS}/{draft_id}", json=body, headers=headers)


def confirm(client, headers, draft_id, updated_at=None):
    return client.post(TICKETS, json={"draftId": draft_id, "draftUpdatedAt": updated_at}, headers=headers)


@pytest.fixture
def draft(client, headers, answered):
    return create_draft(client, headers, answered).json()


def add_type(db, code, default_urgency, group_name):
    group = SupportGroup(name=group_name)
    db.add(group)
    db.flush()
    inquiry_type = InquiryType(code=code, category_code="NET", name=code, request_kind="INCIDENT",
                               default_urgency=default_urgency, default_group_id=group.id)
    db.add(inquiry_type)
    db.commit()
    return inquiry_type


# ---------------------------------------------------------------- TK-01 초안 생성

def test_create_draft_from_last_assessment(client, db, headers, answered, taxonomy):
    net, _, vpn = taxonomy

    res = create_draft(client, headers, answered)

    assert res.status_code == 201
    body = res.json()
    assert (body["inquiryId"], body["status"], body["updatedAt"]) == (answered, "EDITING", None)
    assert body["sessionId"] == db.scalar(select(ChatSession.id))
    assert (body["summary"], body["targetSystem"], body["occurredAt"]) == ("업데이트 이후 VPN 접속 불가", "사내 VPN", "어제")
    assert (body["symptom"], body["triedActions"]) == (None, None)
    assert (body["categoryCode"], body["inquiryTypeId"], body["urgency"]) == ("NET", vpn.id, "P3")
    assert body["urgencyReason"] == "재택 중 VPN 불가"
    assert body["recommendedGroup"] == {"id": net.id, "name": "네트워크팀"}
    assert body["inquiryType"] == {"id": vpn.id, "code": "NET-02", "name": "개인 VPN 접속 장애"}


def test_create_draft_without_assessment_goes_to_service_desk(client, db, headers, ai, taxonomy):
    _, desk, _ = taxonomy
    ai.broken = True
    start(client, headers)                                  # AI 실패(503)여도 문의는 저장된다
    inquiry_id = db.scalar(select(Inquiry.id))

    body = create_draft(client, headers, inquiry_id).json()

    assert (body["summary"], body["urgency"], body["categoryCode"]) == (None, None, None)
    assert body["recommendedGroupId"] == desk.id


def test_create_draft_twice(client, headers, answered, draft):
    res = create_draft(client, headers, answered)

    assert res.status_code == 409
    assert error_code(res) == "DRAFT_ALREADY_EXISTS"
    assert res.json()["error"]["details"] == [{"reason": "DRAFT_ID", "message": "작성 중인 초안", "value": draft["id"]}]


@pytest.mark.parametrize("status, code", [
    ("CLOSED_UNRESOLVED", "INQUIRY_CLOSED"), ("AI_RESOLVED", "INQUIRY_CLOSED"), ("RECEIVED", "INQUIRY_INVALID_STATE"),
])
def test_create_draft_outside_progress(client, db, headers, answered, status, code):
    db.get(Inquiry, answered).status = status
    db.commit()

    assert error_code(create_draft(client, headers, answered)) == code


def test_create_draft_only_by_owner(client, db, answered):
    add_user(db, "E0002", service_role="ADMIN")

    assert error_code(create_draft(client, bearer(login(client, "E0002")), answered)) == "INQUIRY_NOT_FOUND"


# ---------------------------------------------------------------- TK-02 초안 조회

def test_get_draft(client, headers, draft):
    res = client.get(f"{DRAFTS}/{draft['id']}", headers=headers)

    assert res.status_code == 200
    assert res.json() == draft


def test_get_draft_of_other_user(client, db, draft):
    add_user(db, "E0002")

    res = client.get(f"{DRAFTS}/{draft['id']}", headers=bearer(login(client, "E0002")))

    assert error_code(res) == "DRAFT_NOT_FOUND"


# ---------------------------------------------------------------- TK-03 초안 수정·취소

def test_update_draft_fields(client, headers, draft):
    res = patch_draft(client, headers, draft["id"], {"symptom": " 인증 서버 오류 ", "triedActions": None,
                                                     "businessImpact": "재택 근무 불가"})

    assert res.status_code == 200
    body = res.json()
    assert body["changes"] == []
    saved = body["draft"]
    assert (saved["symptom"], saved["businessImpact"], saved["triedActions"]) == ("인증 서버 오류", "재택 근무 불가", None)
    assert saved["summary"] == draft["summary"]             # 보내지 않은 필드는 그대로
    assert saved["updatedAt"] is not None


def test_change_type_recalculates_urgency_and_group(client, db, headers, draft, taxonomy):
    security = add_type(db, "NET-09", "P2", "보안팀")

    body = patch_draft(client, headers, draft["id"], {"inquiryTypeId": security.id}).json()

    assert body["changes"] == [
        {"field": "urgency", "before": "P3", "after": "P2", "reason": "세부 유형 NET-09 기본 긴급도"},
        {"field": "recommendedGroupId", "before": draft["recommendedGroupId"], "after": security.default_group_id,
         "reason": "세부 유형 NET-09 기본 그룹"},
    ]
    saved = body["draft"]
    assert (saved["inquiryTypeId"], saved["urgency"], saved["urgencyReason"]) == (security.id, "P2", "세부 유형 NET-09 기본 긴급도")


def test_change_type_does_not_lower_urgency(client, db, headers, draft):
    minor = add_type(db, "NET-05", "P4", "네트워크2팀")

    body = patch_draft(client, headers, draft["id"], {"inquiryTypeId": minor.id}).json()

    assert [c["field"] for c in body["changes"]] == ["recommendedGroupId"]
    assert body["draft"]["urgency"] == "P3"


def test_clear_type_sends_to_service_desk(client, headers, draft, taxonomy):
    _, desk, _ = taxonomy

    body = patch_draft(client, headers, draft["id"], {"inquiryTypeId": None}).json()

    assert [(c["field"], c["after"]) for c in body["changes"]] == [("categoryCode", None), ("recommendedGroupId", desk.id)]
    assert body["draft"]["inquiryTypeId"] is None


@pytest.mark.parametrize("body, field, reason", [
    ({"urgency": "P1"}, "urgency", "NOT_ALLOWED"),
    ({"recommendedGroupId": 1}, "recommendedGroupId", "NOT_ALLOWED"),
    ({"status": "CANCELLED", "summary": "요약"}, "summary", "NOT_ALLOWED"),
    ({"status": "CONFIRMED"}, "status", "INVALID_VALUE"),
    ({"inquiryTypeId": 999}, "inquiryTypeId", "NOT_FOUND"),
    ({"summary": "가" * 2001}, "summary", "TOO_LONG"),
    ({"targetSystem": "가" * 101}, "targetSystem", "TOO_LONG"),
])
def test_update_draft_validation(client, headers, draft, body, field, reason):
    res = patch_draft(client, headers, draft["id"], body)

    assert res.status_code == 422
    detail = res.json()["error"]["details"][0]
    assert (detail["field"], detail["reason"]) == (field, reason)


def test_cancel_draft_closes_inquiry(client, db, headers, answered, draft):
    res = patch_draft(client, headers, draft["id"], {"status": "CANCELLED"})

    assert res.status_code == 200
    assert res.json() == {"draft": res.json()["draft"] | {"status": "CANCELLED"}, "changes": []}
    inquiry = db.get(Inquiry, answered)
    assert (inquiry.status, inquiry.closed_at is not None) == ("CLOSED_UNRESOLVED", True)
    session = db.scalar(select(ChatSession))
    assert (session.ended_at is not None, session.end_reason) == (True, "USER_END")


def test_cancel_urgent_draft_leaves_audit_log(client, db, headers, answered, draft):
    db.add(InquiryAssessment(inquiry_id=answered, urgent_signal=True, action="ESCALATE", override_reasons=[]))
    db.commit()

    patch_draft(client, headers, draft["id"], {"status": "CANCELLED"})

    assert db.scalar(select(AuditLog.event_type)) == "URGENT_CLOSED"


def test_update_cancelled_draft(client, headers, draft):
    patch_draft(client, headers, draft["id"], {"status": "CANCELLED"})

    res = patch_draft(client, headers, draft["id"], {"summary": "다시"})

    assert res.status_code == 409
    assert res.json()["error"]["details"] == [{"reason": "CURRENT_STATUS", "message": "현재 상태", "value": "CANCELLED"}]


def test_update_draft_of_other_user(client, db, draft):
    add_user(db, "E0002")

    res = patch_draft(client, bearer(login(client, "E0002")), draft["id"], {"summary": "남의 초안"})

    assert error_code(res) == "DRAFT_NOT_FOUND"


# ---------------------------------------------------------------- TK-04 최종 접수

def test_confirm_creates_ticket(client, db, owner, headers, answered, draft):
    res = confirm(client, headers, draft["id"])

    assert res.status_code == 201
    body = res.json()
    ticket = db.scalar(select(Ticket))
    assert body["receiptNo"] == ticket.receipt_no == f"RCPT-{ticket.id:04d}"
    assert (body["draftId"], body["inquiryId"], body["summary"]) == (draft["id"], answered, draft["summary"])
    assert body["requester"]["id"] == owner.id
    assert (body["groupId"], body["urgency"], body["categoryCode"]) == (draft["recommendedGroupId"], "P3", "NET")
    assert (body["jiraSyncStatus"], body["assignStatus"], body["workStatus"]) == ("PENDING", "PENDING", None)
    assert (body["transitionStatus"], body["needsAdmin"], body["displayStatus"]) == ("IDLE", False, "received")
    assert (body["jiraKey"], body["jiraUrl"], body["assignee"]) == (None, None, None)

    assert db.get(TicketDraft, draft["id"]).status == "CONFIRMED"
    assert db.get(Inquiry, answered).status == "RECEIVED"
    session = db.scalar(select(ChatSession))
    assert (session.ended_at is not None, session.end_reason) == (True, "HANDED_OFF")
    job = db.scalar(select(IntegrationJob))
    assert (job.job_type, job.status, job.idempotency_key) == ("JIRA_CREATE", "PENDING", f"create:{ticket.receipt_no}")
    log = db.scalar(select(AssignmentLog))
    assert (log.event, log.group_id, log.rule_id, log.actor_id) == ("RECOMMEND", ticket.group_id, None, None)
    audit = db.scalar(select(AuditLog))
    assert (audit.event_type, audit.target_id, audit.actor_id) == ("CONFIRM", ticket.id, owner.id)


def test_confirm_again_returns_existing_ticket(client, db, headers, draft, monkeypatch):
    first = confirm(client, headers, draft["id"]).json()
    db.scalar(select(Ticket)).jira_key = "ITHD-1520"
    db.commit()
    monkeypatch.setenv("JIRA_BASE_URL", "https://jira.example/")

    res = confirm(client, headers, draft["id"])

    assert res.status_code == 200
    assert (res.json()["id"], res.json()["jiraUrl"]) == (first["id"], "https://jira.example/browse/ITHD-1520")
    assert len(db.scalars(select(Ticket)).all()) == 1
    assert len(db.scalars(select(IntegrationJob)).all()) == 1


def test_confirm_requires_latest_updated_at(client, db, headers, draft):
    updated_at = patch_draft(client, headers, draft["id"], {"symptom": "오류 코드 809"}).json()["draft"]["updatedAt"]

    stale = confirm(client, headers, draft["id"])                      # 수정 전 화면 값(null)

    assert stale.status_code == 409
    assert error_code(stale) == "DRAFT_RECONFIRM_REQUIRED"
    assert stale.json()["error"]["details"][0]["value"] == updated_at
    assert db.scalar(select(Ticket)) is None
    assert confirm(client, headers, draft["id"], updated_at).status_code == 201


def test_confirm_requires_summary(client, db, headers, draft):
    db.get(TicketDraft, draft["id"]).summary = None
    db.commit()

    res = confirm(client, headers, draft["id"])

    assert res.status_code == 422
    assert res.json()["error"]["details"] == [{"field": "summary", "reason": "REQUIRED", "message": "문의 요약을 입력해 주세요."}]


def test_confirm_cancelled_draft(client, headers, draft):
    patch_draft(client, headers, draft["id"], {"status": "CANCELLED"})

    assert error_code(confirm(client, headers, draft["id"])) == "DRAFT_NOT_EDITABLE"


def test_confirm_draft_of_other_user(client, db, draft):
    add_user(db, "E0002")

    assert error_code(confirm(client, bearer(login(client, "E0002")), draft["id"])) == "DRAFT_NOT_FOUND"


def test_confirm_save_failure_keeps_draft(client, db, headers, answered, draft, monkeypatch):
    def broken(*_):
        raise OperationalError("insert", {}, Exception("db down"))
    monkeypatch.setattr("app.services.ticket.enqueue_jira_create", broken)

    res = confirm(client, headers, draft["id"])

    assert res.status_code == 500
    assert error_code(res) == "TICKET_SAVE_FAILED"
    assert db.get(TicketDraft, draft["id"]).status == "EDITING"
    assert db.get(Inquiry, answered).status == "IN_PROGRESS"
    assert db.scalar(select(Ticket)) is None


# ---------------------------------------------------------------- TK-05 접수 목록·TK-06 상세·TK-08 상태 이력

def make_ticket(db, requester, group=None, created_at=None, **fields):
    """대화 없이 접수까지 마친 문의를 만든다."""
    inquiry = Inquiry(user_id=requester.id, status="RECEIVED")
    db.add(inquiry)
    db.flush()
    session = ChatSession(inquiry_id=inquiry.id)
    db.add(session)
    db.flush()
    draft = TicketDraft(inquiry_id=inquiry.id, session_id=session.id, status="CONFIRMED")
    db.add(draft)
    db.flush()
    values = {"summary": "VPN 접속 불가", "jira_sync_status": "SYNCED", "assign_status": "ASSIGNED"} | fields
    ticket = Ticket(receipt_no=f"RCPT-{draft.id:04d}", draft_id=draft.id, inquiry_id=inquiry.id, session_id=session.id,
                    group_id=group.id if group else None, **values)
    if created_at is not None:
        ticket.created_at = created_at
    db.add(ticket)
    db.commit()
    return ticket


def add_member(db, group, user, is_active=True):
    db.add(SupportGroupMember(group_id=group.id, user_id=user.id, member_role="AGENT", assignable=True,
                              is_active=is_active))
    db.commit()


@pytest.fixture
def staff(db, owner):
    """네트워크팀(AGENT E0002 소속)·보안팀, 문의자 owner·E0003. 접수 3건: 내 것 2건(네트워크·보안), 남의 것 1건(네트워크)."""
    net, sec = SupportGroup(name="네트워크팀"), SupportGroup(name="보안팀")
    db.add_all([net, sec])
    db.flush()
    agent = add_user(db, "E0002", name="박서준", service_role="AGENT")
    other = add_user(db, "E0003")
    add_member(db, net, agent)
    mine = make_ticket(db, owner, net, work_status="WIP", assignee_id=agent.id, jira_key="ITHD-1520")
    secret = make_ticket(db, owner, sec, work_status="RDY", summary="계정 도용 의심")
    others = make_ticket(db, other, net, work_status=None, jira_sync_status="NEEDS_ADMIN", assign_status="PENDING")
    return {"net": net, "sec": sec, "agent": agent, "mine": mine, "secret": secret, "others": others}


def listed(client, headers, **params):
    return client.get(TICKETS, params=params, headers=headers)


def ids(res):
    return [item["id"] for item in res.json()["items"]]


def as_user(client, employee_no):
    return bearer(login(client, employee_no))


def test_requester_sees_own_tickets(client, headers, staff):
    res = listed(client, headers)

    assert res.status_code == 200
    assert ids(res) == [staff["secret"].id, staff["mine"].id]        # 기본 createdAt desc, 같으면 id desc
    assert res.json()["totalCount"] == 2


def test_summary_fields(client, owner, headers, staff):
    item = next(i for i in listed(client, headers).json()["items"] if i["id"] == staff["mine"].id)

    assert item["receiptNo"] == staff["mine"].receipt_no
    assert (item["jiraKey"], item["summary"], item["urgency"]) == ("ITHD-1520", "VPN 접속 불가", None)
    assert item["requester"] == {"id": owner.id, "employeeNo": "E0001", "name": "김민지"}
    assert item["group"] == {"id": staff["net"].id, "name": "네트워크팀"}
    assert item["assignee"] == {"id": staff["agent"].id, "employeeNo": "E0002", "name": "박서준"}
    assert (item["workStatus"], item["displayStatus"], item["needsAdmin"]) == ("WIP", "progress", False)
    assert (item["requestedWorkStatus"], item["transitionStatus"]) == (None, "IDLE")


def test_agent_sees_tickets_of_own_groups_by_default(client, staff):
    res = listed(client, as_user(client, "E0002"))

    assert set(ids(res)) == {staff["mine"].id, staff["others"].id}


def test_agent_of_inactive_membership_sees_nothing(client, db, staff):
    db.get(SupportGroupMember, (staff["net"].id, staff["agent"].id)).is_active = False
    db.commit()

    assert ids(listed(client, as_user(client, "E0002"))) == []


def test_agent_can_list_own_requests(client, db, staff):
    own = make_ticket(db, staff["agent"], staff["sec"])

    assert ids(listed(client, as_user(client, "E0002"), view="REQUESTER")) == [own.id]


def test_admin_sees_all_by_default(client, db, staff):
    add_user(db, "E0009", service_role="ADMIN")

    assert len(ids(listed(client, as_user(client, "E0009")))) == 3


@pytest.mark.parametrize("role, view", [("EMPLOYEE", "ASSIGNED"), ("EMPLOYEE", "ALL"), ("AGENT", "ALL")])
def test_view_outside_role_is_forbidden(client, db, role, view):
    add_user(db, "E0009", service_role=role)

    res = listed(client, as_user(client, "E0009"), view=view)

    assert res.status_code == 403
    assert error_code(res) == "FORBIDDEN"


@pytest.fixture
def admin(client, db, staff):
    add_user(db, "E0009", service_role="ADMIN")
    return as_user(client, "E0009")


@pytest.mark.parametrize("params, expected", [
    ({"workStatus": ["RDY", "WIP"]}, ["secret", "mine"]),
    ({"needsAdmin": "true"}, ["others"]),
    ({"needsAdmin": "false"}, ["secret", "mine"]),
    ({"jiraSyncStatus": "NEEDS_ADMIN"}, ["others"]),
    ({"assignStatus": "ASSIGNED"}, ["secret", "mine"]),
    ({"groupId": "net"}, ["others", "mine"]),
    ({"assigneeId": "agent"}, ["mine"]),
    ({"q": "ithd-15"}, ["mine"]),
    ({"q": "도용"}, ["secret"]),
    ({"q": "RCPT-0003"}, ["others"]),
])
def test_list_filters(client, admin, staff, params, expected):
    params = {k: staff[v].id if v in ("net", "agent") else v for k, v in params.items()}

    assert ids(listed(client, admin, **params)) == [staff[name].id for name in expected]


def test_list_filters_by_category_and_urgency(client, db, owner, admin, staff):
    db.add(Category(code="NET", name="VPN·네트워크"))
    hit = make_ticket(db, owner, category_code="NET", urgency="P2")
    make_ticket(db, owner, category_code="NET", urgency="P3")

    assert ids(listed(client, admin, categoryCode="NET", urgency="P2")) == [hit.id]
    assert listed(client, admin, categoryCode="NET").json()["items"][0]["category"] == {"code": "NET", "name": "VPN·네트워크"}


def test_list_filters_by_created_date_in_kst(client, db, owner):
    add_user(db, "E0009", service_role="ADMIN")
    admin = as_user(client, "E0009")
    before = make_ticket(db, owner, created_at=datetime(2026, 9, 30, 14, 59, tzinfo=timezone.utc))   # 9/30 23:59 KST
    after = make_ticket(db, owner, created_at=datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc))     # 10/1 00:00 KST

    assert ids(listed(client, admin, createdFrom="2026-10-01")) == [after.id]
    assert ids(listed(client, admin, createdTo="2026-09-30")) == [before.id]


def test_list_sorts_by_work_status(client, admin, staff):
    res = listed(client, admin, sort="workStatus,asc")

    assert ids(res) == [staff["others"].id, staff["secret"].id, staff["mine"].id]      # 생성 전 → RDY → WIP


def test_list_paging(client, admin, staff):
    body = listed(client, admin, page=2, size=2).json()

    assert (len(body["items"]), body["page"], body["totalCount"], body["totalPages"]) == (1, 2, 3, 2)


@pytest.mark.parametrize("params, status, code", [
    ({"createdFrom": "2026-10-02", "createdTo": "2026-10-01"}, 400, "INVALID_REQUEST"),
    ({"workStatus": "DONE"}, 422, "VALIDATION_ERROR"),
    ({"view": "MINE"}, 422, "VALIDATION_ERROR"),
    ({"sort": "summary,asc"}, 422, "VALIDATION_ERROR"),
])
def test_list_validation(client, headers, params, status, code):
    res = listed(client, headers, **params)

    assert res.status_code == status
    assert error_code(res) == code


@pytest.mark.parametrize("who, expected", [("E0001", 200), ("E0002", 200), ("E0003", 404), ("E0009", 200)])
def test_get_ticket_permission(client, admin, staff, who, expected):
    res = client.get(f"{TICKETS}/{staff['mine'].id}", headers=as_user(client, who))

    assert res.status_code == expected
    if expected == 404:
        assert error_code(res) == "TICKET_NOT_FOUND"


def test_get_ticket(client, owner, headers, staff):
    body = client.get(f"{TICKETS}/{staff['mine'].id}", headers=headers).json()

    assert (body["id"], body["receiptNo"], body["requester"]["id"]) == (staff["mine"].id, staff["mine"].receipt_no, owner.id)
    assert (body["workStatus"], body["displayStatus"], body["assignee"]["name"]) == ("WIP", "progress", "박서준")


def test_agent_cannot_view_ticket_of_other_group(client, staff):
    res = client.get(f"{TICKETS}/{staff['secret'].id}", headers=as_user(client, "E0002"))

    assert error_code(res) == "TICKET_NOT_FOUND"


def test_get_missing_ticket(client, headers):
    assert error_code(client.get(f"{TICKETS}/999", headers=headers)) == "TICKET_NOT_FOUND"


def test_status_history(client, db, headers, staff):
    ticket_id = staff["mine"].id
    db.add_all([
        TicketStatusHistory(ticket_id=ticket_id, from_status="RDY", to_status="WIP", source="ITSSUE",
                            actor_id=staff["agent"].id, changed_at=datetime(2026, 10, 21, 1, 40, tzinfo=timezone.utc)),
        TicketStatusHistory(ticket_id=ticket_id, from_status=None, to_status="RDY", source="JIRA",
                            changed_at=datetime(2026, 10, 21, 1, 21, tzinfo=timezone.utc)),
        TicketStatusHistory(ticket_id=staff["others"].id, to_status="RDY", source="JIRA"),
    ])
    db.commit()

    res = client.get(f"{TICKETS}/{ticket_id}/status-history", headers=headers)

    assert res.status_code == 200
    items = res.json()["items"]
    assert [(i["fromStatus"], i["toStatus"], i["source"]) for i in items] == [(None, "RDY", "JIRA"), ("RDY", "WIP", "ITSSUE")]
    assert (items[0]["actor"], items[1]["actor"]["name"]) == (None, "박서준")
    assert items[1]["changedAt"] == "2026-10-21T10:40:00+09:00"


def test_status_history_of_other_user(client, staff):
    res = client.get(f"{TICKETS}/{staff['mine'].id}/status-history", headers=as_user(client, "E0003"))

    assert error_code(res) == "TICKET_NOT_FOUND"
