"""Jira 생성 → 공용 배정 예약 연결. 실제 Jira·운영 DB는 사용하지 않는다."""
from copy import deepcopy
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError

from app.models import AssignmentLog, Inquiry, IntegrationJob, MemberSkill, SupportGroup, SupportGroupMember, Ticket
from app.services import jira_assign, jira_create
from app.services.assignment import reserve_assignment
from test_jira_assign_service import ACCOUNT, FakeAssignment, assign_db  # noqa: F401
from test_jira_create_service import FakeJira, T0, db, make_job, make_ticket, reload  # noqa: F401


def assignments(db, ticket):
    return db.scalars(select(IntegrationJob).where(
        IntegrationJob.ticket_id == ticket.id, IntegrationJob.job_type == "JIRA_ASSIGN",
    )).all()


def logs(db, ticket):
    return db.scalars(select(AssignmentLog).where(AssignmentLog.ticket_id == ticket.id)).all()


@pytest.mark.parametrize("path", ["created", "linked", "verifying", "saved"])
def test_success_paths_reserve_once_without_assigning_jira(assign_db, path):
    db = assign_db
    ticket = make_ticket(db, **({"jira_sync_status": "VERIFYING"} if path == "verifying" else
                                {"jira_key": "ITHD-5", "jira_sync_status": "SYNCED", "work_status": "RDY"}
                                if path == "saved" else {}))
    job = make_job(db, ticket)
    payload = deepcopy(job.payload)
    jira = FakeJira(existing=path in {"linked", "verifying"})

    result = jira_create.run_jira_create_job(db, jira.client(), job.id, now=T0)

    assert result.outcome == {"created": "CREATED", "linked": "LINKED", "verifying": "LINKED", "saved": "SAVED"}[path]
    ticket = reload(db, Ticket, ticket.id)
    assert (ticket.jira_sync_status, ticket.assign_status, ticket.assignee_id, ticket.assignment_revision) == (
        "SYNCED", "PENDING", 18, 1)
    (assignment,) = assignments(db, ticket)
    assert assignment.status == "PENDING"
    assert assignment.payload == {
        "ticketId": ticket.id, "receiptNo": ticket.receipt_no, "jiraKey": ticket.jira_key,
        "groupId": 3, "assigneeId": 18, "jiraAccountId": ACCOUNT, "assignmentRevision": 1,
        "requestedBy": None, "requestedAt": T0.isoformat(),
    }
    assert [(log.event, log.actor_id) for log in logs(db, ticket)] == [("ASSIGN", None)]
    assert reload(db, IntegrationJob, job.id).payload == payload
    assert not any(method == "PUT" for method, _ in jira.calls)
    assert db.get(Inquiry, ticket.inquiry_id).status == "RECEIVED"
    assert jira_create.run_jira_create_job(db, jira.client(), job.id, now=T0).outcome == "SKIPPED"
    assert len(assignments(db, ticket)) == len(logs(db, ticket)) == 1


def test_creation_then_assignment_executor_confirms_handoff(assign_db):
    db = assign_db
    ticket = make_ticket(db)
    job = make_job(db, ticket)
    jira_create.run_jira_create_job(db, FakeJira().client(), job.id, now=T0)
    (assignment,) = assignments(db, ticket)
    jira = FakeAssignment()

    result = jira_assign.run_jira_assign_job(db, jira.client(), assignment.id, now=T0)

    assert result.outcome == "ASSIGNED"
    assert reload(db, Ticket, ticket.id).assign_status == "ASSIGNED"
    assert db.get(Inquiry, ticket.inquiry_id).status == "HANDED_OFF"
    assert jira.puts == 1
    assert len(logs(db, ticket)) == 1


def test_auto_selection_uses_shared_workload_rule(assign_db):
    db = assign_db
    db.add_all([SupportGroupMember(group_id=3, user_id=19, member_role="AGENT", assignable=True,
                                   jira_account_id="account-19"), MemberSkill(user_id=19, inquiry_type_id=21)])
    db.commit()
    make_ticket(db, id=43, receipt_no="RCPT-0043", draft_id=56, assignee_id=18, work_status="WIP",
                assign_status="ASSIGNED")
    ticket = make_ticket(db)
    job = make_job(db, ticket)

    jira_create.run_jira_create_job(db, FakeJira().client(), job.id, now=T0)

    assert reload(db, Ticket, ticket.id).assignee_id == 19


@pytest.mark.parametrize("manual", [True, False])
def test_precreation_reservation_keeps_assignee_revision_and_log(assign_db, manual):
    db = assign_db
    # 직접 지정한 팀장도 자동 선정 기준으로 다시 제외하지 않는다.
    if manual:
        db.get(SupportGroupMember, (3, 18)).member_role = "MANAGER"
        db.commit()
    ticket = make_ticket(db)
    reserve_assignment(db, ticket, 3, reason="생성 전 예약", actor_id=19,
                       assignee_id=18 if manual else None, now=T0)
    db.commit()
    revision, log_id = ticket.assignment_revision, logs(db, ticket)[0].id
    job = make_job(db, ticket)

    jira_create.run_jira_create_job(db, FakeJira().client(), job.id, now=T0)

    ticket = reload(db, Ticket, ticket.id)
    assert (ticket.assignee_id, ticket.assignment_revision) == (18, revision)
    assert [(log.id, log.actor_id) for log in logs(db, ticket)] == [(log_id, 19)]
    assert assignments(db, ticket)[0].payload["assignmentRevision"] == revision


@pytest.mark.parametrize("state", ["PENDING", "RUNNING", "DONE", "NEEDS_ADMIN"])
def test_existing_assignment_job_is_not_replaced_even_if_terminal(assign_db, state):
    db = assign_db
    ticket = make_ticket(db, jira_key="ITHD-5", jira_sync_status="SYNCED", work_status="RDY")
    reservation = reserve_assignment(db, ticket, 3, reason="기존 예약", actor_id=None, now=T0)
    reservation.job.status = state
    db.commit()
    original_payload = deepcopy(reservation.job.payload)
    revision = ticket.assignment_revision
    job = make_job(db, ticket)

    jira_create.run_jira_create_job(db, FakeJira().client(), job.id, now=T0)

    assert len(assignments(db, ticket)) == len(logs(db, ticket)) == 1
    assert ticket.assignment_revision == revision
    assert assignments(db, ticket)[0].payload == original_payload
    assert assignments(db, ticket)[0].status == state


@pytest.mark.parametrize("status", ["ASSIGNED", "NEEDS_ADMIN"])
def test_existing_assignment_decision_is_preserved(assign_db, status):
    db = assign_db
    ticket = make_ticket(db, assignee_id=18, assign_status=status, assignment_revision=3)
    job = make_job(db, ticket)

    jira_create.run_jira_create_job(db, FakeJira().client(), job.id, now=T0)

    ticket = reload(db, Ticket, ticket.id)
    assert (ticket.assignee_id, ticket.assign_status, ticket.assignment_revision) == (18, status, 3)
    assert assignments(db, ticket) == logs(db, ticket) == []


@pytest.mark.parametrize("status_id", ["10006", "10007", "unknown"])
def test_linked_finished_or_unmapped_issue_is_not_auto_assigned(assign_db, status_id):
    db = assign_db
    ticket = make_ticket(db)
    job = make_job(db, ticket)

    jira_create.run_jira_create_job(db, FakeJira(existing=True, status_id=status_id).client(), job.id, now=T0)

    assert assignments(db, ticket) == logs(db, ticket) == []
    assert reload(db, Ticket, ticket.id).assignment_revision == 0


def test_no_candidate_marks_assignment_only_as_needs_admin(assign_db):
    db = assign_db
    db.get(SupportGroupMember, (3, 18)).assignable = False
    db.commit()
    ticket = make_ticket(db)
    job = make_job(db, ticket)

    result = jira_create.run_jira_create_job(db, FakeJira().client(), job.id, now=T0)

    assert result.outcome == "CREATED"
    ticket = reload(db, Ticket, ticket.id)
    assert (ticket.jira_sync_status, ticket.assign_status, ticket.assignee_id) == ("SYNCED", "NEEDS_ADMIN", None)
    assert reload(db, IntegrationJob, job.id).status == "DONE"
    assert [log.event for log in logs(db, ticket)] == ["FAIL"]
    assert assignments(db, ticket) == []


@pytest.mark.parametrize("mode", ["retry", "timeout", "rejected"])
def test_unconfirmed_creation_does_not_reserve(assign_db, mode):
    db = assign_db
    ticket = make_ticket(db)
    job = make_job(db, ticket)
    jira = FakeJira(post_status={"retry": 429, "rejected": 401}.get(mode, 201),
                    post_exc=httpx.ReadTimeout("slow") if mode == "timeout" else None)

    result = jira_create.run_jira_create_job(db, jira.client(), job.id, now=T0)

    assert result.outcome == {"retry": "RETRY_SCHEDULED", "timeout": "VERIFY_SCHEDULED",
                               "rejected": "NEEDS_ADMIN"}[mode]
    ticket = reload(db, Ticket, ticket.id)
    assert (ticket.assignee_id, ticket.assignment_revision) == (None, 0)
    assert assignments(db, ticket) == logs(db, ticket) == []


def test_repeated_create_success_does_not_repeat_assignment_failure(assign_db):
    db = assign_db
    db.get(SupportGroupMember, (3, 18)).assignable = False
    db.commit()
    ticket = make_ticket(db)
    job = make_job(db, ticket)
    jira_create.run_jira_create_job(db, FakeJira().client(), job.id, now=T0)
    job.status = "PENDING"                 # 생성 작업을 운영자가 다시 실행하더라도 배정 판단은 유지
    db.commit()

    jira_create.run_jira_create_job(db, FakeJira().client(), job.id, now=T0)

    assert reload(db, Ticket, ticket.id).assignment_revision == 1
    assert len(logs(db, ticket)) == 1
    assert assignments(db, ticket) == []


def test_inactive_group_is_not_used_for_initial_assignment(assign_db):
    db = assign_db
    db.get(SupportGroup, 3).is_active = False
    db.commit()
    ticket = make_ticket(db)
    job = make_job(db, ticket)

    jira_create.run_jira_create_job(db, FakeJira().client(), job.id, now=T0)

    assert reload(db, Ticket, ticket.id).assign_status == "NEEDS_ADMIN"
    assert assignments(db, ticket) == []
    assert [log.event for log in logs(db, ticket)] == ["FAIL"]


@pytest.mark.parametrize("error", [OperationalError("save", {}, Exception("DB unavailable")),
                                   IntegrityError("save", {}, Exception("reservation conflict"))])
def test_reservation_db_failure_rolls_back_and_recovers_by_lookup(assign_db, monkeypatch, error):
    db = assign_db
    ticket = make_ticket(db)
    job = make_job(db, ticket)
    job_id, ticket_id = job.id, ticket.id
    real_reserve = jira_create.reserve_assignment

    def fail_after_reserving(*args, **kwargs):
        real_reserve(*args, **kwargs)
        raise error

    monkeypatch.setattr(jira_create, "reserve_assignment", fail_after_reserving)
    jira = FakeJira()
    with pytest.raises(type(error)):
        jira_create.run_jira_create_job(db, jira.client(), job_id, now=T0)
    db.rollback()
    ticket = reload(db, Ticket, ticket_id)
    assert (ticket.jira_key, ticket.jira_sync_status, ticket.assignment_revision) == (None, "PENDING", 0)
    assert assignments(db, ticket) == logs(db, ticket) == []
    assert reload(db, IntegrationJob, job_id).status == "RUNNING"

    monkeypatch.setattr(jira_create, "reserve_assignment", real_reserve)
    recovery_time = T0 + timedelta(minutes=6)
    assert jira_create.requeue_stale_running_jobs(db, now=recovery_time) == 1
    jira.existing = True
    result = jira_create.run_jira_create_job(db, jira.client(), job_id, now=recovery_time)

    assert result.outcome == "LINKED"
    assert jira.posts == 1
    assert len(assignments(db, ticket)) == len(logs(db, ticket)) == 1


def test_manual_reservation_saved_during_jira_call_is_preserved(assign_db):
    db = assign_db
    ticket = make_ticket(db)
    job = make_job(db, ticket)
    fake = FakeJira()

    def during_create(req):
        response = fake(req)
        if req.method == "POST" and req.url.path.endswith("/issue"):
            reserve_assignment(db, ticket, 3, reason="생성 중 직접 지정", actor_id=19, assignee_id=18, now=T0)
            db.commit()
        return response

    from app.integrations.jira.client import JiraClient
    jira = JiraClient("https://jira.example", "test@example.com", "dummy", transport=httpx.MockTransport(during_create))
    jira_create.run_jira_create_job(db, jira, job.id, now=T0)

    ticket = reload(db, Ticket, ticket.id)
    assert (ticket.assignee_id, ticket.assignment_revision) == (18, 1)
    assert [(log.event, log.actor_id) for log in logs(db, ticket)] == [("ASSIGN", 19)]
    assert len(assignments(db, ticket)) == 1
