"""상태 동기화 판단과 별도 수신 서버 검증. 실제 Jira/DB는 호출하지 않는다."""
from dataclasses import replace
import hashlib
import hmac
import json
from pathlib import Path
import sys

# 기존 conftest를 수정하지 않고 pytest 실행 방식 모두에서 별도 시험 도구를 찾는다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import pytest
from fastapi.testclient import TestClient

from app.integrations.jira import parse_jira_webhook
from app.integrations.jira.status_sync import needs_status_refresh, plan_status_sync
from tools.jira_status_lab.receiver import DEMO_SECRET, create_app, settings_from_env


def payload(field="status", event="jira:issue_updated", key="ITHD-DEMO"):
    return {"webhookEvent": event, "issue": {"key": key}, "changelog": {"id": "5001", "items": [
        {"field": field, "from": "10004", "to": "10005", "fromString": "RDY", "toString": "WIP"}]}}


def post(client, value, *, secret=DEMO_SECRET, delivery="delivery-1"):
    body = json.dumps(value).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post("/api/v1/webhooks/jira", content=body, headers={
        "X-Hub-Signature": "sha256=" + signature, "X-Atlassian-Webhook-Identifier": delivery})


@pytest.mark.parametrize("status", ["RDY", "WIP", "FIN", "CLS"])
def test_resolves_all_supported_latest_statuses(status):
    event = parse_jira_webhook(payload())
    plan = plan_status_sync(event, {"work_status": status, "status_id": "id", "status_name": status})
    assert plan.work_status == status and plan.reason == "status_resolved"


def test_delayed_event_uses_latest_query_not_webhook_to_value():
    event = parse_jira_webhook(payload())  # 이 연락은 WIP으로 바뀐 과거 시점의 것
    plan = plan_status_sync(event, {"work_status": "FIN", "status_id": "10006", "status_name": "FIN"})
    assert event.new_work_status == "WIP"
    assert plan.work_status == "FIN"


def test_current_status_matches_latest_is_unchanged():
    plan = plan_status_sync(parse_jira_webhook(payload()), {"work_status": "WIP"}, current_work_status="WIP")
    assert plan.reason == "unchanged" and plan.work_status == "WIP"


def test_unmapped_status_is_not_a_db_update_candidate():
    plan = plan_status_sync(parse_jira_webhook(payload()), {"work_status": None, "status_id": "99999", "status_name": "unknown"})
    assert plan.work_status is None and plan.reason == "unmapped_status"


def test_status_change_requires_a_fresh_jira_read():
    with pytest.raises(ValueError):
        plan_status_sync(parse_jira_webhook(payload()), None)


@pytest.mark.parametrize("field", ["summary", "assignee", "description"])
def test_nonstatus_changes_do_not_need_jira_query(field):
    event = parse_jira_webhook(payload(field))
    assert not needs_status_refresh(event)
    assert plan_status_sync(event, None).reason == "not_status_change"


@pytest.mark.parametrize("event_name", ["comment_created", "comment_updated", "jira:issue_created"])
def test_other_events_are_not_processed_as_status_changes(event_name):
    event = parse_jira_webhook(payload(event=event_name))
    assert not needs_status_refresh(event)
    assert plan_status_sync(event, None).reason == "ignored_event"


def test_invalid_itssue_current_status_is_rejected():
    with pytest.raises(ValueError):
        plan_status_sync(parse_jira_webhook(payload()), {"work_status": "WIP"}, current_work_status="IP")


def test_realistic_field_id_without_field_is_read():
    p = payload()
    p["changelog"]["items"][0]["fieldId"] = p["changelog"]["items"][0].pop("field")
    assert needs_status_refresh(parse_jira_webhook(p))


def test_http_status_refresh_only_calls_read_api():
    seen = []
    def jira(request):
        seen.append((request.method, request.url.path, request.url.params.get("fields")))
        return httpx.Response(200, json={"fields": {"status": {"id": "10005", "name": "WIP"}}})
    with TestClient(create_app(settings_from_env("mock"), httpx.MockTransport(jira))) as client:
        r = post(client, payload())
    assert r.status_code == 200
    assert r.json()["work_status"] == "WIP" and r.json()["status_changed"] is True
    assert r.json()["event_id"] == "delivery:delivery-1"
    assert r.json()["db_updated"] is False
    assert seen == [("GET", "/rest/api/3/issue/ITHD-DEMO", "status")]


@pytest.mark.parametrize("field,event,key,reason", [
    ("summary", "jira:issue_updated", "ITHD-DEMO", "not_status_change"),
    ("assignee", "jira:issue_updated", "ITHD-DEMO", "not_status_change"),
    ("status", "comment_created", "ITHD-DEMO", "ignored_event"),
    ("status", "jira:issue_updated", "ITHD-OTHER", "ignored_issue"),
])
def test_unrelated_requests_do_not_read_jira(field, event, key, reason):
    def forbidden(request):
        raise AssertionError("이번 요청으로 Jira를 조회하면 안 됩니다.")
    with TestClient(create_app(settings_from_env("mock"), httpx.MockTransport(forbidden))) as client:
        r = post(client, payload(field, event, key))
    assert r.status_code == 200 and r.json()["reason"] == reason


def test_invalid_signature_rejected_before_jira_query():
    def forbidden(request):
        raise AssertionError("검증 실패 후 Jira를 읽으면 안 됩니다.")
    with TestClient(create_app(settings_from_env("mock"), httpx.MockTransport(forbidden))) as client:
        r = post(client, payload(), secret="wrong-secret")
    assert r.status_code == 403


@pytest.mark.parametrize("value", [[], {}, {"issue": {}}, {"issue": {"key": ""}}])
def test_invalid_body_returns_400(value):
    with TestClient(create_app(settings_from_env("mock"))) as client:
        assert post(client, value).status_code == 400


@pytest.mark.parametrize("status,reason,retryable", [(401, "auth", False), (404, "not_found", False),
                                                     (429, "rate_limited", True), (503, "server_error", True)])
def test_jira_errors_are_reported_without_error_body(status, reason, retryable):
    def error(request):
        return httpx.Response(status, json={"errorMessages": ["private-detail"]})
    with TestClient(create_app(settings_from_env("mock"), httpx.MockTransport(error))) as client:
        r = post(client, payload())
    assert r.status_code == 502 and r.json()["detail"] == {"reason": reason, "retryable": retryable}
    assert "private-detail" not in r.text


def test_timeout_is_reported_without_automatic_retry():
    seen = []
    def timeout(request):
        seen.append(request)
        raise httpx.ReadTimeout("timeout")
    with TestClient(create_app(settings_from_env("mock"), httpx.MockTransport(timeout))) as client:
        r = post(client, payload())
    assert r.status_code == 502 and r.json()["detail"] == {"reason": "timeout", "retryable": True}
    assert len(seen) == 1


def test_http_unknown_status_does_not_fall_back_to_webhook_status():
    def unknown(request):
        return httpx.Response(200, json={"fields": {"status": {"id": "99999", "name": "unknown"}}})
    with TestClient(create_app(settings_from_env("mock"), httpx.MockTransport(unknown))) as client:
        r = post(client, payload())
    assert r.json()["work_status"] is None and r.json()["reason"] == "unmapped_status"


def test_http_reports_unchanged_with_simulated_current_status():
    settings = replace(settings_from_env("mock"), current_status="WIP")
    with TestClient(create_app(settings)) as client:
        r = post(client, payload())
    assert r.json()["reason"] == "unchanged" and r.json()["db_updated"] is False
