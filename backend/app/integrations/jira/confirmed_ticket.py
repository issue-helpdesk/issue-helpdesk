"""저장된 TK-04 Ticket 응답을 기존 Jira 생성 모듈에 연결한다.

호출자는 인증·초안 버전 확인·접수 확정·DB 커밋을 마친 서버여야 한다.
브라우저의 임의 JSON을 그대로 받아 생성하는 API가 아니다. 이 모듈은 DB를
조회/저장하지 않으므로 접수별 잠금과 생성 결과의 즉시 저장은 호출자 책임이다.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from .client import JiraClient


class ConfirmedTicketError(ValueError):
    """접수 데이터 또는 처리 상태가 Jira 생성에 적합하지 않다."""

    def __init__(self, reason: str, fields: tuple[str, ...]):
        self.reason = reason
        self.fields = fields
        super().__init__(f"{reason}: {', '.join(fields)}")


def _text(data: Mapping[str, Any], key: str, *, required: bool = False) -> str:
    value = data.get(key)
    if value is None or value == "":
        if required:
            raise ConfirmedTicketError("missing_value", (key,))
        return ""
    if not isinstance(value, str):
        raise ConfirmedTicketError("invalid_type", (key,))
    value = value.strip()
    if required and not value:
        raise ConfirmedTicketError("missing_value", (key,))
    return value


def _positive_id(data: Mapping[str, Any], key: str) -> int:
    value = data.get(key)
    if type(value) is not int or value <= 0:
        raise ConfirmedTicketError("invalid_id", (key,))
    return value


def _identity(ticket: Mapping[str, Any]) -> tuple[int, str]:
    if not isinstance(ticket, Mapping):
        raise ConfirmedTicketError("invalid_type", ("ticket",))
    ticket_id = _positive_id(ticket, "id")
    _positive_id(ticket, "draftId")
    receipt = _text(ticket, "receiptNo", required=True)
    if len(receipt) > 255:
        raise ConfirmedTicketError("receipt_too_long", ("receiptNo",))
    return ticket_id, receipt


def to_jira_ticket(ticket: Mapping[str, Any]) -> dict[str, str]:
    """TK-04 Ticket(camelCase) → JiraClient.create_ticket 입력(snake_case).

    분류·긴급도·담당 그룹은 확정값을 사용하고, 누락 시 추측하지 않는다.
    호출 전 저장 상태 확인은 create_from_confirmed_ticket에서 수행한다.
    """
    _, receipt = _identity(ticket)
    summary = _text(ticket, "summary", required=True)
    category = _text(ticket, "categoryCode", required=True)
    urgency = _text(ticket, "urgency", required=True)
    group_id = _positive_id(ticket, "groupId")
    group = ticket.get("group")
    if not isinstance(group, Mapping):
        raise ConfirmedTicketError("missing_value", ("group",))
    if _positive_id(group, "id") != group_id:
        raise ConfirmedTicketError("group_mismatch", ("groupId", "group.id"))
    group_name = _text(group, "name", required=True)

    result = {
        "receipt_no": receipt,
        "title": summary,
        "category_code": category,
        "urgency": urgency,
        "group_name": group_name,
    }
    # 기존 매핑에 있는 선택 항목만 전달한다. 누락값을 코드 등에서 추측하지 않는다.
    for source, field, target in (
        ("category", "name", "category_name"),
        ("inquiryType", "name", "inquiry_type_name"),
        ("inquiryType", "code", "inquiry_type_code"),
    ):
        reference = ticket.get(source)
        if reference is None:
            continue
        if not isinstance(reference, Mapping):
            raise ConfirmedTicketError("invalid_type", (source,))
        value = reference.get(field)
        if value is None:
            continue
        if not isinstance(value, str):
            raise ConfirmedTicketError("invalid_type", (f"{source}.{field}",))
        if value.strip():
            result[target] = value.strip()
    # 긴 요약도 본문에 남긴다. Jira 제목 길이 제한은 기존 mapper에서 적용한다.
    parts = [("문의 요약", summary)]
    for source, label in (
        ("targetSystem", "대상 시스템"),
        ("symptom", "증상"),
        ("occurredAt", "발생 시점"),
        ("businessImpact", "업무 영향"),
        ("triedActions", "시도한 조치"),
        ("urgencyReason", "긴급도 근거"),
    ):
        value = _text(ticket, source)
        if value:
            parts.append((label, value))
        if source == "targetSystem" and value:
            result["target_system"] = value
    result["description"] = "\n\n".join(f"[{label}]\n{value}" for label, value in parts)

    # API 계약에 있는 문의자 항목만 허용한다. 토큰·대화 원문·임의 키는 복사하지 않는다.
    requester = ticket.get("requester")
    if requester is not None:
        if not isinstance(requester, Mapping):
            raise ConfirmedTicketError("invalid_type", ("requester",))
        for source, target in (("employeeNo", "requester_employee_no"), ("name", "requester_name")):
            value = _text(requester, source)
            if value:
                result[target] = value
    return result


def create_from_confirmed_ticket(
    jira: JiraClient,
    ticket: Mapping[str, Any],
) -> dict[str, Any]:
    """DB에 저장된 접수 1건을 Jira에 생성하거나 이미 연결된 키를 반환한다.

    JiraError는 그대로 전달한다. result_unknown은 VERIFYING으로 기록하고,
    기존 생성 여부를 확인하기 전 이 함수를 다시 실행하지 않는다.
    성공 결과도 DB 저장 완료나 개인 담당자 배정 완료를 의미하지 않는다.
    """
    ticket_id, receipt = _identity(ticket)
    status = _text(ticket, "jiraSyncStatus", required=True)
    if status not in {"PENDING", "VERIFYING", "SYNCED", "NEEDS_ADMIN"}:
        raise ConfirmedTicketError("invalid_sync_status", ("jiraSyncStatus",))

    existing = _text(ticket, "jiraKey")
    if existing:
        project_key = str(jira.mapping["project"]["key"])
        if not re.fullmatch(re.escape(project_key) + r"-[1-9]\d*", existing):
            raise ConfirmedTicketError("invalid_jira_key", ("jiraKey",))
        return {
            "ticket_id": ticket_id, "receipt_no": receipt,
            "jira_issue_id": None, "jira_key": existing,
            "jira_url": f"{jira.base_url}{jira.mapping['create']['browse_path']}{existing}",
            "created": False, "source": "saved_ticket",
        }

    if status != "PENDING":
        # VERIFYING 재생성·관리자 확인 상태의 임의 해제·SYNCED 불일치를 막는다.
        raise ConfirmedTicketError("creation_not_allowed", ("jiraSyncStatus", "jiraKey"))

    payload = to_jira_ticket(ticket)
    # 기존 클라이언트가 선택값을 통신 전에 검사하고 JiraError로 반환한다.
    result = jira.create_ticket(payload)
    return {**result, "ticket_id": ticket_id, "receipt_no": receipt, "source": "jira"}
