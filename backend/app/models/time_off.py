from datetime import date, datetime

from sqlalchemy import CheckConstraint, ForeignKey, Identity, Index, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TimeOff(Base):
    """연차·반차 일정. 사람 단위로 한 번만 등록하며 소속 그룹이 여러 개여도 같은 일정을 쓴다."""

    __tablename__ = "time_off"
    __table_args__ = (
        CheckConstraint("time_off_type in ('ANNUAL', 'HALF_AM', 'HALF_PM')", name="time_off_type"),
        CheckConstraint("end_date >= start_date", name="date_order"),
        CheckConstraint("time_off_type = 'ANNUAL' or start_date = end_date", name="half_day_single_date"),
        Index("ix_time_off_user_dates", "user_id", "start_date", "end_date"),
        # 시드를 다시 실행해도 같은 일정이 늘지 않는다. 기간 겹침은 서비스가 검사한다
        UniqueConstraint("user_id", "time_off_type", "start_date", name="uq_time_off_user_type_start"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    time_off_type: Mapped[str]        # ANNUAL(연차) / HALF_AM(오전 반차) / HALF_PM(오후 반차)
    start_date: Mapped[date]
    end_date: Mapped[date]            # 종료일 포함
    note: Mapped[str | None]
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
