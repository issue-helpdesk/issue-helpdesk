"""Jira 댓글 알림(Jira 쪽) 테스트: 댓글 웹훅 해석 · 댓글 조회 · 받는 사람 판별. 실제 Jira는 부르지 않는다.

    pytest tests/test_jira_comment.py
"""

import httpx
import pytest

from app.integrations.jira import (
    JiraClient, JiraError, employee_no_for, parse_jira_webhook, route_comment,
)
from app.integrations.jira.mapper import adf_to_text

BASE = "https://example.atlassian.net"

# 사번 ↔ Jira accountId (시험용 연결표)
ACCOUNTS = {"EMP-1001": "acc-requester", "EMP-1370": "acc-agent", "EMP-1408": "acc-lead"}


def make_client(handler):
    return JiraClient(BASE, "bot@example.com", "t", transport=httpx.MockTransport(handler))


def comment_payload(**over):
    p = {
        "webhookEvent": "comment_created",
        "timestamp": 1790000000000,
        "issue": {"key": "ITHD-12"},
        "comment": {
            "id": "10055",
            "author": {"accountId": "acc-agent", "displayName": "조민재", "accountType": "atlassian"},
            "created": "2026-10-26T10:00:00.000+0900",
            "updated": "2026-10-26T10:00:00.000+0900",
        },
    }
    p.update(over)
    return p


# ---------------------------------------------------------------- 웹훅 해석


def test_comment_created_is_read():
    e = parse_jira_webhook(comment_payload())
    assert e.is_comment_created
    assert e.issue_key == "ITHD-12"
    assert e.comment.comment_id == "10055"
    assert e.comment.author_account_id == "acc-agent"
    assert e.comment.author_name == "조민재"
    assert e.comment.author_type == "atlassian"
    assert not e.status_changed and not e.assignee_changed


def test_comment_event_id_is_stable_and_prefers_delivery_id():
    a, b = parse_jira_webhook(comment_payload()).event_id, parse_jira_webhook(comment_payload()).event_id
    assert a == b and a.startswith("comment:comment_created:10055:")
    assert parse_jira_webhook(comment_payload(), delivery_id="d-9").event_id == "delivery:d-9"


def test_updated_comment_is_not_a_new_comment_and_has_other_event_id():
    created = parse_jira_webhook(comment_payload())
    updated = parse_jira_webhook(comment_payload(webhookEvent="comment_updated"))
    assert not updated.is_comment_created
    assert updated.event_id != created.event_id


def test_comment_without_id_is_not_a_comment_event():
    e = parse_jira_webhook(comment_payload(comment={"author": {"accountId": "x"}}))
    assert e.comment is None and not e.is_comment_created


def test_missing_author_is_kept_as_none():
    e = parse_jira_webhook(comment_payload(comment={"id": 77}))
    assert e.comment.comment_id == "77"          # 숫자 ID도 문자열로
    assert e.comment.author_account_id is None


def test_status_event_is_unchanged_by_comment_support():
    e = parse_jira_webhook({"webhookEvent": "jira:issue_updated", "issue": {"key": "ITHD-1"},
                            "changelog": {"id": "55", "items": [{"field": "status", "from": "1", "to": "2"}]}})
    assert e.comment is None and not e.is_comment_created
    assert e.status_changed and e.event_id == "changelog:55"


# ---------------------------------------------------------------- ADF → 글자


def test_adf_to_text_joins_paragraphs_mentions_and_breaks():
    adf = {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [
            {"type": "mention", "attrs": {"id": "acc-requester", "text": "@김서연"}},
            {"type": "text", "text": " 님, 확인 부탁드립니다."}]},
        {"type": "paragraph", "content": [
            {"type": "text", "text": "첫 줄"}, {"type": "hardBreak"}, {"type": "text", "text": "둘째 줄"}]},
        {"type": "bulletList", "content": [
            {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "항목1"}]}]},
            {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "항목2"}]}]}]},
    ]}
    assert adf_to_text(adf) == "@김서연 님, 확인 부탁드립니다.\n첫 줄\n둘째 줄\n항목1\n항목2"


@pytest.mark.parametrize("value,expected", [("그냥 글", "그냥 글"), (None, ""), ({}, ""), (123, ""), ({"type": "doc"}, "")])
def test_adf_to_text_tolerates_odd_input(value, expected):
    assert adf_to_text(value) == expected


# ---------------------------------------------------------------- 댓글 조회


def test_get_comment_reads_author_and_text():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        return httpx.Response(200, json={
            "id": "10055",
            "author": {"accountId": "acc-agent", "displayName": "조민재", "accountType": "atlassian"},
            "body": {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": "VPN 재설치 후 다시 시도해 주세요."}]}]},
            "created": "2026-10-26T10:00:00.000+0900", "updated": "2026-10-26T10:00:00.000+0900"})

    with make_client(handler) as jira:
        c = jira.get_comment("ITHD-12", 10055)
    assert seen["path"] == "/rest/api/3/issue/ITHD-12/comment/10055"
    assert c == {"comment_id": "10055", "author_account_id": "acc-agent", "author_name": "조민재", "author_type": "atlassian",
                 "text": "VPN 재설치 후 다시 시도해 주세요.", "created": "2026-10-26T10:00:00.000+0900",
                 "updated": "2026-10-26T10:00:00.000+0900"}


def test_deleted_comment_is_not_found_and_not_retryable():
    with make_client(lambda r: httpx.Response(404, json={"errorMessages": ["없음"]})) as jira:
        with pytest.raises(JiraError) as e:
            jira.get_comment("ITHD-12", "1")
    assert e.value.reason == "not_found" and not e.value.retryable


def test_comment_read_timeout_is_retryable():
    def handler(request):
        raise httpx.ReadTimeout("느림")

    with make_client(handler) as jira:
        with pytest.raises(JiraError) as e:
            jira.get_comment("ITHD-12", "1")
    assert e.value.reason == "timeout" and e.value.retryable


@pytest.mark.parametrize("bad", ["", "  ", None])
def test_empty_comment_id_fails_before_any_request(bad):
    def handler(request):
        raise AssertionError("Jira를 부르면 안 됩니다")

    with make_client(handler) as jira:
        with pytest.raises(JiraError) as e:
            jira.get_comment("ITHD-12", bad)
    assert e.value.reason == "invalid_fields"


# ---------------------------------------------------------------- 계정 역방향 조회


def test_employee_no_for_is_reverse_of_account_map():
    assert employee_no_for("acc-agent", ACCOUNTS) == "EMP-1370"
    assert employee_no_for(" acc-agent ", ACCOUNTS) == "EMP-1370"
    assert employee_no_for("acc-nobody", ACCOUNTS) is None
    assert employee_no_for("", ACCOUNTS) is None
    assert employee_no_for(None, ACCOUNTS) is None


# ---------------------------------------------------------------- 받는 사람 판별


def route(author, requester="EMP-1001", assignee="EMP-1370", **kw):
    return route_comment(author, requester_no=requester, assignee_no=assignee, accounts=ACCOUNTS, **kw)


def test_requester_comment_goes_to_assignee():
    r = route("acc-requester")
    assert (r.recipient_nos, r.reason) == (("EMP-1370",), "to_assignee")


def test_assignee_comment_goes_to_requester():
    r = route("acc-agent")
    assert (r.recipient_nos, r.reason) == (("EMP-1001",), "to_requester")


def test_third_person_comment_goes_to_both_without_duplicates():
    r = route("acc-lead")
    assert (r.recipient_nos, r.reason) == (("EMP-1001", "EMP-1370"), "to_both")


def test_comment_is_never_sent_to_its_author():
    for who in ("acc-requester", "acc-agent", "acc-lead"):
        author_no = employee_no_for(who, ACCOUNTS)
        assert author_no not in route(who).recipient_nos


def test_requester_comment_before_assignment_has_no_counterpart():
    r = route("acc-requester", assignee=None)
    assert (r.recipient_nos, r.reason) == ((), "no_counterpart")


def test_assignee_comment_without_requester_has_no_counterpart():
    r = route("acc-agent", requester=None)
    assert (r.recipient_nos, r.reason) == ((), "no_counterpart")


def test_third_person_with_only_one_party_notifies_that_party():
    r = route("acc-lead", assignee=None)
    assert (r.recipient_nos, r.reason) == (("EMP-1001",), "to_both")


def test_same_person_as_requester_and_assignee_is_self_comment():
    r = route("acc-requester", requester="EMP-1001", assignee="EMP-1001")
    assert (r.recipient_nos, r.reason) == ((), "self_comment")


def test_our_own_bot_comments_are_ignored():
    r = route("acc-bot", ignore_account_ids={"acc-bot"})
    assert (r.recipient_nos, r.reason) == ((), "ignored_author")


@pytest.mark.parametrize("author", [None, "", "  "])
def test_missing_author_is_ignored(author):
    assert route(author).reason == "ignored_author"


def test_unmapped_jira_account_is_reported_not_guessed():
    r = route("acc-stranger")
    assert (r.recipient_nos, r.reason) == ((), "unknown_author")


def test_blank_numbers_count_as_missing():
    r = route("acc-requester", assignee="  ")
    assert r.reason == "no_counterpart"
