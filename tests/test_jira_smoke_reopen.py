"""smoke_check.py --reopen (FIN → WIP → FIN 재처리 점검)이 결과를 제대로 가려내는지 가짜 Jira로 확인한다. 실제 Jira는 부르지 않는다.

    pytest tests/test_jira_smoke_reopen.py
"""

import json

import httpx

from app.integrations.jira import JiraClient
from app.integrations.jira.smoke_check import FINAL_RESULT_FIELD, reopen_probe

IDS = {"RDY": "10004", "WIP": "10005", "FIN": "10006", "CLS": "10007"}
NAMES = {v: k for k, v in IDS.items()}
NEXT = {"RDY": ["WIP"], "WIP": ["FIN"], "CLS": []}


def adf(text):
    return {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def text_of(node):
    return "".join(c["content"][0]["text"] for c in node["content"]) if node else ""


class FakeJira:
    """상태·최종 처리 결과 필드·변경 이력만 흉내 낸다. fin_to_wip=False 면 워크플로에 FIN→WIP 전이가 없다."""

    def __init__(self, *, fin_to_wip=True, mode="overwrite", clears_resolution=True):
        self.status, self.value, self.history, self.mode = "RDY", None, [], mode
        self.resolution, self.clears_resolution = None, clears_resolution
        self.reopen_posts = 0
        self.next = {**NEXT, "FIN": (["WIP"] if fin_to_wip else []) + ["CLS"]}

    def handler(self, req):
        path = req.url.path
        if req.method == "GET" and path.endswith("/transitions"):
            return httpx.Response(200, json={"transitions": [
                {"id": f"t-{t}", "to": {"id": IDS[t], "name": t}} for t in self.next[self.status]]})
        if req.method == "GET" and path.endswith("/changelog"):
            return httpx.Response(200, json={"values": [{"items": [
                {"fieldId": FINAL_RESULT_FIELD, "fromString": old, "toString": new}]} for old, new in self.history]})
        if req.method == "POST" and path.endswith("/transitions"):
            body = json.loads(req.content)
            target = body["transition"]["id"].removeprefix("t-")
            if self.status == "FIN" and target == "WIP":
                self.reopen_posts += 1
            self.status = target
            if target == "FIN":
                self.resolution = {"name": "완료"}
            elif target == "WIP" and self.clears_resolution:
                self.resolution = None
            if "fields" in body:
                new = text_of(body["fields"][FINAL_RESULT_FIELD])
                old = text_of(self.value)
                saved = {"overwrite": new, "append": f"{old}\n{new}".strip(), "ignore": old or new}[self.mode]
                self.history.append((old, saved))
                self.value = adf(saved)
            return httpx.Response(204)
        fields = {"status": {"id": IDS[self.status], "name": self.status}}
        if "resolution" in (req.url.params.get("fields") or ""):
            fields.update(resolution=self.resolution, resolutiondate="2026-10-30T10:00:00.000+0900" if self.resolution else None)
        if FINAL_RESULT_FIELD in (req.url.params.get("fields") or ""):
            fields[FINAL_RESULT_FIELD] = self.value
        return httpx.Response(200, json={"fields": fields})


def run(fake):
    with JiraClient("https://example.atlassian.net", "bot@example.com", "t", transport=httpx.MockTransport(fake.handler)) as c:
        return reopen_probe(c, "ITHD-1")


def test_overwrite_passes_and_reports_history(capsys):
    fake = FakeJira()
    assert run(fake) is True
    out = capsys.readouterr().out
    assert "덮어씀" in out and "변경 이력에 1차 결과가 남아 있음: True" in out
    assert fake.status == "FIN" and fake.reopen_posts == 1


def test_missing_fin_to_wip_transition_stops_without_sending_it(capsys):
    fake = FakeJira(fin_to_wip=False)
    assert run(fake) is False
    assert "Jira 워크플로에 없습니다" in capsys.readouterr().out
    assert fake.status == "FIN" and fake.reopen_posts == 0


def test_appended_result_is_flagged(capsys):
    assert run(FakeJira(mode="append")) is False
    assert "이어 붙음" in capsys.readouterr().out


def test_ignored_new_result_is_flagged(capsys):
    assert run(FakeJira(mode="ignore")) is False
    assert "반영되지 않음" in capsys.readouterr().out


def test_uncleared_resolution_is_flagged(capsys):
    assert run(FakeJira(clears_resolution=False)) is False
    assert "해결 결과·해결 일시 비워짐: False" in capsys.readouterr().out
