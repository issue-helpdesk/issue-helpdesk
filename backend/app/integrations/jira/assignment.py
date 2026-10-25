"""담당자 선정 — 같은 담당 그룹 구성원 중 1명을 고른다 (`docs/11` 2.3·2.4).

DB도 네트워크도 쓰지 않는 순수 함수다. 구성원 목록과 업무량은 호출하는 쪽(백엔드)이 DB에서 모아 넘기고,
이 함수는 "누구를 고를지"만 정한다. 그래서 같은 입력이면 항상 같은 결과가 나온다.

    decision = pick_assignee(members, scenario_id="NET-01")
    if decision.selected:
        ...  # decision.user_id 에게 예약(assign_status=PENDING) 후 JIRA_ASSIGN 작업 등록
    else:
        ...  # decision.reason 을 assignment_logs 에 남기고 팀장 확인으로

업무량 = RDY + WIP + 예약(PENDING). 숫자를 세는 일은 호출하는 쪽 몫이다 (`docs/06` 기준 쿼리는 `docs/11` 3장).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable


@dataclass(frozen=True)
class Member:
    """담당 그룹 구성원 1명의 배정 판단용 정보."""

    user_id: int
    employee_no: str
    name: str = ""
    is_manager: bool = False                 # 팀장(서비스 역할 MANAGER)은 자동배정에서 제외
    user_active: bool = True                 # users 상태가 ACTIVE
    member_active: bool = True               # support_group_members 활성
    assignable: bool = True                  # 자동배정 대상 여부
    jira_account_id: str | None = None
    scenario_ids: frozenset[str] = frozenset()   # member_skills: 처리할 수 있는 세부 분류
    rdy: int = 0
    wip: int = 0
    reserved: int = 0                        # 선정됐지만 Jira 확인 전인 건(PENDING)
    last_assigned_at: datetime | None = None  # assignment_logs ASSIGN·REASSIGN 의 가장 최근 시각

    @property
    def workload(self) -> int:
        return self.rdy + self.wip + self.reserved


@dataclass(frozen=True)
class AssignDecision:
    selected: bool
    user_id: int | None = None
    reason: str = ""                                         # assignment_logs.reason 에 그대로 남길 문장
    workload: int | None = None
    excluded: dict[int, str] = field(default_factory=dict)   # user_id → 후보에서 빠진 이유
    candidate_ids: tuple[int, ...] = ()                      # 후보가 된 user_id (정렬 전)


def _excluded_reason(m: Member, scenario_id: str, require_jira_account: bool) -> str | None:
    if m.is_manager:
        return "팀장 제외"
    if not m.user_active:
        return "사용자 비활성"
    if not m.member_active:
        return "그룹 구성원 아님(비활성)"
    if not m.assignable:
        return "자동배정 대상 아님"
    if scenario_id not in m.scenario_ids:
        return "해당 세부 분류 처리 불가"
    if require_jira_account and not (m.jira_account_id or "").strip():
        return "Jira 계정 없음"
    return None


def pick_assignee(
    members: Iterable[Member],
    scenario_id: str | None,
    *,
    require_jira_account: bool = True,
    exclude_user_ids: Iterable[int] = (),
) -> AssignDecision:
    """후보를 걸러내고(2.3) 1명을 고른다(2.4).

    - require_jira_account: `docs/api/03` TK-09가 자동배정에도 "유효한 Jira 계정"을 요구하므로 기본값은 True.
    - exclude_user_ids: 부재자 등 호출하는 쪽이 따로 빼고 싶은 사람. 부재자는 `time_off.absent_user_ids`로 만든다.
    - 선정 순서: 업무량 적은 순 → 마지막 배정이 오래된 순(배정 이력 없음이 가장 먼저) → 사번 순.
    - scenario_id 가 없으면(미분류) 개인 자동배정을 하지 않는다. 서비스데스크 확인으로 둔다.
    """
    members = list(members)
    if not scenario_id:
        return AssignDecision(False, reason="미분류는 개인 자동배정을 하지 않음(서비스데스크 확인)")

    skip = set(exclude_user_ids)
    excluded: dict[int, str] = {}
    candidates: list[Member] = []
    for m in members:
        why = "배정 제외 대상" if m.user_id in skip else _excluded_reason(m, scenario_id, require_jira_account)
        if why:
            excluded[m.user_id] = why
        else:
            candidates.append(m)

    if not candidates:
        return AssignDecision(False, reason="배정 가능한 후보 없음", excluded=excluded)

    def key(m: Member) -> tuple[int, float, str]:
        last = m.last_assigned_at.timestamp() if m.last_assigned_at else float("-inf")
        return (m.workload, last, m.employee_no)

    ordered = sorted(candidates, key=key)
    best = ordered[0]
    tied = [m for m in ordered if m.workload == best.workload]
    reason = f"업무량 최소 ({best.workload}건)"
    if len(tied) > 1:
        reason += f", 동률 {len(tied)}명 중 마지막 배정이 가장 오래된 순" if _has_distinct_last(tied) else f", 동률 {len(tied)}명 중 사번 순"
    return AssignDecision(
        True, user_id=best.user_id, reason=reason, workload=best.workload,
        excluded=excluded, candidate_ids=tuple(m.user_id for m in candidates),
    )


def _has_distinct_last(tied: list[Member]) -> bool:
    """동률자들의 마지막 배정 시각이 서로 달라서 그 기준으로 갈렸는지."""
    return len({m.last_assigned_at for m in tied}) > 1
