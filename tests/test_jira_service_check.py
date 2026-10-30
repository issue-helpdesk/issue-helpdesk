"""service_check.py(생성 서비스 실제 Jira 종단 점검)의 흐름이 맞는지 상태를 가진 모의 Jira로 확인한다. 실제 Jira는 부르지 않는다.

    pytest tests/test_jira_service_check.py
"""

import json

import httpx

from app.integrations.jira import JiraClient
from app.integrations.jira.service_check import run_check


class StatefulJira:
    """생성한 이슈를 기억하고 접수번호 검색에 응답한다. index_visible=False 면 검색에 나타나지 않는다(색인 지연)."""

    def __init__(self, *, index_visible=True):
        self.issues: list[dict] = []
        self.index_visible = index_visible

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("search/jql"):
            jql = json.loads(req.content)["jql"]
            found = [i for i in self.issues if i["receipt"] in jql] if self.index_visible else []
            return httpx.Response(200, json={"issues": [
                {"id": i["id"], "key": i["key"], "fields": {"customfield_10043": i["receipt"]}} for i in found], "isLast": True})
        if req.method == "POST" and req.url.path == "/rest/api/3/issue":
            fields = json.loads(req.content)["fields"]
            n = len(self.issues) + 1
            self.issues.append({"id": str(20000 + n), "key": f"ITHD-{900 + n}", "receipt": fields["customfield_10043"]})
            return httpx.Response(201, json={"id": self.issues[-1]["id"], "key": self.issues[-1]["key"]})
        return httpx.Response(200, json={})


def run(fake, **kw):
    with JiraClient("https://jira.example", "bot@example.com", "t", transport=httpx.MockTransport(fake)) as c:
        return run_check(c, stamp="TEST", wait_tries=2, wait_delay=0, **kw)


def test_full_flow_passes_and_creates_exactly_one_issue(capsys):
    fake = StatefulJira()
    assert run(fake) is True
    out = capsys.readouterr().out
    assert "CREATED" in out and "LINKED" in out and "확인 필요" not in out
    assert len(fake.issues) == 1  # 유실 흉내 뒤에도 새로 만들지 않고 연결만 했다


def test_search_lag_is_reported_and_skips_the_link_step(capsys):
    fake = StatefulJira(index_visible=False)
    assert run(fake) is False
    out = capsys.readouterr().out
    assert "검색에 방금 만든 이슈가 나타남" in out and "LINKED" not in out
    assert len(fake.issues) == 1
