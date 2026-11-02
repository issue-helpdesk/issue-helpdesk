"""M5-1-3: 최초 배정과 서버가 승인한 재배정의 Jira 실행·재조회 연결.

서버가 같은 담당 그룹의 대상자를 검증·예약한 뒤 호출한다. DB 조회·예약,
전체 후보 선정, 작업 잠금·revision 확인은 호출자가 담당한다.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping

from .assignment import Member, pick_assignee
from .client import JiraClient


@dataclass(frozen=True)
class AssignmentTarget:
    """서버가 해당 그룹에서 조회·예약한 담당자. 계정 ID는 Member에 담는다."""

    group_id: int
    member: Member
    service_role: str


class TicketAssignmentError(ValueError):
    """연결할 접수·예약·그룹 정보가 일치하지 않는다. Jira를 호출하지 않는다."""


class StaleAssignmentError(TicketAssignmentError):
    """오래된 작업이다. 호출자는 현재 배정 상태를 바꾸지 않고 중단한다."""


@dataclass(frozen=True)
class ReassignmentContext:
    """TK-09 권한 확인·예약 저장 후 서버가 구성하는 작업 정보. API 요청 DTO가 아니다."""

    expected_account_id: str | None
    revision: int
    current_revision: int
    reason: str
    manual: bool = False


def _id(value: Any, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise TicketAssignmentError(f"{field}: 양의 정수가 필요합니다.")
    return value


def assign_confirmed_ticket(
    jira: JiraClient,
    ticket: Mapping[str, Any],
    target: AssignmentTarget,
    *,
    exclude_user_ids: Iterable[int] = (),
    reassignment: ReassignmentContext | None = None,
) -> dict[str, Any]:
    """정해진 담당자 1명의 자격 검사 → 현재 담당자 확인 → 지정 → 재조회.

    ticket은 접수·Jira 키·배정 예약이 저장된 최신 TK-04 Ticket 형식이다.
    사용자 입력 JSON을 직접 넘기지 않는다. ASSIGNED 반환은 Jira 대조 결과이며
    이 함수가 DB에 저장했다는 뜻이 아니다. JiraError는 그대로 전달한다.
    """
    if not isinstance(ticket, Mapping):
        raise TicketAssignmentError("ticket: 저장된 접수 데이터가 필요합니다.")
    if not isinstance(target, AssignmentTarget) or not isinstance(target.member, Member):
        raise TicketAssignmentError("target: AssignmentTarget과 Member가 필요합니다.")
    ticket_id = _id(ticket.get("id"), "id")
    group_id = _id(ticket.get("groupId"), "groupId")
    _id(target.group_id, "target.group_id")
    _id(target.member.user_id, "target.member.user_id")
    if group_id != target.group_id:
        raise TicketAssignmentError("접수 담당 그룹과 대상자의 그룹이 다릅니다.")
    if _id(ticket.get("assigneeId"), "assigneeId") != target.member.user_id:
        raise TicketAssignmentError("저장된 배정 예약과 대상자가 다릅니다.")
    if ticket.get("jiraSyncStatus") != "SYNCED":
        raise TicketAssignmentError("Jira 생성 결과를 DB에 저장한 뒤 호출해야 합니다.")
    if ticket.get("assignStatus") not in {"PENDING", "ASSIGNED"}:
        raise TicketAssignmentError("배정 예약 또는 확인된 배정 상태가 필요합니다.")
    if ticket.get("workStatus") == "CLS":
        raise TicketAssignmentError("종료(CLS)된 접수는 배정하지 않습니다(TK-09).")
    key = ticket.get("jiraKey")
    prefix = re.escape(str(jira.mapping["project"]["key"]))
    if not isinstance(key, str) or not re.fullmatch(prefix + r"-[1-9]\d*", key):
        raise TicketAssignmentError("저장된 현재 프로젝트의 jiraKey가 필요합니다.")

    expected = None
    if reassignment is not None:
        if not isinstance(reassignment, ReassignmentContext):
            raise TicketAssignmentError("서버가 구성한 ReassignmentContext가 필요합니다.")
        if type(reassignment.revision) is not int or reassignment.revision < 1:
            raise TicketAssignmentError("재배정 작업의 revision은 양의 정수여야 합니다.")
        if type(reassignment.current_revision) is not int or reassignment.current_revision < 0:
            raise TicketAssignmentError("DB에서 읽은 현재 revision이 필요합니다.")
        if reassignment.revision != reassignment.current_revision:
            raise StaleAssignmentError("오래된 배정 작업이므로 현재 상태를 유지하고 중단합니다.")
        if not isinstance(reassignment.reason, str) or not 1 <= len(reassignment.reason.strip()) <= 500:
            raise TicketAssignmentError("재배정 사유는 1~500자여야 합니다(TK-09).")
        if type(reassignment.manual) is not bool:
            raise TicketAssignmentError("수동 지정 여부는 서버가 구성한 bool 값이어야 합니다.")
        expected = reassignment.expected_account_id
        if expected is not None:
            if not isinstance(expected, str) or not expected.strip():
                raise TicketAssignmentError("작업이 예상한 이전 Jira accountId 또는 None이 필요합니다.")
            expected = expected.strip()

    def result(status: str, reason: str, actual: str | None = None) -> dict[str, Any]:
        return {
            "ticket_id": ticket_id, "jira_key": key,
            "user_id": target.member.user_id,
            "account_id": target.member.jira_account_id,
            "actual_account_id": actual,
            "assign_status": status, "reason": reason,
            "db_updated": False,
        }

    if target.service_role not in {"AGENT", "ADMIN"}:
        return result("NEEDS_ADMIN", "ineligible_service_role")
    if not isinstance(target.member.employee_no, str) or not target.member.employee_no.strip():
        raise TicketAssignmentError("대상자의 내부 사번이 필요합니다.")
    account = target.member.jira_account_id
    if account is not None and not isinstance(account, str):
        raise TicketAssignmentError("Jira accountId는 문자열이어야 합니다.")
    subtype = ticket.get("inquiryType")
    scenario = subtype.get("code") if isinstance(subtype, Mapping) else None
    if scenario is not None and not isinstance(scenario, str):
        raise TicketAssignmentError("inquiryType.code는 문자열이어야 합니다.")
    if reassignment is None or not reassignment.manual:
        decision = pick_assignee(
            [target.member], scenario_id=scenario,
            exclude_user_ids=exclude_user_ids,
        )
        if not decision.selected:
            return result("NEEDS_ADMIN", decision.excluded.get(target.member.user_id, decision.reason))
    else:
        # TK-09 공통 자격은 검사한다. 자동 선정 전용 팀장·부재 제외는
        # 사유를 받은 수동 지정에 그대로 적용하지 않는다(docs/11 3.1).
        member = target.member
        checks = (
            (member.user_active, "사용자 비활성"),
            (member.member_active, "그룹 구성원 아님(비활성)"),
            (member.assignable, "자동배정 대상 아님"),
            (bool(scenario) and scenario in member.scenario_ids, "해당 세부 분류 처리 불가"),
            (bool(account and account.strip()), "Jira 계정 없음"),
        )
        for eligible, reason in checks:
            if not eligible:
                return result("NEEDS_ADMIN", reason)

    account = account.strip()
    current = jira.get_assignee(key)["account_id"]
    if current == account:
        return result("ASSIGNED", "already_assigned", current)
    if reassignment is not None:
        if current != expected:
            return result("NEEDS_ADMIN", "reassignment_source_changed", current)
    elif current is not None:
        # 지정 전에 이미 다른 계정이면 사람이 바꾼 값일 수 있으므로 덮어쓰지 않는다.
        return result("NEEDS_ADMIN", "existing_assignee_conflict", current)
    if ticket["assignStatus"] == "ASSIGNED":
        reason = "confirmed_assignment_removed" if current is None else "confirmed_assignment_changed"
        return result("NEEDS_ADMIN", reason, current)

    outcome = jira.assign_issue(key, account)
    actual = outcome["actual_account_id"]
    if not outcome["matched"]:
        return result("NEEDS_ADMIN", "assignment_mismatch", actual)
    return result("ASSIGNED", "assignment_verified", actual)
