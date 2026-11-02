from datetime import date
from typing import Literal

from app.schemas.common import CamelModel, KstDatetime, PageQuery, sort_param, trimmed_str
from app.schemas.inquiry import UserRef

TimeOffType = Literal["ANNUAL", "HALF_AM", "HALF_PM"]


class TimeOff(CamelModel):
    id: int
    user_id: int
    user: UserRef
    time_off_type: str
    start_date: date
    end_date: date
    note: str | None
    created_by: UserRef | None
    created_at: KstDatetime


class TimeOffListQuery(PageQuery):
    sort: list[sort_param("startDate", "createdAt")] = ["startDate,desc"]
    user_id: int | None = None
    group_id: int | None = None
    date_from: date | None = None         # 이 기간과 겹치는 일정
    date_to: date | None = None


class TimeOffCreateRequest(CamelModel):
    user_id: int | None = None            # 없으면 본인
    time_off_type: TimeOffType
    start_date: date
    end_date: date
    note: trimmed_str(1, 500) | None = None


# 보낸 필드만 바꾼다. userId 는 모르는 필드라 NOT_ALLOWED 가 된다
class TimeOffUpdateRequest(CamelModel):
    time_off_type: TimeOffType = None
    start_date: date = None
    end_date: date = None
    note: trimmed_str(1, 500) | None = None
