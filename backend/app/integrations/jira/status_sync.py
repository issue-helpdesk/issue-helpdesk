"""Jira 최신 조회 결과로 ITssue에 반영할 상태를 결정한다. DB는 수정하지 않는다."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .webhook import WebhookEvent

WORK_STATUSES = frozenset({"RDY", "WIP", "FIN", "CLS"})


def needs_status_refresh(event: WebhookEvent) -> bool:
    """이슈 수정 중 상태 변경만 재조회한다. 제목·댓글·담당자만 바뀐 경우는 제외."""
    return event.webhook_event == "jira:issue_updated" and event.status_changed


@dataclass(frozen=True)
class StatusSyncPlan:
    issue_key: str
    event_id: str
    work_status: str | None
    reason: str
    jira_status_id: str | None = None
    jira_status_name: str | None = None
    current_work_status: str | None = None


def plan_status_sync(
    event: WebhookEvent,
    latest: Mapping[str, Any] | None,
    *,
    current_work_status: str | None = None,
) -> StatusSyncPlan:
    """latest에는 JiraClient.get_work_status()의 결과를 전달한다.

    이벤트의 from/to 값은 갱신 신호로만 쓴다. 지연된 웹훅의 과거 상태로 DB를 덮어쓰지 않는다.
    current_work_status는 백엔드가 잠근 티켓에서 읽은 값이다. 미전달 시 상태 해석까지만 한다.
    매핑이 없는 Jira 상태는 work_status=None이며 DB에 반영하지 않는다.
    """
    if current_work_status is not None and current_work_status not in WORK_STATUSES:
        raise ValueError("current_work_status는 RDY/WIP/FIN/CLS 또는 None이어야 합니다.")
    base = dict(issue_key=event.issue_key, event_id=event.event_id, current_work_status=current_work_status)
    if event.webhook_event != "jira:issue_updated":
        return StatusSyncPlan(**base, work_status=None, reason="ignored_event")
    if not event.status_changed:
        return StatusSyncPlan(**base, work_status=None, reason="not_status_change")
    if latest is None:
        raise ValueError("상태 변경은 Jira 최신 상태 조회 후 처리해야 합니다.")
    status = latest.get("work_status")
    status_id = latest.get("status_id")
    status_name = latest.get("status_name")
    resolved = dict(jira_status_id=str(status_id) if status_id is not None else None,
                    jira_status_name=str(status_name) if status_name is not None else None)
    if not isinstance(status, str) or status not in WORK_STATUSES:
        return StatusSyncPlan(**base, **resolved, work_status=None, reason="unmapped_status")
    return StatusSyncPlan(**base, **resolved, work_status=status,
                          reason="unchanged" if status == current_work_status else "status_resolved")
