"""Jira 담당자 지정·상태 전환·웹훅 해석·담당자 선정·재시도 판단 테스트. 실제 Jira는 부르지 않는다.

    pytest tests/test_jira_assignment.py
"""

import json
from datetime import datetime, timezone

import httpx
import pytest

from app.integrations.jira import (
    JiraClient, JiraError, Member, RetryPolicy, WebhookError, next_step, parse_jira_webhook,
    pick_assignee, verify_webhook_secret, work_status_from_jira,
)

BASE = "https://example.atlassian.net"


def make_client(handler):
    return JiraClient(BASE, "bot@example.com", "t", transport=httpx.MockTransport(handler))


def j(data, status=200):
    return httpx.Response(status, json=data)


# ---------------------------------------------------------------- 담당자 지정


def test_assign_issue_sends_account_id_and_confirms_by_rereading():
    calls = []

    def handler(req):
        calls.append((req.method, req.url.path))
        if req.method == "PUT":
            assert json.loads(req.content) == {"accountId": "acc-1"}
            return httpx.Response(204)
        return j({"fields": {"assignee": {"accountId": "acc-1", "displayName": "김담당"}}})

    with make_client(handler) as c:
        out = c.assign_issue("ITHD-1", "acc-1")
    assert out == {"matched": True, "account_id": "acc-1", "actual_account_id": "acc-1"}
    assert [m for m, _ in calls] == ["PUT", "GET"]


def test_assign_issue_reports_mismatch_instead_of_confirming():
    def handler(req):
        if req.method == "PUT":
            return httpx.Response(204)
        return j({"fields": {"assignee": {"accountId": "someone-else"}}})

    with make_client(handler) as c:
        out = c.assign_issue("ITHD-1", "acc-1")
    assert out["matched"] is False and out["actual_account_id"] == "someone-else"


def test_assign_issue_timeout_is_retryable_and_empty_account_is_rejected():
    def timeout(req):
        raise httpx.ReadTimeout("slow")

    with make_client(timeout) as c:
        with pytest.raises(JiraError) as e:
            c.assign_issue("ITHD-1", "acc-1")
        assert e.value.reason == "timeout" and e.value.retryable
        with pytest.raises(JiraError) as e2:
            c.assign_issue("ITHD-1", "  ")
        assert e2.value.reason == "invalid_fields" and not e2.value.retryable


def test_assign_issue_400_is_not_retryable():
    with make_client(lambda req: j({"errorMessages": ["user not assignable"]}, 400)) as c:
        with pytest.raises(JiraError) as e:
            c.assign_issue("ITHD-1", "acc-1")
    assert e.value.reason == "invalid_fields" and not e.value.retryable


def test_get_assignee_none_when_unassigned():
    with make_client(lambda req: j({"fields": {"assignee": None}})) as c:
        assert c.get_assignee("ITHD-1")["account_id"] is None


# ---------------------------------------------------------------- 상태 전환


def _workflow(current_id, transitions):
    sent = []

    def handler(req):
        if req.method == "GET" and req.url.path.endswith("/transitions"):
            return j({"transitions": transitions})
        if req.method == "POST":
            sent.append(json.loads(req.content))
            return httpx.Response(204)
        return j({"fields": {"status": {"id": current_id, "name": "x"}}})

    return handler, sent


def test_transition_finds_transition_by_target_status_id():
    handler, sent = _workflow("10004", [{"id": "21", "to": {"id": "10005"}}, {"id": "31", "to": {"id": "10006"}}])
    with make_client(handler) as c:
        assert c.transition_issue("ITHD-1", "FIN", final_result="재접속 안내") == {"changed": True, "work_status": "FIN"}
    adf = {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": "재접속 안내"}]}]}
    assert sent == [{"transition": {"id": "31"}, "fields": {"customfield_10069": adf}}]


def test_transition_to_fin_requires_final_result():
    handler, sent = _workflow("10005", [{"id": "31", "to": {"id": "10006"}}])
    with make_client(handler) as c:
        for empty in (None, "", "  "):
            with pytest.raises(JiraError) as e:
                c.transition_issue("ITHD-1", "FIN", final_result=empty)
            assert e.value.reason == "invalid_fields" and not e.value.retryable
    assert sent == []


def test_transition_is_noop_when_already_there():
    handler, sent = _workflow("10005", [])
    with make_client(handler) as c:
        assert c.transition_issue("ITHD-1", "WIP") == {"changed": False, "work_status": "WIP"}
    assert sent == []


def test_transition_not_allowed_and_unknown_target():
    handler, _ = _workflow("10004", [{"id": "21", "to": {"id": "10005"}}])
    with make_client(handler) as c:
        with pytest.raises(JiraError) as e:
            c.transition_issue("ITHD-1", "CLS")
        assert e.value.reason == "invalid_transition" and not e.value.retryable
        with pytest.raises(JiraError) as e2:
            c.transition_issue("ITHD-1", "DONE")
        assert e2.value.reason == "invalid_fields"


def test_work_status_mapping():
    assert work_status_from_jira("10004") == "RDY" and work_status_from_jira(10007) == "CLS"
    assert work_status_from_jira("99999") is None
    with make_client(lambda r: j({"fields": {"status": {"id": "10006", "name": "FIN"}}})) as c:
        assert c.get_work_status("ITHD-1")["work_status"] == "FIN"


# ---------------------------------------------------------------- 웹훅


PAYLOAD = {
    "webhookEvent": "jira:issue_updated",
    "timestamp": 1761350000000,
    "issue": {"key": "ITHD-9"},
    "changelog": {"id": "555", "items": [
        {"field": "status", "from": "10004", "to": "10005", "fromString": "RDY", "toString": "WIP"},
        {"field": "assignee", "from": None, "to": "acc-7", "toString": "박서준"},
    ]},
}


def test_parse_webhook_reads_status_and_assignee():
    e = parse_jira_webhook(PAYLOAD)
    assert e.issue_key == "ITHD-9" and e.status_changed and e.assignee_changed
    assert e.new_work_status == "WIP" and e.new_assignee_account_id == "acc-7"
    assert e.event_id == "changelog:555" and e.timestamp_ms == 1761350000000


def test_event_id_priority_and_hash_fallback():
    assert parse_jira_webhook(PAYLOAD, delivery_id="d-1").event_id == "delivery:d-1"
    bare = {"issue": {"key": "ITHD-9"}}
    a, b = parse_jira_webhook(bare).event_id, parse_jira_webhook(dict(bare)).event_id
    assert a == b and a.startswith("sha256:")


def test_parse_webhook_unassign_and_other_fields():
    e = parse_jira_webhook({"issue": {"key": "ITHD-1"}, "changelog": {"items": [
        {"field": "assignee", "from": "acc-7", "to": None}, {"field": "summary", "to": "x"}]}})
    assert e.assignee_changed and e.new_assignee_account_id is None and not e.status_changed


@pytest.mark.parametrize("bad", [None, [], {}, {"issue": {}}, {"issue": {"key": " "}}])
def test_parse_webhook_rejects_missing_issue_key(bad):
    with pytest.raises(WebhookError):
        parse_jira_webhook(bad)


def test_webhook_secret_check():
    assert verify_webhook_secret("s3", "s3")
    assert not verify_webhook_secret("s3", "other")
    assert not verify_webhook_secret(None, "s3") and not verify_webhook_secret("s3", "") and not verify_webhook_secret("", "")


# ---------------------------------------------------------------- 담당자 선정


def m(uid, **kw):
    base = dict(employee_no=f"E{uid:04d}", jira_account_id=f"acc-{uid}", scenario_ids=frozenset({"NET-01"}))
    base.update(kw)
    return Member(uid, **base)


def dt(day):
    return datetime(2026, 10, day, tzinfo=timezone.utc)


def test_picks_lowest_workload_including_reserved():
    d = pick_assignee([m(1, rdy=1, wip=1), m(2, wip=1), m(3, rdy=1, reserved=1, wip=1)], "NET-01")
    assert d.selected and d.user_id == 2 and d.workload == 1
    assert d.reason == "업무량 최소 (1건)"


def test_tie_goes_to_oldest_last_assignment_then_employee_no():
    d = pick_assignee([m(1, last_assigned_at=dt(20)), m(2, last_assigned_at=dt(10)), m(3, last_assigned_at=dt(15))], "NET-01")
    assert d.user_id == 2 and "마지막 배정" in d.reason
    d2 = pick_assignee([m(5), m(4)], "NET-01")                    # 둘 다 배정 이력 없음 → 사번 순
    assert d2.user_id == 4 and "사번 순" in d2.reason
    d3 = pick_assignee([m(1, last_assigned_at=dt(1)), m(2)], "NET-01")   # 이력 없는 사람이 먼저
    assert d3.user_id == 2


def test_excludes_manager_inactive_unassignable_no_skill_no_jira_and_listed():
    members = [
        m(1, is_manager=True), m(2, user_active=False), m(3, member_active=False), m(4, assignable=False),
        m(5, scenario_ids=frozenset({"SW-01"})), m(6, jira_account_id=None), m(7), m(8),
    ]
    d = pick_assignee(members, "NET-01", exclude_user_ids=[8])
    assert d.user_id == 7
    assert d.excluded == {1: "팀장 제외", 2: "사용자 비활성", 3: "그룹 구성원 아님(비활성)", 4: "자동배정 대상 아님",
                          5: "해당 세부 분류 처리 불가", 6: "Jira 계정 없음", 8: "배정 제외 대상"}


def test_jira_account_requirement_can_be_relaxed():
    assert not pick_assignee([m(6, jira_account_id=None)], "NET-01").selected
    assert pick_assignee([m(6, jira_account_id=None)], "NET-01", require_jira_account=False).user_id == 6


def test_no_candidate_and_unclassified():
    d = pick_assignee([m(1, is_manager=True)], "NET-01")
    assert not d.selected and d.user_id is None and d.reason == "배정 가능한 후보 없음"
    u = pick_assignee([m(1)], None)
    assert not u.selected and "미분류" in u.reason
    assert not pick_assignee([], "NET-01").selected


# ---------------------------------------------------------------- 재시도 판단


def err(reason, retryable):
    return JiraError(reason, "x", retryable=retryable)


def test_retry_backoff_then_needs_admin():
    p = RetryPolicy()
    assert next_step(err("timeout", True), 1, policy=p) == next_step(err("timeout", True), 1, policy=p)
    assert (s := next_step(err("server_error", True), 1)).action == "RETRY" and s.delay_seconds == 60
    assert next_step(err("server_error", True), 2).delay_seconds == 300
    assert next_step(err("rate_limited", True), 3).action == "NEEDS_ADMIN"


def test_non_retryable_goes_to_admin_immediately():
    for r in ("auth", "invalid_fields", "invalid_transition", "not_found"):
        assert next_step(err(r, False), 1).action == "NEEDS_ADMIN"


def test_result_unknown_verifies_never_retries_then_escalates():
    s = next_step(err("result_unknown", False), 1)
    assert s.action == "VERIFY" and s.delay_seconds == 60
    assert next_step(err("result_unknown", False), 4).action == "NEEDS_ADMIN"
    assert next_step(err("result_unknown", False), 1, elapsed_seconds=900).action == "NEEDS_ADMIN"


# ---------------------------------------------------------------- 되돌림 금지 · 사번-계정 연결표


@pytest.mark.parametrize("current, target", [("10006", "RDY"), ("10007", "WIP"), ("10007", "RDY"), ("10007", "FIN")])
def test_closed_tickets_and_fin_to_rdy_cannot_go_back(current, target):
    # 워크플로가 허용하더라도(전환 목록에 있어도) ITssue는 되돌리지 않는다
    handler, sent = _workflow(current, [{"id": "1", "to": {"id": "10005"}}, {"id": "2", "to": {"id": "10004"}}, {"id": "3", "to": {"id": "10006"}}])
    with make_client(handler) as c:
        with pytest.raises(JiraError) as e:
            c.transition_issue("ITHD-1", target)
    assert e.value.reason == "invalid_transition" and not e.value.retryable and sent == []


def test_fin_can_go_back_to_wip_only_for_reprocessing():
    # 미해결 재처리(SRS JIRA-06): FIN → WIP 만 허용한다. 최종 처리 결과는 보내지 않는다.
    handler, sent = _workflow("10006", [{"id": "5", "to": {"id": "10005"}}, {"id": "4", "to": {"id": "10007"}}])
    with make_client(handler) as c:
        assert c.transition_issue("ITHD-1", "WIP") == {"changed": True, "work_status": "WIP"}
    assert sent == [{"transition": {"id": "5"}}]


def test_fin_to_wip_still_needs_the_workflow_transition():
    handler, sent = _workflow("10006", [{"id": "4", "to": {"id": "10007"}}])  # Jira 워크플로에 FIN → WIP 가 없는 경우
    with make_client(handler) as c:
        with pytest.raises(JiraError) as e:
            c.transition_issue("ITHD-1", "WIP")
    assert e.value.reason == "invalid_transition" and not e.value.retryable and sent == []


def test_forward_transitions_still_allowed_from_fin():
    handler, sent = _workflow("10006", [{"id": "9", "to": {"id": "10007"}}])
    with make_client(handler) as c:
        assert c.transition_issue("ITHD-1", "CLS")["changed"] is True
    assert sent == [{"transition": {"id": "9"}}]


def test_account_map_lookup_skips_blank_and_rejects_shared_account(tmp_path):
    from app.integrations.jira import account_id_for, load_account_map
    from app.integrations.jira.accounts import ACCOUNTS_PATH

    # 기본 파일은 값이 비어 있어도 읽힌다(비어 있으면 연결 없음)
    assert account_id_for("EMP-1370", {}) is None
    assert account_id_for(" EMP-1370 ", {"EMP-1370": "acc-1"}) == "acc-1"
    load_account_map.cache_clear()
    assert isinstance(load_account_map(ACCOUNTS_PATH), dict)

    f = tmp_path / "a.yaml"
    f.write_text("accounts:\n  EMP-1: acc-1\n  EMP-2: ''\n  EMP-3: acc-3\n", encoding="utf-8")
    assert load_account_map(f) == {"EMP-1": "acc-1", "EMP-3": "acc-3"}
    g = tmp_path / "b.yaml"
    g.write_text("accounts:\n  EMP-1: same\n  EMP-2: same\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_account_map(g)


def test_default_account_file_covers_six_groups():
    from app.integrations.jira.accounts import ACCOUNTS_PATH
    import yaml
    raw = yaml.safe_load(ACCOUNTS_PATH.read_text(encoding="utf-8"))["accounts"]
    assert len(raw) == 6 and all(k.startswith("EMP-") for k in raw)


# ---------------------------------------------------------------- 웹훅 서명 (X-Hub-Signature)


def test_hub_signature_matches_atlassian_example_and_rejects_tampering():
    from app.integrations.jira import verify_hub_signature

    secret, body = "It's a Secret to Everybody", b"Hello World!"
    good = "sha256=a4771c39fbe90f317c7824e83ddef3caae9cb3d976c214ace1f2937e133263c9"   # Atlassian 문서의 시험 값(끝 ...263c9)
    assert verify_hub_signature(body, good, secret)
    assert verify_hub_signature(body, good.upper().replace("SHA256", "sha256"), secret)   # 서명 글자 대소문자 무관
    assert not verify_hub_signature(b"Hello World?", good, secret)                       # 본문이 바뀜
    assert not verify_hub_signature(body, good, "other")                                 # 비밀값 다름
    for bad in (None, "", "sha256", "sha256=", "md5=abc", "a4771c39"):
        assert not verify_hub_signature(body, bad, secret)
    assert not verify_hub_signature(body, good, None) and not verify_hub_signature(body, good, "")
    assert not verify_hub_signature("Hello World!", good, secret)                        # 바이트가 아니면 거부


# ---------------------------------------------------------------- 연차·반차 부재 목록 (time_off)


def test_absent_user_ids_annual_and_half_days():
    from datetime import date, datetime, time

    from app.integrations.jira import Member, TimeOff, absent_user_ids, pick_assignee

    d = date(2026, 11, 4)
    entries = [
        TimeOff(1, "ANNUAL", date(2026, 11, 3), date(2026, 11, 5)),   # 연차: 기간 안이면 종일
        TimeOff(2, "HALF_AM", d, d),                                  # 오전 반차: 13시 전까지
        TimeOff(3, "HALF_PM", d, d),                                  # 오후 반차: 13시부터
        TimeOff(4, "ANNUAL", date(2026, 11, 5), date(2026, 11, 6)),   # 기간 밖
    ]
    morning, noon, afternoon = (datetime(2026, 11, 4, h, m) for h, m in ((9, 0), (13, 0), (15, 30)))
    assert absent_user_ids(entries, morning) == {1, 2}
    assert absent_user_ids(entries, noon) == {1, 3}              # 정각 13:00 부터 오후 반차 부재, 오전 반차 복귀
    assert absent_user_ids(entries, afternoon) == {1, 3}
    assert absent_user_ids(entries, datetime(2026, 11, 7, 10, 0)) == frozenset()
    assert absent_user_ids(entries, afternoon, half_day_cutoff=time(14, 0)) == {1, 3}
    assert absent_user_ids(entries, datetime(2026, 11, 4, 13, 30), half_day_cutoff=time(14, 0)) == {1, 2}
    with __import__("pytest").raises(ValueError):
        absent_user_ids([TimeOff(5, "SICK", d, d)], morning)

    members = [Member(user_id=i, employee_no=f"EMP-{i}", jira_account_id=f"acc{i}", scenario_ids=frozenset({"NET-01"})) for i in (1, 2, 3)]
    assert pick_assignee(members, "NET-01", exclude_user_ids=absent_user_ids(entries, morning)).user_id == 3
    assert pick_assignee(members, "NET-01", exclude_user_ids=absent_user_ids(entries, afternoon)).user_id == 2
