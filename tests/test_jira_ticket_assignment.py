"""M5-1-3 기본 배정 연결: 실제 Jira를 바꾸지 않는 모의 HTTP 시험."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.integrations.jira.assignment import Member
from app.integrations.jira.client import JiraClient, JiraError
from app.integrations.jira.confirmed_ticket import create_from_confirmed_ticket
from app.integrations.jira.ticket_assignment import (
    AssignmentTarget, ReassignmentContext, StaleAssignmentError,
    TicketAssignmentError, assign_confirmed_ticket,
)


@pytest.fixture
def ticket():
    return {
        "id": 42, "receiptNo": "RCPT-0042", "draftId": 55,
        "summary": "VPN 접속 오류", "categoryCode": "NET", "urgency": "P2",
        "groupId": 3, "group": {"id": 3, "name": "네트워크팀"},
        "assigneeId": 7, "inquiryType": {"id": 21, "code": "NET-01"},
        "jiraKey": "ITHD-999", "jiraSyncStatus": "SYNCED",
        "assignStatus": "PENDING", "workStatus": "RDY",
    }


@pytest.fixture
def target():
    return AssignmentTarget(3, Member(
        user_id=7, employee_no="EMP-TEST", jira_account_id="account-test",
        scenario_ids=frozenset({"NET-01"}),
    ), "AGENT")


def client(handler):
    return JiraClient("https://jira.example", "test@example.com", "dummy",
                      transport=httpx.MockTransport(handler))


def no_network(request):
    pytest.fail(f"Jira를 호출하면 안 됩니다: {request.method} {request.url.path}")


def test_create_then_assign_the_same_key_and_verify(ticket, target):
    saved = deepcopy(ticket)
    saved.update(jiraKey=None, jiraSyncStatus="PENDING")
    assigned = None
    seen = []

    def handler(request):
        nonlocal assigned
        seen.append((request.method, request.url.path))
        if request.url.path.endswith("search/jql"):
            return httpx.Response(200, json={"issues": [], "isLast": True})
        if request.method == "POST":
            body = json.loads(request.content)["fields"]
            assert body["components"] == [{"id": "10002"}]
            assert body["customfield_10043"] == "RCPT-0042"
            return httpx.Response(201, json={"id": "20001", "key": "ITHD-999"})
        assert "ITHD-999" in request.url.path
        if request.method == "PUT":
            assert json.loads(request.content) == {"accountId": "account-test"}
            assigned = "account-test"
            return httpx.Response(204)
        who = {"accountId": assigned} if assigned else None
        return httpx.Response(200, json={"fields": {"assignee": who}})

    with client(handler) as jira:
        creation = create_from_confirmed_ticket(jira, saved)
        # 실제 서버에서는 이 사이에 Jira 키 저장·예약 커밋이 필요하다.
        saved.update(jiraKey=creation["jira_key"], jiraSyncStatus="SYNCED")
        before = deepcopy(saved)
        result = assign_confirmed_ticket(jira, saved, target)
    assert result["assign_status"] == "ASSIGNED"
    assert result["reason"] == "assignment_verified"
    assert result["jira_key"] == creation["jira_key"]
    assert result["actual_account_id"] == "account-test"
    assert result["db_updated"] is False
    assert saved == before
    assert [m for m, _ in seen] == ["POST", "POST", "GET", "PUT", "GET"]


def test_already_assigned_does_not_send_put(ticket, target):
    def handler(request):
        assert request.method == "GET"
        return httpx.Response(200, json={"fields": {"assignee": {"accountId": "account-test"}}})
    ticket["assignStatus"] = "ASSIGNED"
    with client(handler) as jira:
        result = assign_confirmed_ticket(jira, ticket, target)
    assert result["reason"] == "already_assigned"
    assert result["assign_status"] == "ASSIGNED"


def test_existing_other_assignee_is_preserved(ticket, target):
    def handler(request):
        assert request.method == "GET"
        return httpx.Response(200, json={"fields": {"assignee": {"accountId": "manual-account"}}})
    with client(handler) as jira:
        result = assign_confirmed_ticket(jira, ticket, target)
    assert result["assign_status"] == "NEEDS_ADMIN"
    assert result["reason"] == "existing_assignee_conflict"
    assert result["actual_account_id"] == "manual-account"


def test_manual_unassignment_after_confirmed_assignment_is_preserved(ticket, target):
    ticket["assignStatus"] = "ASSIGNED"
    def handler(request):
        assert request.method == "GET"
        return httpx.Response(200, json={"fields": {"assignee": None}})
    with client(handler) as jira:
        result = assign_confirmed_ticket(jira, ticket, target)
    assert result["reason"] == "confirmed_assignment_removed"


@pytest.mark.parametrize("field,value", [
    ("jiraKey", None), ("jiraKey", "OTHER-1"), ("jiraSyncStatus", "PENDING"),
    ("groupId", 99), ("assigneeId", 99), ("assignStatus", "NEEDS_ADMIN"),
    ("workStatus", "CLS"), ("id", True),
])
def test_inconsistent_saved_context_is_rejected(ticket, target, field, value):
    ticket[field] = value
    with client(no_network) as jira, pytest.raises(TicketAssignmentError):
        assign_confirmed_ticket(jira, ticket, target)


@pytest.mark.parametrize("change", [
    {"is_manager": True}, {"user_active": False}, {"member_active": False},
    {"assignable": False}, {"jira_account_id": None},
    {"scenario_ids": frozenset({"SW-01"})},
])
def test_ineligible_target_is_not_sent_to_jira(ticket, target, change):
    target = replace(target, member=replace(target.member, **change))
    with client(no_network) as jira:
        result = assign_confirmed_ticket(jira, ticket, target)
    assert result["assign_status"] == "NEEDS_ADMIN"


def test_missing_scenario_is_not_automatically_assigned(ticket, target):
    ticket["inquiryType"] = None
    with client(no_network) as jira:
        result = assign_confirmed_ticket(jira, ticket, target)
    assert result["assign_status"] == "NEEDS_ADMIN"


def test_absent_target_is_excluded(ticket, target):
    with client(no_network) as jira:
        result = assign_confirmed_ticket(jira, ticket, target, exclude_user_ids={7})
    assert result["assign_status"] == "NEEDS_ADMIN"


def test_employee_role_cannot_be_assigned(ticket, target):
    with client(no_network) as jira:
        result = assign_confirmed_ticket(jira, ticket, replace(target, service_role="EMPLOYEE"))
    assert result["reason"] == "ineligible_service_role"


def test_after_put_mismatch_is_not_success(ticket, target):
    reads = 0
    def handler(request):
        nonlocal reads
        if request.method == "PUT":
            return httpx.Response(204)
        reads += 1
        who = None if reads == 1 else {"accountId": "changed-account"}
        return httpx.Response(200, json={"fields": {"assignee": who}})
    with client(handler) as jira:
        result = assign_confirmed_ticket(jira, ticket, target)
    assert result["assign_status"] == "NEEDS_ADMIN"
    assert result["reason"] == "assignment_mismatch"
    assert result["jira_key"] == "ITHD-999"


@pytest.mark.parametrize("failure", ["timeout", "auth"])
def test_write_failure_is_not_retried_or_reported_success(ticket, target, failure):
    writes = []
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"fields": {"assignee": None}})
        writes.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("lost response", request=request)
        return httpx.Response(401, json={"errorMessages": ["Unauthorized"]})
    before = deepcopy(ticket)
    with client(handler) as jira, pytest.raises(JiraError) as caught:
        assign_confirmed_ticket(jira, ticket, target)
    assert caught.value.reason == failure
    assert len(writes) == 1
    assert ticket == before


def reassignment(previous="previous-account", **overrides):
    values = dict(expected_account_id=previous, revision=2, current_revision=2,
                  reason="담당자 변경", manual=True)
    values.update(overrides)
    return ReassignmentContext(**values)


def assignment_handler(previous, calls):
    """현재 담당자 조회 → 지정 → 재조회 결과를 갖는 모의 Jira."""
    current = previous
    def handler(request):
        nonlocal current
        calls.append(request.method)
        if request.method == "PUT":
            assert json.loads(request.content) == {"accountId": "account-test"}
            current = "account-test"
            return httpx.Response(204)
        assert request.method == "GET"
        who = {"accountId": current} if current is not None else None
        return httpx.Response(200, json={"fields": {"assignee": who}})
    return handler


@pytest.mark.parametrize("previous", ["previous-account", None])
def test_approved_reassignment_changes_expected_previous_account(ticket, target, previous):
    ticket["workStatus"] = "FIN"
    before = deepcopy(ticket)
    calls = []
    with client(assignment_handler(previous, calls)) as jira:
        result = assign_confirmed_ticket(jira, ticket, target, reassignment=reassignment(previous))
    assert calls == ["GET", "PUT", "GET"]
    assert result["assign_status"] == "ASSIGNED"
    assert result["actual_account_id"] == "account-test"
    assert result["db_updated"] is False
    assert ticket == before


def test_fin_is_not_blanket_blocked(ticket, target):
    ticket["workStatus"] = "FIN"
    calls = []
    with client(assignment_handler(None, calls)) as jira:
        result = assign_confirmed_ticket(jira, ticket, target)
    assert result["assign_status"] == "ASSIGNED"
    assert calls == ["GET", "PUT", "GET"]


def test_cls_is_blocked_for_reassignment_too(ticket, target):
    ticket["workStatus"] = "CLS"
    with client(no_network) as jira, pytest.raises(TicketAssignmentError, match="CLS"):
        assign_confirmed_ticket(jira, ticket, target, reassignment=reassignment())


def test_reassignment_does_not_overwrite_unexpected_current_account(ticket, target):
    calls = []
    with client(assignment_handler("manual-change", calls)) as jira:
        result = assign_confirmed_ticket(jira, ticket, target, reassignment=reassignment())
    assert calls == ["GET"]
    assert result["reason"] == "reassignment_source_changed"
    assert result["actual_account_id"] == "manual-change"


@pytest.mark.parametrize("job,current", [(1, 2), (3, 2)])
def test_stale_job_never_calls_jira_or_changes_snapshot(ticket, target, job, current):
    before = deepcopy(ticket)
    with client(no_network) as jira, pytest.raises(StaleAssignmentError):
        assign_confirmed_ticket(jira, ticket, target,
                                reassignment=reassignment(revision=job, current_revision=current))
    assert ticket == before


@pytest.mark.parametrize("overrides", [
    {"reason": " "}, {"reason": "x" * 501}, {"reason": None},
    {"revision": 0}, {"revision": True}, {"current_revision": -1},
    {"current_revision": True}, {"expected_account_id": " "},
    {"expected_account_id": 123},
    {"manual": 1},
])
def test_invalid_reassignment_context_never_calls_jira(ticket, target, overrides):
    with client(no_network) as jira, pytest.raises(TicketAssignmentError):
        assign_confirmed_ticket(jira, ticket, target, reassignment=reassignment(**overrides))


def test_reassignment_is_idempotent_when_jira_already_matches(ticket, target):
    calls = []
    with client(assignment_handler("account-test", calls)) as jira:
        result = assign_confirmed_ticket(jira, ticket, target, reassignment=reassignment())
    assert calls == ["GET"]
    assert result["reason"] == "already_assigned"


@pytest.mark.parametrize("member_update", [
    {"user_active": False}, {"member_active": False}, {"assignable": False},
    {"jira_account_id": None}, {"scenario_ids": frozenset({"SW-01"})},
])
def test_reassignment_keeps_common_tk09_eligibility_checks(ticket, target, member_update):
    target = replace(target, member=replace(target.member, **member_update))
    with client(no_network) as jira:
        result = assign_confirmed_ticket(jira, ticket, target, reassignment=reassignment())
    assert result["assign_status"] == "NEEDS_ADMIN"


def test_explicit_manual_assignment_can_include_group_manager_and_absent_member(ticket, target):
    # TK-09의 AGENT 자격·구성원 조건은 유지한다. 자동 선정용 제외만 적용하지 않는다.
    target = replace(target, member=replace(target.member, is_manager=True))
    calls = []
    with client(assignment_handler("previous-account", calls)) as jira:
        result = assign_confirmed_ticket(jira, ticket, target,
                                        exclude_user_ids={7}, reassignment=reassignment())
    assert result["assign_status"] == "ASSIGNED"
    assert calls == ["GET", "PUT", "GET"]


def test_saved_reservation_is_still_required_for_reassignment(ticket, target):
    ticket["assigneeId"] = None
    with client(no_network) as jira, pytest.raises(TicketAssignmentError):
        assign_confirmed_ticket(jira, ticket, target, reassignment=reassignment())


def test_completed_job_is_not_reapplied_to_a_changed_jira_assignment(ticket, target):
    ticket["assignStatus"] = "ASSIGNED"
    calls = []
    with client(assignment_handler("previous-account", calls)) as jira:
        result = assign_confirmed_ticket(jira, ticket, target, reassignment=reassignment())
    assert calls == ["GET"]
    assert result["reason"] == "confirmed_assignment_changed"


@pytest.mark.parametrize("excluded,manager", [({7}, False), (set(), True)])
def test_automatic_reassignment_keeps_leave_and_manager_exclusions(ticket, target, excluded, manager):
    target = replace(target, member=replace(target.member, is_manager=manager))
    with client(no_network) as jira:
        result = assign_confirmed_ticket(jira, ticket, target,
                                        exclude_user_ids=excluded,
                                        reassignment=reassignment(manual=False))
    assert result["assign_status"] == "NEEDS_ADMIN"


def test_approved_automatic_reassignment_can_change_expected_previous_account(ticket, target):
    calls = []
    with client(assignment_handler("previous-account", calls)) as jira:
        result = assign_confirmed_ticket(jira, ticket, target,
                                        reassignment=reassignment(manual=False))
    assert result["assign_status"] == "ASSIGNED"
    assert calls == ["GET", "PUT", "GET"]
