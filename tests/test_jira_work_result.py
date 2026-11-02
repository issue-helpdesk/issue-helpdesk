"""최종 처리 결과 수정과 Jira 전환 시각 조회. HTTP는 모두 모의 응답이다."""
from copy import deepcopy
from datetime import timedelta, timezone
import httpx
import pytest

from app.integrations.jira.client import JiraError
from test_jira_transition_service import EVENT_AT, IDS, Workflow
from test_jira_create_service import T0


@pytest.mark.parametrize("status", ["WIP", "FIN"])
def test_result_edit_sends_only_dedicated_adf_field_and_rereads(status):
    jira = Workflow(status, "기존 결과")
    with jira.client() as client:
        result = client.update_final_result("ITHD-42", " 첫 줄\r\n\r\n둘째 줄 ")
    assert result == {"work_status": status, "final_result": "첫 줄\n\n둘째 줄", "changed": True, "matched": True}
    assert (jira.transitions, jira.edits) == (0, 1)
    assert [method for method, _ in jira.calls] == ["GET", "PUT", "GET"]


def test_same_result_does_not_put():
    jira = Workflow("FIN", "같은 결과")
    assert jira.client().update_final_result("ITHD-42", "같은 결과")["changed"] is False
    assert jira.edits == 0


@pytest.mark.parametrize("status", ["RDY", "CLS"])
def test_result_edit_rejects_ineligible_status_without_write(status):
    jira = Workflow(status)
    with pytest.raises(JiraError) as error:
        jira.client().update_final_result("ITHD-42", "결과")
    assert error.value.reason == "invalid_transition"
    assert jira.edits == 0


@pytest.mark.parametrize("note", [None, "", " ", "a" * 4001])
def test_invalid_note_is_rejected_before_http(note):
    jira = Workflow("WIP")
    with pytest.raises(JiraError) as error:
        jira.client().update_final_result("ITHD-42", note)
    assert error.value.reason == "invalid_fields"
    assert jira.calls == []


def test_missing_final_result_mapping_is_not_guessed():
    jira = Workflow("WIP")
    client = jira.client()
    client.mapping = deepcopy(client.mapping)
    client.mapping.pop("transition_fields")
    with pytest.raises(JiraError) as error:
        client.get_work_result("ITHD-42")
    assert error.value.reason == "invalid_fields"
    assert jira.calls == []


@pytest.mark.parametrize("status,reason,retryable", [(400, "invalid_fields", False), (401, "auth", False),
                                                    (429, "rate_limited", True), (503, "result_unknown", False)])
def test_result_edit_classifies_rejections_and_unknown_write(status, reason, retryable):
    jira = Workflow("WIP")
    jira.write_status = status
    with pytest.raises(JiraError) as error:
        jira.client().update_final_result("ITHD-42", "새 결과")
    assert (error.value.reason, error.value.retryable) == (reason, retryable)


def test_result_edit_timeout_requires_read_before_any_retry():
    jira = Workflow("WIP")
    jira.write_error = httpx.ReadTimeout("slow")
    with pytest.raises(JiraError) as error:
        jira.client().update_final_result("ITHD-42", "새 결과")
    assert error.value.reason == "result_unknown"
    jira.write_error = None
    assert jira.client().update_final_result("ITHD-42", "새 결과")["changed"] is False
    assert jira.edits == 1


def test_read_after_edit_failure_is_unknown():
    jira = Workflow("WIP")
    jira.read_errors[2] = httpx.ReadTimeout("slow")
    with pytest.raises(JiraError) as error:
        jira.client().update_final_result("ITHD-42", "새 결과")
    assert error.value.reason == "result_unknown"
    assert jira.edits == 1


def test_edit_does_not_confirm_if_status_changed_during_call():
    jira = Workflow("WIP")
    jira.after_status = "CLS"
    result = jira.client().update_final_result("ITHD-42", "새 결과")
    assert result["matched"] is False
    assert result["work_status"] == "CLS"


def history(identifier, source="WIP", target="FIN", at=EVENT_AT):
    return {"id": identifier, "created": at.isoformat(),
            "items": [{"field": "status", "from": IDS[source], "to": IDS[target]}]}


def test_transition_time_reads_all_pages_and_chooses_latest_matching_change():
    jira = Workflow("FIN", "결과")
    jira.histories = [history("1", at=T0 - timedelta(days=1)), history("2"),
                      history("3", source="FIN", target="CLS"),
                      history("4", at=(EVENT_AT + timedelta(seconds=1)).astimezone(timezone(timedelta(hours=9))))]
    result = jira.client().get_status_changed_at("ITHD-42", "WIP", "FIN", not_before=T0)
    assert result == EVENT_AT + timedelta(seconds=1)
    assert result.utcoffset() == timedelta(0)
    assert len(jira.calls) == 4


def test_transition_time_never_uses_old_history_or_local_clock():
    jira = Workflow("FIN", "결과")
    jira.histories = [history("old", at=T0 - timedelta(days=1))]
    with pytest.raises(JiraError) as error:
        jira.client().get_status_changed_at("ITHD-42", "WIP", "FIN", not_before=T0)
    assert error.value.reason == "result_unknown"


def test_transition_time_rejects_timezone_less_event():
    jira = Workflow("FIN", "결과")
    jira.histories = [{**history("bad"), "created": "2026-10-30T09:00:10"}]
    with pytest.raises(JiraError) as error:
        jira.client().get_status_changed_at("ITHD-42", "WIP", "FIN", not_before=T0)
    assert error.value.reason == "unexpected"


def test_repeated_changelog_page_stops_instead_of_looping():
    jira = Workflow("FIN")
    client = jira.client()
    client._http.close()
    client._http = httpx.Client(base_url="https://jira.example", transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={"values": [history("same")], "isLast": False})))
    with pytest.raises(JiraError) as error:
        client.get_status_changed_at("ITHD-42", "WIP", "FIN", not_before=T0)
    assert error.value.reason == "unexpected"
