from datetime import date
from typing import Annotated

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from app.db.session import DbSession
from app.models import SupportGroup, SupportGroupMember, TimeOff, User

Creator = aliased(User)
SORT_COLUMNS = {
    "startDate": TimeOff.start_date,
    "createdAt": TimeOff.created_at,
}


class TimeOffRepository:
    def __init__(self, db: DbSession) -> None:
        self.db = db

    def add(self, row: TimeOff) -> TimeOff:
        self.db.add(row)
        self.db.flush()
        return row

    def delete(self, row: TimeOff) -> None:
        self.db.delete(row)

    def get(self, time_off_id: int) -> TimeOff | None:
        return self.db.get(TimeOff, time_off_id)

    def get_for_update(self, time_off_id: int) -> TimeOff | None:
        return self.db.get(TimeOff, time_off_id, with_for_update=True, populate_existing=True)

    def user(self, user_id: int | None) -> User | None:
        return self.db.get(User, user_id) if user_id is not None else None

    def lock_user(self, user_id: int) -> User | None:
        """한 사람의 일정 등록·수정을 줄 세운다. 동시에 들어온 두 요청이 겹침 검사를 함께 통과하지 못하게 한다."""
        return self.db.get(User, user_id, with_for_update=True)

    def overlapping(self, user_id: int, start: date, end: date, exclude_id: int | None = None) -> list[TimeOff]:
        query = select(TimeOff).where(TimeOff.user_id == user_id, TimeOff.start_date <= end, TimeOff.end_date >= start)
        if exclude_id is not None:
            query = query.where(TimeOff.id != exclude_id)
        return list(self.db.scalars(query.order_by(TimeOff.start_date, TimeOff.id)))

    def on_date(self, day: date) -> list[TimeOff]:
        return list(self.db.scalars(select(TimeOff).where(TimeOff.start_date <= day, TimeOff.end_date >= day)))

    def managed_group_ids(self, manager_id: int) -> set[int]:
        """이 사람이 활성 MANAGER 인 활성 그룹."""
        return set(self.db.scalars(
            select(SupportGroupMember.group_id)
            .join(SupportGroup, SupportGroup.id == SupportGroupMember.group_id)
            .where(SupportGroupMember.user_id == manager_id, SupportGroupMember.member_role == "MANAGER",
                   SupportGroupMember.is_active.is_(True), SupportGroup.is_active.is_(True))
        ))

    def group_member_ids(self, group_ids: set[int]) -> set[int]:
        if not group_ids:
            return set()
        return set(self.db.scalars(
            select(SupportGroupMember.user_id)
            .where(SupportGroupMember.group_id.in_(group_ids), SupportGroupMember.is_active.is_(True))
        ))

    def search(
        self,
        user_ids: set[int] | None,
        date_from: date | None,
        date_to: date | None,
        sort: list[tuple[str, bool]],
        offset: int,
        limit: int,
    ) -> tuple[list[tuple[TimeOff, User, User | None]], int]:
        """user_ids: 이 사람들의 일정만. None 이면 전체."""
        conditions = []
        if user_ids is not None:
            conditions.append(TimeOff.user_id.in_(user_ids))
        if date_from is not None:
            conditions.append(TimeOff.end_date >= date_from)
        if date_to is not None:
            conditions.append(TimeOff.start_date <= date_to)

        total = self.db.scalar(select(func.count()).select_from(select(TimeOff.id).where(*conditions).subquery()))
        order_by = [SORT_COLUMNS[f].desc() if desc else SORT_COLUMNS[f].asc() for f, desc in sort]
        rows = self.db.execute(
            select(TimeOff, User, Creator)
            .join(User, User.id == TimeOff.user_id)
            .outerjoin(Creator, Creator.id == TimeOff.created_by)
            .where(*conditions)
            .order_by(*order_by, TimeOff.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return [tuple(row) for row in rows], total


TimeOffRepositoryDep = Annotated[TimeOffRepository, Depends(TimeOffRepository)]
