from sqlalchemy import CheckConstraint, ForeignKey, Identity, Integer, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SupportGroup(Base):
    __tablename__ = "support_groups"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    description: Mapped[str | None]
    is_triage: Mapped[bool] = mapped_column(server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class SupportGroupMember(Base):
    __tablename__ = "support_group_members"
    __table_args__ = (
        CheckConstraint("member_role in ('AGENT', 'MANAGER')", name="member_role"),
    )

    # 복합 PK (group_id, user_id)
    group_id: Mapped[int] = mapped_column(ForeignKey("support_groups.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    member_role: Mapped[str]
    assignable: Mapped[bool]
    jira_account_id: Mapped[str | None]
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class MemberSkill(Base):
    __tablename__ = "member_skills"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    inquiry_type_id: Mapped[int] = mapped_column(ForeignKey("inquiry_types.id"), primary_key=True)


class RoutingRule(Base):
    __tablename__ = "routing_rules"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    inquiry_type_id: Mapped[int] = mapped_column(ForeignKey("inquiry_types.id"))
    target_system: Mapped[str | None]
    group_id: Mapped[int] = mapped_column(ForeignKey("support_groups.id"))
    priority: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    description: Mapped[str | None]
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))