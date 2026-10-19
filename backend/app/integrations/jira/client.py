"""ITSD(IT Service Desk)에 티켓을 만들고 Jira가 발급한 ID·키·주소를 돌려준다.

    with JiraClient.from_env() as jira:
        result = jira.create_ticket(ticket)
        # {"jira_issue_id": "10999", "jira_key": "ITSD-353", "jira_url": "https://…/browse/ITSD-353", "created": True}

인증정보는 서버 환경 변수(JIRA_BASE_URL · JIRA_EMAIL · JIRA_API_TOKEN)에서만 읽는다.
"""

from __future__ import annotations

from typing import Any, Mapping

import httpx

from .mapper import MappingError, load_mapping, to_jira_fields

DEFAULT_TIMEOUT = 10.0  # 초


class JiraError(Exception):
    """Jira 호출 실패. 연동 상태 기록·관리자 재처리에 쓸 이유와 재시도 가능 여부를 담는다.

    reason: timeout · network · auth · invalid_fields · not_found · rate_limited · server_error · unexpected
    """

    def __init__(self, reason: str, message: str, *, retryable: bool, status_code: int | None = None):
        super().__init__(message)
        self.reason = reason
        self.retryable = retryable
        self.status_code = status_code

    def to_dict(self) -> dict[str, Any]:
        return {"status": "FAILED", "reason": self.reason, "retryable": self.retryable, "message": str(self)}


class JiraClient:
    def __init__(
        self,
        base_url: str,
        email: str,
        api_token: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        mapping: Mapping[str, Any] | None = None,
        transport: httpx.BaseTransport | None = None,  # 테스트에서 가짜 응답을 끼울 때만
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
        그래서 시간 초과로 결과가 불명확했던 건도 다시 부르면 중복 없이 처리된다 (설계서 10.1).
        자동 재시도는 하지 않는다. JiraError.retryable 을 보고 연동 작업(integration_jobs)이 정한다.
        """
        try:
            fields = to_jira_fields(ticket, self.mapping)
        except MappingError as e:
            raise JiraError("invalid_fields", str(e), retryable=False) from e

        existing = self.find_by_receipt(str(ticket["receipt_no"]).strip())
        if existing:
            return {**existing, "created": False}

        data = self._request("POST", "/rest/api/3/issue", json={"fields": fields})
        return {**self._result(data["id"], data["key"]), "created": True}

    def find_by_receipt(self, receipt_no: str) -> dict[str, Any] | None:
        """ITssue 접수번호로 이미 만든 티켓을 찾는다. 없으면 None."""
        field = self.mapping["fields"]["receipt_no"]["jira"]           # customfield_10113
        number = field.removeprefix("customfield_")
        jql = f'project = "{self.mapping["project"]["key"]}" AND cf[{number}] ~ "\\"{receipt_no}\\""'
        data = self._request(
            "POST",
            "/rest/api/3/search/jql",
            json={"jql": jql + " ORDER BY created ASC", "fields": [field], "maxResults": 20},
        )
        for issue in data.get("issues", []):
            # 글자 검색은 비슷한 번호도 찾으므로 값이 정확히 같은지 다시 본다
            if (issue.get("fields") or {}).get(field) == receipt_no:
                return self._result(issue["id"], issue["key"])
        return None

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
