from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Identity, Integer, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    name: Mapped[str]
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("service_role in ('EMPLOYEE', 'AGENT', 'ADMIN')", name="service_role"),
        CheckConstraint("account_status in ('ACTIVE', 'LOCKED', 'INACTIVE')", name="account_status"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    employee_no: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    email: Mapped[str] = mapped_column(unique=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    position: Mapped[str | None]
    service_role: Mapped[str]
    account_status: Mapped[str]
    password_hash: Mapped[str]
    password_changed_at: Mapped[datetime | None]
    failed_login_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    locked_until: Mapped[datetime | None]
    last_login_at: Mapped[datetime | None]
    slack_user_id: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime | None]
