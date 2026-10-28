"""Jira 호출이 실패했을 때 다음에 무엇을 할지 정한다 (`docs/11` 2.5, 6.1의 1번).

client.py 는 자동 재시도를 하지 않고 JiraError 만 올린다. 이 함수는 연동 작업(integration_jobs)이
"이 오류를 받았을 때 다시 시도할지, 결과를 확인할지, 관리자에게 넘길지"를 한 곳에서 같은 기준으로 정하게 한다.
DB를 쓰지 않는 순수 함수이며, 시도 횟수와 경과 시간은 호출하는 쪽이 넘긴다.

⚠ RetryPolicy 의 숫자는 제안값이다. 팀에서 정하기 전까지 임시로 쓴다.
"""

from __future__ import annotations

from dataclasses import dataclass

from .client import JiraError


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3                                  # 재시도 가능한 오류의 최대 시도 횟수
    backoff_seconds: tuple[int, ...] = (60, 300, 900)      # n번째 실패 뒤 기다리는 시간. 넘치면 마지막 값
    verify_max_checks: int = 3                             # 결과 불명확(result_unknown) 재조회 최대 횟수
    verify_interval_seconds: int = 60
    verify_deadline_seconds: int = 900                     # 결과 불명확 상태가 이 시간을 넘으면 관리자 확인


@dataclass(frozen=True)
class NextStep:
    action: str                 # RETRY(같은 작업 다시 실행) · VERIFY(Jira에서 결과만 조회) · NEEDS_ADMIN(관리자 확인)
    delay_seconds: int = 0
    reason: str = ""


def next_step(error: JiraError, attempts: int, elapsed_seconds: float = 0, policy: RetryPolicy = RetryPolicy()) -> NextStep:
    """attempts = 지금까지 실행한 횟수(이번 실패 포함), elapsed_seconds = 첫 실패 뒤 흐른 시간."""
    if error.reason == "result_unknown":
        # 생성·배정이 됐는지 모르는 상태. 다시 만들지 않고 조회로만 확인하고, 예약은 유지한다.
        if attempts > policy.verify_max_checks or elapsed_seconds >= policy.verify_deadline_seconds:
            return NextStep("NEEDS_ADMIN", reason="결과 불명확 상태가 길어져 관리자 확인이 필요합니다.")
        return NextStep("VERIFY", policy.verify_interval_seconds, "결과 불명확: Jira에서 결과만 조회합니다.")

    if not error.retryable:
        return NextStep("NEEDS_ADMIN", reason=f"재시도해도 같은 결과입니다({error.reason}).")

    if attempts >= policy.max_attempts:
        return NextStep("NEEDS_ADMIN", reason=f"재시도 {policy.max_attempts}회를 넘었습니다({error.reason}).")
    index = min(max(attempts, 1), len(policy.backoff_seconds)) - 1
    return NextStep("RETRY", policy.backoff_seconds[index], f"{error.reason}: {attempts}회 실패, 다시 시도합니다.")
