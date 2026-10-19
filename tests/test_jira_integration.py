"""Jira(ITSD) 연동 모듈 테스트. 실제 Jira는 부르지 않고 가짜 응답(httpx.MockTransport)으로 확인한다.

    pytest tests/test_jira_integration.py
"""

import json
from pathlib import Path

import httpx
import pytest

from app.integrations.jira import JiraClient, JiraError, MappingError, to_jira_fields
from app.integrations.jira.mapper import compose_description, load_mapping

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://example.atlassian.net"
TICKET = {
    "receipt_no": "RCPT-0001",
    "title": "VPN 연결이 안 됩니다",
    "description": "재택근무 중 VPN 접속이 실패합니다.",
    "category_code": "NET",
    "urgency": "P2",
    "group_name": "네트워크팀",
}


def make_client(handler):
    return JiraClient(BASE, "bot@example.com", "test-token", transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------- mapper


def test_example_ticket_maps_to_itsd_fields():
    f = to_jira_fields(TICKET)
    assert f["project"] == {"key": "ITSD"}
    assert f["issuetype"] == {"id": "10032"}                 # 작업
    assert f["summary"] == "VPN 연결이 안 됩니다"
    assert f["customfield_10113"] == "RCPT-0001"             # ITssue 접수번호
    assert f["customfield_10130"] == TICKET["description"]   # 접수 내용
    assert f["customfield_10117"] == {"id": "10284"}          # IT 문의 분류 NET
    assert f["customfield_10129"] == "P2"                     # 우선순위 등급
    assert f["priority"] == {"id": "2"}                       # High
    assert f["customfield_10084"] == {"id": "10193"}          # 긴급도 High (urgency 에서 계산)
    assert f["customfield_10131"] == "네트워크팀"             # 담당 팀
    assert f["components"] == [{"id": "10062"}]               # 네트워크팀 컴포넌트
    assert f["customfield_10123"] == "챗봇"                   # 접수 채널 CHATBOT 고정
    assert f["customfield_10124"] == "티켓"                   # 처리 유형 TICKET 고정
    assert f["description"]["type"] == "doc"


def test_codes_become_jira_values():
    f = to_jira_fields({**TICKET, "request_kind": "INCIDENT", "impact_scope": "DEPARTMENT",
                        "requester_employee_no": "EMP-1086", "inquiry_type_code": "NET-02"})
    assert f["customfield_10120"] == "장애"            # 티켓 유형: 영문 코드 → 한글 저장값
    assert f["customfield_10118"] == {"id": "10290"}   # 영향 범위 부서
    assert f["customfield_10114"] == "EMP-1086"
    assert f["customfield_10127"] == "NET-02"


def test_migration_only_and_unknown_keys_are_not_sent():
    f = to_jira_fields({**TICKET, "created_at": "2026-10-19T10:00:00+09:00", "work_status": "WIP",
                        "group_id": 3, "aiSummary": "x"})
    assert "customfield_10115" not in f and "status" not in f
    assert all(k in ("project", "issuetype", "summary", "description", "priority", "components")
               or k.startswith("customfield_") for k in f)


def test_description_is_composed_from_draft_parts():
    t = {k: v for k, v in TICKET.items() if k != "description"}
    t.update(summary="VPN 끊김", onset="오늘 아침", tried_actions="재접속\n재부팅")
    text = compose_description(t)
    assert text == "[문의 요약]\nVPN 끊김\n\n[발생 시점]\n오늘 아침\n\n[시도한 조치]\n재접속\n재부팅"
    assert to_jira_fields(t)["customfield_10130"] == text


def test_long_text_is_cut_but_description_keeps_all():
    long = "가" * 300
    f = to_jira_fields({**TICKET, "description": long})
    assert len(f["customfield_10130"]) == 255
    assert f["description"]["content"][0]["content"][0]["text"] == long


def test_missing_required_field_is_rejected():
    with pytest.raises(MappingError, match="group_name"):
        to_jira_fields({**TICKET, "group_name": " "})


@pytest.mark.parametrize("key,value", [("group_name", "없는팀"), ("urgency", "P5"),
                                       ("category_code", "XYZ"), ("request_kind", "장애")])
def test_unknown_code_is_rejected(key, value):
    with pytest.raises(MappingError, match=value):
        to_jira_fields({**TICKET, key: value})


def test_mapping_matches_dataset_taxonomy():
    """매핑의 팀·분류·등급이 데이터셋 분류 체계와 같은지 확인한다."""
    tax = json.loads((ROOT / "dataset" / "data" / "taxonomy.json").read_text(encoding="utf-8"))
    o = load_mapping()["options"]
    assert set(o["group_name"]["values"]) == {t["name"] for t in tax["team_detail"]}
    assert set(o["category_code"]["values"]) == {c["code"] for c in tax["category_detail"]}
    assert set(o["urgency"]["values"]) == set(o["urgency_label"]["values"]) == set(tax["urgency"])


# ---------------------------------------------------------------- client


def test_create_ticket_returns_id_key_url():
    seen = {}

    def handler(req: httpx.Request):
        if req.url.path == "/rest/api/3/search/jql":
            seen["jql"] = json.loads(req.content)["jql"]
            return httpx.Response(200, json={"issues": []})
        if req.method == "POST" and req.url.path == "/rest/api/3/issue":
            seen["fields"] = json.loads(req.content)["fields"]
            return httpx.Response(201, json={"id": "10999", "key": "ITSD-353", "self": "…"})
        return httpx.Response(500)

    with make_client(handler) as c:
        result = c.create_ticket(TICKET)

    assert result == {"jira_issue_id": "10999", "jira_key": "ITSD-353",
                      "jira_url": f"{BASE}/browse/ITSD-353", "created": True}
    assert 'project = "ITSD"' in seen["jql"] and 'cf[10113] ~ "\\"RCPT-0001\\""' in seen["jql"]
    assert seen["fields"]["summary"] == TICKET["title"]


def test_existing_ticket_is_not_created_again():
    calls = []

    def handler(req: httpx.Request):
        calls.append((req.method, req.url.path))
        return httpx.Response(200, json={"issues": [
            {"id": "10500", "key": "ITSD-200", "fields": {"customfield_10113": "RCPT-0001"}}]})

    with make_client(handler) as c:
        result = c.create_ticket(TICKET)
    assert result["jira_key"] == "ITSD-200" and result["created"] is False
    assert ("POST", "/rest/api/3/issue") not in calls


def test_similar_receipt_no_is_not_treated_as_same():
    def handler(req: httpx.Request):
        if req.url.path == "/rest/api/3/search/jql":
            return httpx.Response(200, json={"issues": [
                {"id": "1", "key": "ITSD-9", "fields": {"customfield_10113": "RCPT-00010"}}]})
        return httpx.Response(201, json={"id": "2", "key": "ITSD-10"})

    with make_client(handler) as c:
        assert c.create_ticket(TICKET)["jira_key"] == "ITSD-10"


def test_timeout_is_retryable():
    def handler(req):
        raise httpx.ReadTimeout("slow", request=req)

    with make_client(handler) as c, pytest.raises(JiraError) as e:
        c.create_ticket(TICKET)
    assert e.value.reason == "timeout" and e.value.retryable is True
    assert e.value.to_dict()["status"] == "FAILED"


def test_rejected_field_is_not_retryable():
    def handler(req: httpx.Request):
        if req.url.path == "/rest/api/3/search/jql":
            return httpx.Response(200, json={"issues": []})
        return httpx.Response(400, json={"errorMessages": [], "errors": {"components": "구성 요소가 없습니다"}})

    with make_client(handler) as c, pytest.raises(JiraError) as e:
        c.create_ticket(TICKET)
    assert e.value.reason == "invalid_fields" and e.value.retryable is False
    assert "components" in str(e.value)


def test_bad_mapping_fails_before_any_request():
    def handler(req):
        raise AssertionError("네트워크를 부르면 안 됨")

    with make_client(handler) as c, pytest.raises(JiraError) as e:
        c.create_ticket({**TICKET, "urgency": "P9"})
    assert e.value.reason == "invalid_fields"


def test_check_saved_reports_only_differences():
    sent = to_jira_fields(TICKET)
    saved = {k: v for k, v in sent.items() if k not in ("project", "description")}
    saved["components"] = [{"id": "10062", "name": "네트워크팀"}]
    saved["customfield_10131"] = "다른팀"

    def handler(req: httpx.Request):
        return httpx.Response(200, json={"key": "ITSD-353", "fields": saved})

    with make_client(handler) as c:
        assert c.check_saved("ITSD-353", TICKET) == {"customfield_10131": ("네트워크팀", "다른팀")}


def test_from_env_requires_all_three(monkeypatch):
    from app.core.config import get_jira_settings

    get_jira_settings.cache_clear()
    for n in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"):
        monkeypatch.delenv(n, raising=False)
    monkeypatch.setenv("JIRA_BASE_URL", BASE)
    with pytest.raises(JiraError, match="JIRA_EMAIL"):
        JiraClient.from_env()
    get_jira_settings.cache_clear()
