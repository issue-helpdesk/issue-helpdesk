"""ITSD(IT Service Desk)에 티켓을 만들고 Jira가 발급한 ID·키·주소를 돌려준다.

    with JiraClient.from_env() as jira:
        result = jira.create_ticket(ticket)
        # {"jira_issue_id": "10999", "jira_key": "ITSD-353", "jira_url": "https://…/browse/ITSD-353", "created": True}

인증정보는 서버 환경 변수(JIRA_BASE_URL · JIRA_EMAIL · JIRA_API_TOKEN)에서만 읽는다.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

import httpx

from .mapper import MappingError, load_mapping, to_jira_fields, work_status_from_jira

DEFAULT_TIMEOUT = 10.0  # 초


class JiraError(Exception):
    """Jira 호출 실패. 연동 상태 기록·관리자 재처리에 쓸 이유와 재시도 가능 여부를 담는다.

    reason: timeout · network · result_unknown · auth · invalid_fields · invalid_transition · not_found · rate_limited · server_error · unexpected
    """

    def __init__(self, reason: str, message: str, *, retryable: bool, status_code: int | None = None):
        super().__init__(message)
        self.reason = reason
        self.retryable = retryable
        self.status_code = status_code

    def to_dict(self) -> dict[str, Any]:
        status = "VERIFYING" if self.reason == "result_unknown" else "FAILED"
        return {"status": status, "reason": self.reason, "retryable": self.retryable, "message": str(self)}


class JiraClient:
    def __init__(
        self,
        base_url: str,
        email: str,
        api_token: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        mapping: Mapping[str, Any] | None = None,
        transport: httpx.BaseTransport | None = None,  # 테스트에서 모의 응답을 끼울 때만
    ):
        self.base_url = base_url.rstrip("/")
        self.mapping = mapping or load_mapping()
        self._http = httpx.Client(
            base_url=self.base_url,
            auth=(email, api_token),
            timeout=timeout,
            headers={"Accept": "application/json"},
            transport=transport,
        )

    @classmethod
    def from_env(cls, **kwargs: Any) -> "JiraClient":
        from app.core.config import get_jira_settings  # .env 를 읽는 곳은 core/config 한 곳

        try:
            s = get_jira_settings()
        except RuntimeError as e:
            raise JiraError("auth", str(e), retryable=False) from e
        return cls(s.base_url, s.email, s.api_token, **kwargs)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "JiraClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ---------------------------------------------------------------- 공개 함수

    def create_ticket(self, ticket: Mapping[str, Any]) -> dict[str, Any]:
        """접수 1건을 ITSD 티켓으로 만든다.

        같은 접수번호의 티켓이 이미 있으면 새로 만들지 않고 그 티켓을 돌려준다(created=False).
        검색 반영 지연·동시 요청까지 원자적으로 막지는 않는다. 백엔드 작업 잠금이 필요하다.
        생성 응답이 불명확하면 result_unknown을 반환한다. 기존 생성 여부 확인 전 재생성하지 않는다.
        자동 재시도는 하지 않는다. JiraError.retryable 을 보고 연동 작업(integration_jobs)이 정한다.
        """
        try:
            fields = to_jira_fields(ticket, self.mapping)
        except MappingError as e:
            raise JiraError("invalid_fields", str(e), retryable=False) from e

        existing = self.find_by_receipt(str(ticket["receipt_no"]).strip())
        if existing:
            return {**existing, "created": False}

        try:
            data = self._request("POST", "/rest/api/3/issue", json={"fields": fields})
        except JiraError as e:
            if e.reason in ("timeout", "network", "server_error"):
                raise JiraError(
                    "result_unknown", "Jira 생성 결과를 확인해야 합니다. 기존 이슈 확인 전 재생성하지 마세요.",
                    retryable=False, status_code=e.status_code,
                ) from e
            raise
        return {**self._result(data["id"], data["key"]), "created": True}

    def find_by_receipt(self, receipt_no: str) -> dict[str, Any] | None:
        """ITssue 접수번호로 이미 만든 티켓을 찾는다. 없으면 None."""
        field = self.mapping["fields"]["receipt_no"]["jira"]           # customfield_10113
        number = field.removeprefix("customfield_")
        phrase = '"' + receipt_no.replace('\\', '\\\\').replace('"', '\\"') + '"'
        jql = f'project = "{self.mapping["project"]["key"]}" AND cf[{number}] ~ {json.dumps(phrase, ensure_ascii=False)}'
        query = {"jql": jql + " ORDER BY created ASC", "fields": [field], "maxResults": 20}
        seen_tokens: set[str] = set()
        while True:
            data = self._request("POST", "/rest/api/3/search/jql", json=query)
            for issue in data.get("issues", []):
                # 글자 검색은 비슷한 번호도 찾으므로 모든 페이지에서 정확히 대조한다.
                if (issue.get("fields") or {}).get(field) == receipt_no:
                    return self._result(issue["id"], issue["key"])
            token = data.get("nextPageToken")
            if data.get("isLast") is True or not token:
                return None
            if token in seen_tokens:
                raise JiraError("unexpected", "Jira 검색 페이지가 반복되어 생성하지 않았습니다.", retryable=False)
            seen_tokens.add(token)
            query["nextPageToken"] = token

    def check_auth(self) -> dict[str, Any]:
        """토큰이 맞는지 확인한다. 토큰 주인 계정의 이름·accountId를 돌려준다(이 계정이 티켓 보고자가 된다)."""
        me = self._request("GET", "/rest/api/3/myself")
        return {"account_id": me.get("accountId"), "display_name": me.get("displayName")}

    def get_issue(self, issue_key: str, fields: list[str] | None = None) -> dict[str, Any]:
        params = {"fields": ",".join(fields)} if fields else None
        return self._request("GET", f"/rest/api/3/issue/{issue_key}", params=params)

    def check_saved(self, issue_key: str, ticket: Mapping[str, Any]) -> dict[str, tuple[Any, Any]]:
        """보낸 값과 Jira에 저장된 값을 비교한다. 다른 필드만 {필드: (보낸 값, 저장된 값)}로 돌려준다."""
        sent = to_jira_fields(ticket, self.mapping)
        sent.pop("project", None)
        sent.pop("description", None)  # Jira가 ADF 모양을 조금 바꿔 저장할 수 있어 비교하지 않는다
        saved = self.get_issue(issue_key, list(sent))["fields"]
        diffs: dict[str, tuple[Any, Any]] = {}
        for field, want in sent.items():
            got = saved.get(field)
            if field == "components":
                ok = sorted(c["id"] for c in want) == sorted(str(c.get("id")) for c in got or [])
            elif isinstance(want, dict):
                ok = isinstance(got, dict) and str(got.get("id")) == want["id"]
            else:
                ok = got == want
            if not ok:
                diffs[field] = (want, got)
        return diffs

    # ---------------------------------------------------------------- 담당자 지정·상태 전환 (M5-1-3·M5-3-1)

    def get_assignee(self, issue_key: str) -> dict[str, Any]:
        """Jira에 지금 지정된 담당자를 조회한다. 배정 결과 확인(⑥)에 쓴다. 담당자가 없으면 account_id가 None."""
        fields = self.get_issue(issue_key, ["assignee"])["fields"]
        who = fields.get("assignee") or {}
        return {"account_id": who.get("accountId"), "display_name": who.get("displayName")}

    def assign_issue(self, issue_key: str, account_id: str) -> dict[str, Any]:
        """Jira 담당자를 지정하고, 다시 조회해 요청한 계정과 같은지 비교한다.

        같은 계정으로 다시 불러도 결과가 같아서(멱등) 시간 초과·통신 오류는 retryable=True 로 올린다.
        반환: {"matched": bool, "account_id": 요청한 계정, "actual_account_id": Jira에 있는 계정}
        matched=False 이면 ITssue는 배정을 확정하지 않고 예약을 풀어 팀장 확인으로 넘긴다(`docs/11` 2.5).
        """
        if not str(account_id or "").strip():
            raise JiraError("invalid_fields", "담당자 accountId가 비어 있습니다.", retryable=False)
        account_id = str(account_id).strip()
        self._request("PUT", f"/rest/api/3/issue/{issue_key}/assignee", json={"accountId": account_id})
        actual = self.get_assignee(issue_key)["account_id"]
        return {"matched": actual == account_id, "account_id": account_id, "actual_account_id": actual}

    def get_work_status(self, issue_key: str) -> dict[str, Any]:
        """Jira 상태를 ITssue 업무 상태(RDY·WIP·FIN·CLS)로 바꿔 돌려준다. 매핑에 없는 상태면 work_status=None."""
        status = self.get_issue(issue_key, ["status"])["fields"].get("status") or {}
        return {"work_status": work_status_from_jira(status.get("id"), self.mapping),
                "status_id": status.get("id"), "status_name": status.get("name")}

    def transition_issue(self, issue_key: str, target: str) -> dict[str, Any]:
        """Jira 상태를 target(RDY·WIP·FIN·CLS)으로 옮긴다.

        먼저 현재 상태를 보고, 이미 target 이면 아무것도 보내지 않는다(changed=False). 그래서 시간 초과 뒤 다시 불러도 안전하다.
        Jira 워크플로가 현재 상태에서 target 으로 바로 가는 전환을 허용하지 않으면 invalid_transition(재시도 불가)이다.
        FIN·CLS 에서 뒤로(WIP·RDY 등) 되돌리는 전환은 Jira 워크플로와 상관없이 막는다(팀 결정). 이미 끝난 일은 새 티켓으로 다룬다.
        반환: {"changed": bool, "work_status": target}
        """
        values = self.mapping["options"]["work_status"]["values"]
        if target not in values:
            raise JiraError("invalid_fields", f"work_status '{target}'는 매핑에 없습니다. 가능한 값: {', '.join(values)}",
                            retryable=False)
        target_id = values[target]["id"]
        current = self.get_work_status(issue_key)["work_status"]
        if current == target:
            return {"changed": False, "work_status": target}
        # 팀 결정: 처리 완료(FIN)·종결(CLS)된 티켓은 되돌리지 않는다. 다시 필요하면 새 접수로 만든다.
        order = ("RDY", "WIP", "FIN", "CLS")
        if current in ("FIN", "CLS") and order.index(target) < order.index(current):
            raise JiraError("invalid_transition", f"{issue_key}는 {current} 상태라 {target}으로 되돌릴 수 없습니다. 새 티켓을 만드세요.",
                            retryable=False)
        listed = self._request("GET", f"/rest/api/3/issue/{issue_key}/transitions")
        for t in listed.get("transitions", []):
            if str((t.get("to") or {}).get("id")) == target_id:
                self._request("POST", f"/rest/api/3/issue/{issue_key}/transitions", json={"transition": {"id": t["id"]}})
                return {"changed": True, "work_status": target}
        raise JiraError("invalid_transition", f"{issue_key}는 현재 상태에서 {target}으로 바로 전환할 수 없습니다.",
                        retryable=False)

    # ---------------------------------------------------------------- 내부

    def _result(self, issue_id: str, key: str) -> dict[str, Any]:
        return {
            "jira_issue_id": str(issue_id),
            "jira_key": key,
            "jira_url": f"{self.base_url}{self.mapping['create']['browse_path']}{key}",
        }

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            resp = self._http.request(method, path, **kwargs)
        except httpx.TimeoutException as e:
            # 생성 요청이었다면 이미 만들어졌을 수 있다. create_ticket 을 다시 부르면 먼저 찾아본다.
            raise JiraError("timeout", "Jira 응답 시간이 초과되었습니다.", retryable=True) from e
        except httpx.TransportError as e:
            raise JiraError("network", f"Jira에 연결하지 못했습니다: {e}", retryable=True) from e

        if resp.is_success:
            return resp.json() if resp.content else {}

        status = resp.status_code
        detail = _error_text(resp)
        if status in (401, 403):
            raise JiraError("auth", f"Jira 인증 또는 권한 오류입니다. {detail}", retryable=False, status_code=status)
        if status == 400:
            raise JiraError("invalid_fields", f"Jira가 값을 거부했습니다. {detail}", retryable=False, status_code=status)
        if status == 404:
            raise JiraError("not_found", f"Jira에서 찾지 못했습니다. {detail}", retryable=False, status_code=status)
        if status == 429:
            raise JiraError("rate_limited", "Jira 요청 한도를 넘었습니다.", retryable=True, status_code=status)
        if status >= 500:
            raise JiraError("server_error", f"Jira 서버 오류입니다. {detail}", retryable=True, status_code=status)
        raise JiraError("unexpected", f"예상하지 못한 응답({status}). {detail}", retryable=False, status_code=status)


def _error_text(resp: httpx.Response) -> str:
    """Jira 오류 응답에서 읽을 부분만 꺼낸다. 요청 본문(접수 내용)은 넣지 않는다."""
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200]
    parts = list(body.get("errorMessages") or [])
    parts += [f"{k}: {v}" for k, v in (body.get("errors") or {}).items()]
    return " / ".join(parts)[:500]
