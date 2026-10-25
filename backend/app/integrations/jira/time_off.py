"""오늘(지금) 부재인 사람 목록 만들기 — 연차·반차 일정에서 `exclude_user_ids` 를 만든다 (`docs/11` 3.1).

DB도 네트워크도 쓰지 않는 순수 함수다. `time_off` 표의 행을 읽어 `TimeOff` 로 넘기면 된다.

    absent = absent_user_ids(entries, now)
    decision = pick_assignee(members, "NET-01", exclude_user_ids=absent)

규칙 (점심시간 기준 시각 `half_day_cutoff` 기본값은 13:00, 회사 규정에 맞춰 바꿀 수 있다)
- ANNUAL(연차): 시작일~종료일 사이의 날에는 종일 부재.
- HALF_AM(오전 반차): 그날 `half_day_cutoff` 전까지만 부재.
- HALF_PM(오후 반차): 그날 `half_day_cutoff` 이후부터 부재.
`now` 는 회사 현지 시각이다 (시간대 변환은 호출하는 쪽에서 한다).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Iterable

ANNUAL = "ANNUAL"
HALF_AM = "HALF_AM"
HALF_PM = "HALF_PM"
DEFAULT_HALF_DAY_CUTOFF = time(13, 0)


@dataclass(frozen=True)
class TimeOff:
    """`time_off` 표의 한 행 (연차·반차 일정)."""

    user_id: int
    time_off_type: str          # ANNUAL / HALF_AM / HALF_PM
    start_date: date
    end_date: date


def is_absent(entry: TimeOff, now: datetime, half_day_cutoff: time = DEFAULT_HALF_DAY_CUTOFF) -> bool:
    today = now.date()
    if not (entry.start_date <= today <= entry.end_date):
        return False
    if entry.time_off_type == ANNUAL:
        return True
    if entry.time_off_type == HALF_AM:
        return now.time() < half_day_cutoff
    if entry.time_off_type == HALF_PM:
        return now.time() >= half_day_cutoff
    raise ValueError(f"알 수 없는 time_off_type: {entry.time_off_type!r}")


def absent_user_ids(entries: Iterable[TimeOff], now: datetime, half_day_cutoff: time = DEFAULT_HALF_DAY_CUTOFF) -> frozenset[int]:
    """지금 부재인 user_id 집합. `pick_assignee(exclude_user_ids=...)` 에 그대로 넘긴다."""
    return frozenset(e.user_id for e in entries if is_absent(e, now, half_day_cutoff))
