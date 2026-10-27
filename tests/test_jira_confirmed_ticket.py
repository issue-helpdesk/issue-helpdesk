"""확정 접수 계약 → 기존 Jira HTTP 클라이언트 연결 시험. 실제 Jira 호출 없음."""

from copy import deepcopy
import json
from pathlib import Path
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.integrations.jira.client import JiraClient, JiraError
from app.integrations.jira.confirmed_ticket import (
    ConfirmedTicketError, create_from_confirmed_ticket, to_jira_ticket,
)


@pytest.fixture
def ticket():
    return {
        "id": 42, "draftId": 55, "receiptNo": "RCPT-0042",
        "summary": "VPN 접속 오류", "categoryCode": "NET", "urgency": "P2",
        "groupId": 3, "group": {"id": 3, "name": "네트워크팀"},
        "targetSystem": "VPN", "symptom": "인증 서버 연결 실패",
        "occurredAt": "오늘 오전", "businessImpact": "사내 시스템 접속 불가",
        "triedActions": "재설치", "urgencyReason": "개인 업무 전면 중단",
        "requester": {"id": 17, "employeeNo": "EMP-TEST", "name": "시험 사용자"},
        "jiraSyncStatus": "PENDING", "jiraKey": None,
    }


def client_for(handler):
    return JiraClient("https://jira.example", "test@example.com", "dummy", transport=httpx.MockTransport(handler))


def no_network(request):
    pytest.fail(f"호출하면 안 되는 Jira 요청: {request.method} {request.url.path}")


def test_create_uses_current_jira_fields_and_preserves_snapshot(ticket):
    before = deepcopy(ticket)
    seen = []

    def handler(request):
        seen.append(request.url.path)
        body = json.loads(request.content)
        if request.url.path.endswith("search/jql"):
            assert "RCPT-0042" in body["jql"]
            return httpx.Response(200, json={"issues": [], "isLast": True})
        assert request.url.path == "/rest/api/3/issue"
        fields = body["fields"]
        assert fields["project"] == {"key": "ITHD"}
        assert fields["issuetype"] == {"id": "10010"}
        assert fields["summary"] == ticket["summary"]
        assert fields["customfield_10043"] == ticket["receiptNo"]
        assert fields["customfield_10064"] == {"id": "10022"}
        assert fields["priority"] == {"id": "2"}
        assert fields["components"] == [{"id": "10002"}]
        assert fields["customfield_10044"] == "EMP-TEST"
        text = json.dumps(fields["description"], ensure_ascii=False)
        for key in ("summary", "symptom", "occurredAt", "businessImpact", "triedActions"):
            assert ticket[key] in text
        assert "assignee" not in fields  # 개인 배정은 별도 작업
        return httpx.Response(201, json={"id": "20001", "key": "ITHD-999"})

    with client_for(handler) as jira:
        result = create_from_confirmed_ticket(jira, ticket)
    assert seen == ["/rest/api/3/search/jql", "/rest/api/3/issue"]
    assert result == {
        "ticket_id": 42, "receipt_no": "RCPT-0042", "jira_issue_id": "20001",
        "jira_key": "ITHD-999", "jira_url": "https://jira.example/browse/ITHD-999",
        "created": True, "source": "jira",
    }
    assert ticket == before


def test_existing_jira_search_reuses_issue_without_post(ticket):
    def handler(request):
        assert request.url.path.endswith("search/jql")
        return httpx.Response(200, json={"issues": [{"id": "20001", "key": "ITHD-999",
            "fields": {"customfield_10043": "RCPT-0042"}}], "isLast": True})
    with client_for(handler) as jira:
        result = create_from_confirmed_ticket(jira, ticket)
    assert result["created"] is False
    assert result["jira_key"] == "ITHD-999"


def test_saved_jira_key_returns_without_network_or_requiring_fields_again(ticket):
    ticket.update(jiraKey="ITHD-999", jiraSyncStatus="SYNCED", categoryCode=None)
    ticket["jiraUrl"] = "https://untrusted.example"
    with client_for(no_network) as jira:
        result = create_from_confirmed_ticket(jira, ticket)
    assert result["source"] == "saved_ticket"
    assert result["created"] is False
    assert result["jira_url"] == "https://jira.example/browse/ITHD-999"


@pytest.mark.parametrize("field", ["id", "draftId", "receiptNo", "summary", "categoryCode", "urgency", "groupId", "group"])
def test_missing_required_value_never_calls_jira(ticket, field):
    ticket[field] = None
    with client_for(no_network) as jira, pytest.raises(ConfirmedTicketError):
        create_from_confirmed_ticket(jira, ticket)


@pytest.mark.parametrize("field,value", [("categoryCode", "UNKNOWN"), ("urgency", "P0")])
def test_invalid_option_is_rejected_before_network(ticket, field, value):
    ticket[field] = value
    with client_for(no_network) as jira, pytest.raises(JiraError) as caught:
        create_from_confirmed_ticket(jira, ticket)
    assert caught.value.reason == "invalid_fields"


def test_group_name_must_be_known_and_id_must_match(ticket):
    ticket["group"]["id"] = 999
    with client_for(no_network) as jira, pytest.raises(ConfirmedTicketError, match="group_mismatch"):
        create_from_confirmed_ticket(jira, ticket)
    ticket["group"]["id"] = ticket["groupId"]
    ticket["group"]["name"] = "알 수 없는 팀"
    with client_for(no_network) as jira, pytest.raises(JiraError) as caught:
        create_from_confirmed_ticket(jira, ticket)
    assert caught.value.reason == "invalid_fields"


@pytest.mark.parametrize("state", ["VERIFYING", "NEEDS_ADMIN", "SYNCED", "EDITING", None])
def test_non_pending_without_jira_key_cannot_create(ticket, state):
    ticket["jiraSyncStatus"] = state
    with client_for(no_network) as jira, pytest.raises(ConfirmedTicketError):
        create_from_confirmed_ticket(jira, ticket)


def test_unconfirmed_draft_request_is_not_a_ticket():
    with client_for(no_network) as jira, pytest.raises(ConfirmedTicketError):
        create_from_confirmed_ticket(jira, {"draftId": 55, "draftUpdatedAt": None})


@pytest.mark.parametrize("key", ["OTHER-123", "ITHD-1/../../x", "https://jira.example/ITHD-1"])
def test_invalid_saved_key_does_not_create(ticket, key):
    ticket["jiraKey"] = key
    with client_for(no_network) as jira, pytest.raises(ConfirmedTicketError):
        create_from_confirmed_ticket(jira, ticket)


@pytest.mark.parametrize("field,value", [("id", True), ("summary", {"bad": "value"}), ("occurredAt", 123)])
def test_wrong_types_are_not_silently_stringified(ticket, field, value):
    ticket[field] = value
    with client_for(no_network) as jira, pytest.raises(ConfirmedTicketError):
        create_from_confirmed_ticket(jira, ticket)


def test_long_summary_is_preserved_in_full_description(ticket):
    ticket["summary"] = "확정된 긴 문의 내용 " * 80
    payload = to_jira_ticket(ticket)
    from app.integrations.jira.mapper import to_jira_fields, adf_to_text
    fields = to_jira_fields(payload)
    assert len(fields["summary"]) == 255
    assert ticket["summary"].strip() in adf_to_text(fields["description"])


def test_only_allowlisted_confirmed_fields_are_forwarded(ticket):
    ticket.update(apiToken="do-not-send", messages=["private chat"], aiSummary="not in Ticket contract")
    payload = to_jira_ticket(ticket)
    assert "do-not-send" not in json.dumps(payload)
    assert "private chat" not in json.dumps(payload)
    assert "aiSummary" not in payload


def test_timeout_after_post_stays_result_unknown_without_retry(ticket):
    posts = []
    def handler(request):
        if request.url.path.endswith("search/jql"):
            return httpx.Response(200, json={"issues": [], "isLast": True})
        posts.append(request)
        raise httpx.ReadTimeout("lost response", request=request)
    with client_for(handler) as jira, pytest.raises(JiraError) as caught:
        create_from_confirmed_ticket(jira, ticket)
    assert caught.value.reason == "result_unknown"
    assert caught.value.retryable is False
    assert len(posts) == 1


def test_auth_failure_is_not_retried_or_marked_success(ticket):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(401, json={"errorMessages": ["Unauthorized"]})
    with client_for(handler) as jira, pytest.raises(JiraError) as caught:
        create_from_confirmed_ticket(jira, ticket)
    assert caught.value.reason == "auth"
    assert len(requests) == 1
