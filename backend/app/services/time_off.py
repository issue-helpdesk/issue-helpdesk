"""연차·반차 일정 (TO-01~04)과 지금 부재인 사람 계산. 권한: 본인, ADMIN, 팀장(자기 그룹 구성원). 기준은 docs/11 3.1."""
from datetime import date, datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.error_codes import ErrorCode
from app.core.errors import AppError, field_error
from app.db.session import DbSession
from app.integrations.jira import TimeOff as TimeOffEntry, absent_user_ids
from app.models import TimeOff, User
from app.repositories.time_off import TimeOffRepository, TimeOffRepositoryDep
from app.schemas.common import Page, parse_sort
from app.schemas.inquiry import UserRef
from app.schemas.time_off import (
    TimeOff as TimeOffView,
    TimeOffCreateRequest,
    TimeOffListQuery,
    TimeOffUpdateRequest,
)
from app.utils import datetime_utils


def current_absentees(db: Session, now: datetime | None = None) -> frozenset[int]:
    """지금 부재인 user_id. 자동배정과 RF-04 onLeave 가 같이 쓴다. 반차 기준 시각은 회사 현지 시각(KST)이다."""
    local = datetime_utils.to_kst(now or datetime_utils.now())
    rows = TimeOffRepository(db).on_date(local.date())
    return absent_user_ids(
        [TimeOffEntry(r.user_id, r.time_off_type, r.start_date, r.end_date) for r in rows], local,
    )


class TimeOffService:
    def __init__(self, db: DbSession, time_off: TimeOffRepositoryDep) -> None:
        self.db = db
        self.time_off = time_off

    def list_time_off(self, query: TimeOffListQuery, viewer: User) -> Page[TimeOffView]:
        """TO-01. ADMIN 은 전체, 그 외에는 본인과 자기 그룹 구성원의 일정."""
        if query.date_from and query.date_to and query.date_from > query.date_to:
            raise AppError(ErrorCode.INVALID_REQUEST)
        is_admin = viewer.service_role == "ADMIN"
        managed_groups = set() if is_admin else self.time_off.managed_group_ids(viewer.id)
        visible = None if is_admin else {viewer.id} | self.time_off.group_member_ids(managed_groups)
        if (query.group_id is not None and not is_admin and query.group_id not in managed_groups
                or query.user_id is not None and visible is not None and query.user_id not in visible):
            raise AppError(ErrorCode.FORBIDDEN)

        user_ids = visible
        if query.group_id is not None:
            user_ids = self.time_off.group_member_ids({query.group_id})
        if query.user_id is not None:
            user_ids = {query.user_id} if user_ids is None or query.user_id in user_ids else set()

        rows, total = self.time_off.search(user_ids, query.date_from, query.date_to, parse_sort(query.sort),
                                           query.offset, query.size)
        return Page.of([to_view(*row) for row in rows], query.page, query.size, total)

    def create(self, body: TimeOffCreateRequest, user: User) -> TimeOffView:
        """TO-02. userId 가 없으면 본인 일정."""
        owner_id = body.user_id if body.user_id is not None else user.id
        if not self.can_manage(owner_id, user):
            raise AppError(ErrorCode.FORBIDDEN)
        if self.time_off.lock_user(owner_id) is None:
            raise field_error(ErrorCode.VALIDATION_ERROR, "userId", "NOT_FOUND", "존재하지 않는 사용자입니다.")
        check_dates(body.time_off_type, body.start_date, body.end_date)
        self.check_overlap(owner_id, body.time_off_type, body.start_date, body.end_date)
        row = self.time_off.add(TimeOff(user_id=owner_id, time_off_type=body.time_off_type, start_date=body.start_date,
                                        end_date=body.end_date, note=body.note, created_by=user.id))
        self.db.commit()
        return self.view(row)

    def update(self, time_off_id: int, body: TimeOffUpdateRequest, user: User) -> TimeOffView:
        """TO-03. 보낸 필드만 바꾸고, 바뀐 뒤의 값으로 날짜와 겹침을 검사한다."""
        row = self.time_off.get(time_off_id)
        if row is None or not self.can_manage(row.user_id, user):
            raise AppError(ErrorCode.TIME_OFF_NOT_FOUND)
        self.time_off.lock_user(row.user_id)
        row = self.time_off.get_for_update(time_off_id)
        sent = body.model_fields_set
        kind = body.time_off_type if "time_off_type" in sent else row.time_off_type
        start = body.start_date if "start_date" in sent else row.start_date
        end = body.end_date if "end_date" in sent else row.end_date
        check_dates(kind, start, end)
        self.check_overlap(row.user_id, kind, start, end, exclude_id=row.id)
        for name in sent:
            setattr(row, name, getattr(body, name))
        self.db.commit()
        return self.view(row)

    def delete(self, time_off_id: int, user: User) -> None:
        """TO-04."""
        row = self.time_off.get_for_update(time_off_id)
        if row is None or not self.can_manage(row.user_id, user):
            raise AppError(ErrorCode.TIME_OFF_NOT_FOUND)
        self.time_off.delete(row)
        self.db.commit()

    def can_manage(self, owner_id: int, user: User) -> bool:
        if user.service_role == "ADMIN" or owner_id == user.id:
            return True
        return owner_id in self.time_off.group_member_ids(self.time_off.managed_group_ids(user.id))

    def check_overlap(self, user_id: int, kind: str, start: date, end: date, exclude_id: int | None = None) -> None:
        for other in self.time_off.overlapping(user_id, start, end, exclude_id):
            if {kind, other.time_off_type} != {"HALF_AM", "HALF_PM"}:         # 같은 날 오전·오후 반차만 함께 쓸 수 있다
                raise AppError(ErrorCode.TIME_OFF_OVERLAP, [
                    {"reason": "TIME_OFF_ID", "message": "겹치는 일정", "value": other.id},
                ])

    def view(self, row: TimeOff) -> TimeOffView:
        return to_view(row, self.time_off.user(row.user_id), self.time_off.user(row.created_by))


TimeOffServiceDep = Annotated[TimeOffService, Depends(TimeOffService)]


def check_dates(kind: str, start: date, end: date) -> None:
    if end < start:
        raise field_error(ErrorCode.VALIDATION_ERROR, "endDate", "INVALID_VALUE", "종료일은 시작일보다 빠를 수 없습니다.")
    if kind != "ANNUAL" and start != end:
        raise field_error(ErrorCode.VALIDATION_ERROR, "endDate", "INVALID_VALUE", "반차는 시작일과 종료일이 같아야 합니다.")


def to_view(row: TimeOff, owner: User, creator: User | None) -> TimeOffView:
    return TimeOffView(
        id=row.id,
        user_id=row.user_id,
        user=UserRef.model_validate(owner),
        time_off_type=row.time_off_type,
        start_date=row.start_date,
        end_date=row.end_date,
        note=row.note,
        created_by=UserRef.model_validate(creator) if creator else None,
        created_at=row.created_at,
    )
