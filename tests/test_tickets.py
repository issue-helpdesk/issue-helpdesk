"""접수 초안·최종 접수 API (TK-01~04) — SQLite 메모리 DB. 문의는 Mock 모델로 판단 흐름을 돌려 만든다."""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import (
    AssignmentLog,
    AuditLog,
    ChatSession,
    Inquiry,
    InquiryAssessment,
    InquiryType,
    IntegrationJob,
    SupportGroup,
    Ticket,
    TicketDraft,
)
from test_auth import add_user, bearer, client, error_code, login  # noqa: F401 (픽스처)
from test_flow_correct import DOC
from test_inquiries import ANSWER, INQUIRY_TABLES, ai, ai_reply, create_sqlite_tables, headers, owner, start, taxonomy  # noqa: F401

DRAFTS = "/api/v1/ticket-drafts"
TICKETS = "/api/v1/tickets"


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    create_sqlite_tables(engine, INQUIRY_TABLES + ["integration_jobs", "assignment_logs"])
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
