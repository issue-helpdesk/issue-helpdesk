"""Jira 웹훅(TK-13)으로 들어온 본문을 읽기 쉬운 값으로 바꾼다.

네트워크와 DB를 쓰지 않는다. 이 파일은 "무슨 일이 일어났는지"만 읽어 낸다.
- 이벤트를 저장(jira_webhook_events)하고 중복을 거르고 접수별로 순서대로 처리하는 일은 백엔드 몫이다.
- `docs/api/03` TK-13: 이벤트 값으로 상태를 직접 덮어쓰지 않는다. 이 이벤트는 "Jira를 다시 조회하라"는 신호로 쓰고,
  실제 반영은 JiraClient.get_work_status / get_assignee 로 최신값을 읽어서 한다.

    event = parse_jira_webhook(payload, delivery_id=request.headers.get("X-Atlassian-Webhook-Identifier"))
    if event.status_changed or event.assignee_changed:
        ...  # event.issue_key 로 접수를 찾아 Jira 최신 상태를 조회
    if event.is_comment_created:
        ...  # event.comment.comment_id 로 JiraClient.get_comment 를 부르고, comment_notify.route_comment 로 받는 사람을 정한다
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, Mapping

from .mapper import work_status_from_jira


class WebhookError(ValueError):
    """웹훅 본문 형식 오류. API는 400 INVALID_REQUEST 로 응답한다."""


@dataclass(frozen=True)
class WebhookChange:
    field: str                      # status · assignee ...
    from_value: str | None          # 상태는 상태 ID, 담당자는 accountId
    to_value: str | None
    from_text: str | None = None    # 화면 이름 (참고용)
    to_text: str | None = None


@dataclass(frozen=True)
class WebhookComment:
    """comment_created · comment_updated 이벤트의 댓글 정보. 본문(글)은 읽지 않는다. 필요하면 JiraClient.get_comment 로 다시 조회한다."""
    comment_id: str
    author_account_id: str | None   # 작성자 Jira accountId. 알 수 없으면 None
    author_name: str | None         # 화면 이름 (참고용)
    author_type: str | None         # atlassian(사람) · app(앱·봇) · customer. 참고용
    created: str | None
    updated: str | None


@dataclass(frozen=True)
class WebhookEvent:
    event_id: str                   # 중복 검사 키. delivery_id → 변경 이력 ID → 댓글 ID → 본문 해시 순
    webhook_event: str
    issue_key: str
    timestamp_ms: int | None
    changes: tuple[WebhookChange, ...]
    comment: WebhookComment | None = None

    @property
    def is_comment_created(self) -> bool:
        """새 댓글이 달린 이벤트인가. 댓글 수정(comment_updated)·삭제는 알림 대상이 아니라서 False."""
        return self.webhook_event == "comment_created" and self.comment is not None

    def change(self, field: str) -> WebhookChange | None:
        return next((c for c in self.changes if c.field == field), None)

    @property
    def status_changed(self) -> bool:
        return self.change("status") is not None

    @property
    def assignee_changed(self) -> bool:
        return self.change("assignee") is not None

    @property
    def new_work_status(self) -> str | None:
        """변경 후 상태를 RDY·WIP·FIN·CLS 로. 상태가 안 바뀌었거나 매핑에 없으면 None. 참고용이며 반영 전에 Jira를 다시 조회한다."""
        c = self.change("status")
        return work_status_from_jira(c.to_value) if c else None

    @property
    def new_assignee_account_id(self) -> str | None:
        """변경 후 담당자 accountId. 담당자가 해제됐으면 None."""
        c = self.change("assignee")
        return c.to_value if c else None


def parse_jira_webhook(payload: Mapping[str, Any], *, delivery_id: str | None = None) -> WebhookEvent:
    if not isinstance(payload, Mapping):
        raise WebhookError("웹훅 본문이 JSON 객체가 아닙니다.")
    issue = payload.get("issue")
    key = issue.get("key") if isinstance(issue, Mapping) else None
    if not isinstance(key, str) or not key.strip():
        raise WebhookError("issue.key 가 없습니다.")

    changelog = payload.get("changelog")
    changelog = changelog if isinstance(changelog, Mapping) else {}
    changes = tuple(
        WebhookChange(
            field=str(item.get("field") or item.get("fieldId") or ""),
            from_value=_str_or_none(item.get("from")),
            to_value=_str_or_none(item.get("to")),
            from_text=_str_or_none(item.get("fromString")),
            to_text=_str_or_none(item.get("toString")),
        )
        for item in changelog.get("items") or []
        if isinstance(item, Mapping)
    )
    timestamp = payload.get("timestamp")
    comment = _comment_of(payload.get("comment"))
    return WebhookEvent(
        event_id=_event_id(payload, changelog, delivery_id, comment),
        webhook_event=str(payload.get("webhookEvent") or ""),
        issue_key=key.strip(),
        timestamp_ms=timestamp if isinstance(timestamp, int) and not isinstance(timestamp, bool) else None,
        changes=changes,
        comment=comment,
    )


def _comment_of(raw: Any) -> WebhookComment | None:
    """payload["comment"] 를 읽는다. 댓글 ID가 없으면 댓글 이벤트로 보지 않는다."""
    if not isinstance(raw, Mapping) or raw.get("id") in (None, ""):
        return None
    author = raw.get("author")
    author = author if isinstance(author, Mapping) else {}
    return WebhookComment(
        comment_id=str(raw["id"]),
        author_account_id=_str_or_none(author.get("accountId")),
        author_name=_str_or_none(author.get("displayName")),
        author_type=_str_or_none(author.get("accountType")),
        created=_str_or_none(raw.get("created")),
        updated=_str_or_none(raw.get("updated")),
    )


def verify_webhook_secret(received: str | None, expected: str | None) -> bool:
    """X-Itssue-Webhook-Secret 헤더와 환경 변수 JIRA_WEBHOOK_SECRET 비교. 어느 쪽이든 비어 있으면 거부한다."""
    if not received or not expected:
        return False
    return hmac.compare_digest(received.encode("utf-8"), expected.encode("utf-8"))


_HASHES = {"sha1": hashlib.sha1, "sha256": hashlib.sha256, "sha384": hashlib.sha384, "sha512": hashlib.sha512}


def verify_hub_signature(body: bytes, header: str | None, secret: str | None) -> bool:
    """Jira 관리자 웹훅의 서명 검증. Jira는 웹훅 설정의 「비밀값(secret)」으로 본문의 HMAC 서명을 만들어
    `X-Hub-Signature: sha256=<서명>` 헤더로 보낸다(Atlassian 웹훅 문서). 같은 비밀값으로 본문(받은 그대로의 바이트)에 서명해 비교한다.

    사용자 정의 헤더(`X-Itssue-Webhook-Secret`)는 Jira 관리자 웹훅 설정에서 넣을 수 있다고 확인하지 못해서, 이 방식을 기본으로 쓴다.
    비밀값이나 헤더가 없거나, 알 수 없는 방식이거나, 서명이 다르면 False.
    """
    if not header or not secret or not isinstance(body, (bytes, bytearray)):
        return False
    method, sep, signature = header.strip().partition("=")
    hasher = _HASHES.get(method.strip().lower())
    if not sep or hasher is None or not signature.strip():
        return False
    expected = hmac.new(secret.encode("utf-8"), bytes(body), hasher).hexdigest()
    return hmac.compare_digest(expected.encode("ascii"), signature.strip().lower().encode("utf-8", "ignore"))


def _str_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


def _event_id(payload: Mapping[str, Any], changelog: Mapping[str, Any], delivery_id: str | None,
              comment: WebhookComment | None = None) -> str:
    if delivery_id and delivery_id.strip():
        return f"delivery:{delivery_id.strip()}"
    if changelog.get("id"):
        return f"changelog:{changelog['id']}"
    if comment is not None:
        # 같은 댓글이 다시 와도 같은 키. 수정 이벤트는 updated 가 달라서 다른 키가 된다.
        return f"comment:{payload.get('webhookEvent')}:{comment.comment_id}:{comment.updated or comment.created or ''}"
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()
