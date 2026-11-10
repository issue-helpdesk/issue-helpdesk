"""접수 분류 변경(TK-15)·분류 이상 신고(TK-16~18)·Jira 필드 갱신 작업(JIRA_UPDATE_FIELDS). SQLite 메모리 DB·모의 Jira 만 사용한다."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from app.integrations.jira import JiraError
from app.integrations.jira.client import JiraClient
from app.integrations.jira.mapper import MappingError, load_mapping, to_jira_update_fields
from app.models import (AssignmentLog, AuditLog, Category, Inquiry, InquiryType, IntegrationJob, SupportGroupMember,
                        Ticket, TicketClassificationReport)
from app.services.jira_fields import requeue_stale_field_jobs, run_jira_update_fields_job
from test_auth import add_user, client, error_code  # noqa: F401
from test_inquiries import headers, owner  # noqa: F401
from test_tickets import TICKETS, admin, as_user, db, jobs, listed, set_work_status, staff, team  # noqa: F401

NOW = datetime(2026, 11, 10, 1, 0, tzinfo=timezone.utc)


@pytest.fixture
def sec(db, team):
    """보안팀 기본 세부 유형 SEC-01(배정 가능자 E0008), 네트워크팀 기본 세부 유형 NET-05."""
    db.add(Category(code="SEC", name="보안"))
    sec_type = InquiryType(code="SEC-01", category_code="SEC", name="계정 도용 의심", request_kind="INCIDENT",
                           default_urgency="P2", default_group_id=team["sec"].id)
    net_type = InquiryType(code="NET-05", category_code="NET", name="무선 접속 장애", request_kind="INCIDENT",
                           default_urgency="P3", default_group_id=team["net"].id)
    db.add_all([sec_type, net_type])
    db.flush()
    guard = add_user(db, "E0008", name="정보안", service_role="AGENT")
    db.add(SupportGroupMember(group_id=team["sec"].id, user_id=guard.id, member_role="AGENT", assignable=True,
                              jira_account_id="acc-E0008"))
    db.commit()
    return team | {"sec_type": sec_type, "net_type": net_type, "guard": guard}


def reclassify(client, headers, ticket_id, inquiry_type_id, reason="보안 계정 탈취 의심 건"):
    return client.put(f"{TICKETS}/{ticket_id}/classification", headers=headers,
                      json={"inquiryTypeId": inquiry_type_id, "reason": reason})


def report(client, headers, ticket_id, reason="보안 건으로 보입니다", suggested=None):
    return client.post(f"{TICKETS}/{ticket_id}/classification-reports", headers=headers,
                       json={"reason": reason, "suggestedInquiryTypeId": suggested})


def reject(client, headers, ticket_id, report_id, note="네트워크 장애가 맞습니다"):
    return client.patch(f"{TICKETS}/{ticket_id}/classification-reports/{report_id}", headers=headers,
                        json={"status": "REJECTED", "resolutionNote": note})


# ---------------------------------------------------------------- TK-15 분류 변경

def test_admin_moves_ticket_to_other_category(client, db, admin, sec):
    ticket = sec["mine"]

    res = reclassify(client, admin, ticket.id, sec["sec_type"].id)

    assert res.status_code == 200
    body = res.json()
    assert (body["categoryCode"], body["inquiryTypeId"], body["groupId"]) == ("SEC", sec["sec_type"].id, sec["sec"].id)
    assert (body["assigneeId"], body["assignStatus"], body["urgency"]) == (sec["guard"].id, "PENDING", None)
    inquiry = db.get(Inquiry, ticket.inquiry_id)
    assert (inquiry.category_code, inquiry.inquiry_type_id) == ("SEC", sec["sec_type"].id)
    log = db.scalar(select(AssignmentLog))
    assert (log.event, log.group_id, log.assignee_id) == ("REASSIGN", sec["sec"].id, sec["guard"].id)
    assert log.reason.startswith("분류 변경 NET-02→SEC-01: 보안 계정 탈취 의심 건")
    assign_job, fields_job = jobs(db)
    assert (assign_job.job_type, fields_job.job_type) == ("JIRA_ASSIGN", "JIRA_UPDATE_FIELDS")
    assert fields_job.idempotency_key.startswith("fields:")
    assert {k: fields_job.payload[k] for k in ("jiraKey", "inquiryTypeId", "fields")} == {
        "jiraKey": "ITHD-1520", "inquiryTypeId": sec["sec_type"].id,
        "fields": {"category_code": "SEC", "category_name": "보안", "inquiry_type_name": "계정 도용 의심",
                   "inquiry_type_code": "SEC-01", "request_kind": "INCIDENT"},
    }
    audit = db.scalar(select(AuditLog).where(AuditLog.event_type == "RECLASSIFY"))
    assert (audit.result, audit.reason, audit.target_id) == ("NET-02→SEC-01", "보안 계정 탈취 의심 건", ticket.id)


def test_same_group_keeps_assignee(client, db, admin, sec):
    res = reclassify(client, admin, sec["mine"].id, sec["net_type"].id, reason="무선 장애로 정정")

    assert res.status_code == 200
    assert (res.json()["groupId"], res.json()["assigneeId"]) == (sec["net"].id, sec["agent"].id)
    assert db.scalar(select(AssignmentLog)) is None
    assert [job.job_type for job in jobs(db)] == ["JIRA_UPDATE_FIELDS"]


def test_no_assignable_member_leaves_ticket_for_admin(client, db, admin, sec):
    db.get(SupportGroupMember, (sec["sec"].id, sec["guard"].id)).assignable = False
    db.commit()

    body = reclassify(client, admin, sec["mine"].id, sec["sec_type"].id).json()

    assert (body["groupId"], body["assigneeId"], body["assignStatus"], body["needsAdmin"]) == (
        sec["sec"].id, None, "NEEDS_ADMIN", True)
    assert [job.job_type for job in jobs(db)] == ["JIRA_UPDATE_FIELDS"]


@pytest.mark.parametrize("who", ["E0002", "E0004", "E0001"])       # 담당자 · 팀장 · 문의자
def test_only_admin_changes_classification(client, db, sec, who):
    res = reclassify(client, as_user(client, who), sec["mine"].id, sec["sec_type"].id)

    assert res.status_code == 403
    assert db.get(Ticket, sec["mine"].id).category_code is None
    assert jobs(db) == []


def test_closed_ticket_cannot_be_reclassified(client, db, admin, sec):
    set_work_status(db, sec["mine"], "CLS")

    assert error_code(reclassify(client, admin, sec["mine"].id, sec["sec_type"].id)) == "TICKET_INVALID_TRANSITION"


def test_reclassify_before_jira_creation(client, admin, sec):
    assert error_code(reclassify(client, admin, sec["others"].id, sec["sec_type"].id)) == "TICKET_NOT_SYNCED"


@pytest.mark.parametrize("job_type", ["JIRA_ASSIGN", "JIRA_UPDATE_FIELDS"])
def test_reclassify_while_job_active(client, db, admin, sec, job_type):
    db.add(IntegrationJob(ticket_id=sec["mine"].id, job_type=job_type, status="PENDING", attempts=0,
                          idempotency_key="active", payload={}))
    db.commit()

    assert error_code(reclassify(client, admin, sec["mine"].id, sec["sec_type"].id)) == "INTEGRATION_JOB_IN_PROGRESS"


@pytest.mark.parametrize("change, field, reason", [
    ({"reason": "  "}, "reason", "REQUIRED"),
    ({"type": "vpn"}, "inquiryTypeId", "UNCHANGED"),
    ({"type": 9999}, "inquiryTypeId", "NOT_FOUND"),
    ({"inactive": True}, "inquiryTypeId", "NOT_FOUND"),
    ({"group_off": True}, "inquiryTypeId", "GROUP_INACTIVE"),
])
def test_reclassify_validation(client, db, admin, sec, change, field, reason):
    sec["sec_type"].is_active = not change.get("inactive", False)
    sec["sec"].is_active = not change.get("group_off", False)
    db.commit()
    target = change.get("type", "sec_type")
    type_id = sec[target].id if isinstance(target, str) else target

    res = reclassify(client, admin, sec["mine"].id, type_id, reason=change.get("reason", "사유"))

    assert res.status_code == 422
    assert (res.json()["error"]["details"][0]["field"], res.json()["error"]["details"][0]["reason"]) == (field, reason)


def test_reclassify_closes_old_field_failure(client, db, admin, sec):
    failed = IntegrationJob(ticket_id=sec["mine"].id, job_type="JIRA_UPDATE_FIELDS", status="NEEDS_ADMIN", attempts=3,
                            idempotency_key="fields:old", payload={}, last_error="invalid_fields")
    db.add(failed)
    db.commit()

    reclassify(client, admin, sec["mine"].id, sec["sec_type"].id)

    db.refresh(failed)
    assert (failed.status, failed.last_error) == ("DONE", "superseded:reclassify (invalid_fields)")


def test_reclassify_resolves_open_report(client, db, admin, sec):
    report_id = report(client, as_user(client, "E0002"), sec["mine"].id).json()["id"]

    res = reclassify(client, admin, sec["mine"].id, sec["sec_type"].id)

    assert res.json()["openClassificationReport"] is None
    saved = db.get(TicketClassificationReport, report_id)
    db.refresh(saved)
    assert saved.status == "RESOLVED" and saved.resolved_by is not None
    assert saved.resolution_note == "분류 변경 NET-02→SEC-01: 보안 계정 탈취 의심 건"


# ---------------------------------------------------------------- TK-16~18 분류 이상 신고

def test_member_reports_wrong_classification(client, db, headers, admin, sec):
    agent = as_user(client, "E0002")

    res = report(client, agent, sec["mine"].id, suggested=sec["sec_type"].id)

    assert res.status_code == 201
    body = res.json()
    assert (body["status"], body["reason"], body["reporter"]["employeeNo"]) == ("OPEN", "보안 건으로 보입니다", "E0002")
    assert body["suggestedInquiryType"] == {"id": sec["sec_type"].id, "code": "SEC-01", "name": "계정 도용 의심"}
    assert client.get(f"{TICKETS}/{sec['mine'].id}", headers=agent).json()["openClassificationReport"]["id"] == body["id"]
    assert client.get(f"{TICKETS}/{sec['mine'].id}", headers=headers).json()["openClassificationReport"] is None  # 문의자
    reported = listed(client, admin, classificationReportOpen="true").json()["items"]
    assert [(i["id"], i["classificationReportOpen"]) for i in reported] == [(sec["mine"].id, True)]
    others = listed(client, admin, classificationReportOpen="false").json()["items"]
    assert sec["mine"].id not in [i["id"] for i in others]
    assert db.scalar(select(AuditLog.result).where(AuditLog.event_type == "CLASSIFICATION_REPORT")) == "OPEN"


def test_one_open_report_per_ticket(client, sec):
    agent = as_user(client, "E0002")
    report(client, agent, sec["mine"].id)

    res = report(client, agent, sec["mine"].id)

    assert res.status_code == 409
    assert error_code(res) == "CLASSIFICATION_REPORT_ALREADY_OPEN"


@pytest.mark.parametrize("who, status", [("E0001", 403), ("E0003", 404), ("E0008", 404)])   # 문의자 · 무관 · 다른 그룹
def test_report_permission(client, sec, who, status):
    assert report(client, as_user(client, who), sec["mine"].id).status_code == status


@pytest.mark.parametrize("body, field", [({"reason": " "}, "reason"),
                                         ({"reason": "x", "suggested": 9999}, "suggestedInquiryTypeId")])
def test_report_validation(client, sec, body, field):
    res = report(client, as_user(client, "E0002"), sec["mine"].id, reason=body["reason"], suggested=body.get("suggested"))

    assert res.status_code == 422
    assert res.json()["error"]["details"][0]["field"] == field


def test_report_on_closed_ticket(client, db, sec):
    set_work_status(db, sec["mine"], "CLS")

    assert error_code(report(client, as_user(client, "E0002"), sec["mine"].id)) == "TICKET_INVALID_TRANSITION"


def test_admin_rejects_report(client, db, admin, sec):
    agent = as_user(client, "E0002")
    report_id = report(client, agent, sec["mine"].id).json()["id"]

    res = reject(client, admin, sec["mine"].id, report_id)

    assert res.status_code == 200
    assert (res.json()["status"], res.json()["resolutionNote"]) == ("REJECTED", "네트워크 장애가 맞습니다")
    assert res.json()["resolvedBy"]["employeeNo"] == "E0009"
    assert db.get(Ticket, sec["mine"].id).inquiry_type_id == sec["vpn"].id         # 분류는 그대로
    assert error_code(reject(client, admin, sec["mine"].id, report_id)) == "CLASSIFICATION_REPORT_NOT_OPEN"
    assert report(client, agent, sec["mine"].id).status_code == 201                # 반려 뒤 다시 신고할 수 있다
    history = client.get(f"{TICKETS}/{sec['mine'].id}/classification-reports", headers=agent).json()["items"]
    assert [r["status"] for r in history] == ["REJECTED", "OPEN"]


def test_reject_requires_admin_and_note(client, admin, sec):
    report_id = report(client, as_user(client, "E0002"), sec["mine"].id).json()["id"]

    assert reject(client, as_user(client, "E0004"), sec["mine"].id, report_id).status_code == 403
    res = reject(client, admin, sec["mine"].id, report_id, note=" ")
    assert res.status_code == 422 and res.json()["error"]["details"][0]["field"] == "resolutionNote"
    assert error_code(reject(client, admin, sec["secret"].id, report_id)) == "NOT_FOUND"     # 다른 접수의 신고


def test_report_history_is_staff_only(client, headers, sec):
    assert error_code(client.get(f"{TICKETS}/{sec['mine'].id}/classification-reports",
                                 headers=headers)) == "TICKET_NOT_FOUND"


# ---------------------------------------------------------------- JIRA_UPDATE_FIELDS 실행

class FakeFields:
    def __init__(self, *, error=None, diffs=None):
        self.error, self.diffs, self.sent = error, diffs or {}, []

    def update_fields(self, key, values):
        self.sent.append((key, values))
        if self.error:
            raise self.error
        return self.diffs


@pytest.fixture
def fields_job(client, db, admin, sec):
    reclassify(client, admin, sec["mine"].id, sec["sec_type"].id)
    return next(job for job in jobs(db) if job.job_type == "JIRA_UPDATE_FIELDS")


def test_field_job_updates_jira(db, fields_job):
    jira = FakeFields()

    result = run_jira_update_fields_job(db, jira, fields_job.id, now=NOW)

    assert result.outcome == "UPDATED"
    assert jira.sent == [("ITHD-1520", fields_job.payload["fields"])]
    db.refresh(fields_job)
    assert (fields_job.status, fields_job.attempts, fields_job.last_error) == ("DONE", 1, None)


def test_field_job_skips_when_reclassified_again(db, sec, fields_job):
    db.get(Ticket, sec["mine"].id).inquiry_type_id = sec["net_type"].id
    db.commit()
    jira = FakeFields()

    result = run_jira_update_fields_job(db, jira, fields_job.id, now=NOW)

    assert result.outcome == "STALE" and jira.sent == []
    db.refresh(fields_job)
    assert (fields_job.status, fields_job.last_error) == ("DONE", "stale_classification")


@pytest.mark.parametrize("jira, outcome, status", [
    (FakeFields(error=JiraError("timeout", "시간 초과", retryable=True)), "RETRY_SCHEDULED", "PENDING"),
    (FakeFields(error=JiraError("invalid_fields", "거절", retryable=False)), "NEEDS_ADMIN", "NEEDS_ADMIN"),
    (FakeFields(diffs={"customfield_10064": ({"id": "10026"}, {"id": "10022"})}), "NEEDS_ADMIN", "NEEDS_ADMIN"),
])
def test_field_job_failures(db, fields_job, jira, outcome, status):
    result = run_jira_update_fields_job(db, jira, fields_job.id, now=NOW)

    assert result.outcome == outcome
    db.refresh(fields_job)
    assert fields_job.status == status
    if status == "PENDING":
        assert fields_job.next_retry_at is not None


def test_stuck_field_job_is_requeued(db, fields_job):
    fields_job.status, fields_job.updated_at = "RUNNING", NOW - timedelta(minutes=10)
    db.commit()

    assert requeue_stale_field_jobs(db, now=NOW) == 1
    db.refresh(fields_job)
    assert (fields_job.status, fields_job.last_error) == ("PENDING", "stale_running")


def test_retry_of_failed_field_job(client, db, admin, sec, fields_job):
    fields_job.status = "NEEDS_ADMIN"
    db.commit()

    res = client.post(f"{TICKETS}/{sec['mine'].id}/integration-jobs", headers=admin,
                      json={"retryOfJobId": fields_job.id, "reason": "Jira 화면 설정 수정"})

    assert res.status_code == 201
    assert (res.json()["jobType"], res.json()["retryOfJobId"]) == ("JIRA_UPDATE_FIELDS", fields_job.id)


def test_retry_of_stale_field_job_is_refused(client, db, admin, sec, fields_job):
    fields_job.status = "NEEDS_ADMIN"
    db.get(Ticket, sec["mine"].id).inquiry_type_id = sec["net_type"].id
    db.commit()

    res = client.post(f"{TICKETS}/{sec['mine'].id}/integration-jobs", headers=admin,
                      json={"retryOfJobId": fields_job.id, "reason": "재처리"})

    assert error_code(res) == "INTEGRATION_RETRY_NOT_ALLOWED"
    assert res.json()["error"]["details"][0]["reason"] == "CLASSIFICATION"


# ---------------------------------------------------------------- Jira 칸 변환·클라이언트

def test_update_fields_mapping():
    fields = to_jira_update_fields({"category_code": "SEC", "category_name": "보안", "inquiry_type_code": "SEC-01",
                                    "request_kind": "INCIDENT", "inquiry_type_name": None}, load_mapping())

    assert fields == {"customfield_10064": {"id": "10026"}, "customfield_10053": "보안",
                      "customfield_10055": "SEC-01", "customfield_10049": "장애", "customfield_10054": None}


def test_update_fields_rejects_unknown_key():
    with pytest.raises(MappingError):
        to_jira_update_fields({"nope": "x"}, load_mapping())


def test_client_update_fields_puts_then_compares():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "PUT":
            assert json.loads(request.content) == {"fields": {"customfield_10064": {"id": "10026"}}}
            return httpx.Response(204)
        return httpx.Response(200, json={"fields": {"customfield_10064": {"id": "10022"}}})   # 반영 안 됨

    with JiraClient("https://jira.example", "bot@example.com", "dummy", transport=httpx.MockTransport(handler)) as jira:
        diffs = jira.update_fields("ITHD-1", {"category_code": "SEC"})

    assert calls == [("PUT", "/rest/api/3/issue/ITHD-1"), ("GET", "/rest/api/3/issue/ITHD-1")]
    assert diffs == {"customfield_10064": ({"id": "10026"}, {"id": "10022"})}
