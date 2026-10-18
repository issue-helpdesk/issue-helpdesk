from sqlalchemy import CheckConstraint, ForeignKey, Identity, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Category(Base):
    __tablename__ = "categories"

    code: Mapped[str] = mapped_column(primary_key=True)    # ACC, ACS, NET, SW, HW, SYS, SEC
    name: Mapped[str]
    description: Mapped[str | None]


class InquiryType(Base):
    __tablename__ = "inquiry_types"
    __table_args__ = (
        CheckConstraint("request_kind in ('INCIDENT', 'REQUEST', 'QUESTION')", name="request_kind"),
        CheckConstraint("default_urgency in ('P1', 'P2', 'P3', 'P4')", name="default_urgency"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(unique=True)          # ACC-01 등
    category_code: Mapped[str] = mapped_column(ForeignKey("categories.code"))
    name: Mapped[str]
    request_kind: Mapped[str]
    default_urgency: Mapped[str]
    default_group_id: Mapped[int] = mapped_column(ForeignKey("support_groups.id"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))