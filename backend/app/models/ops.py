from datetime import datetime

from sqlalchemy import ForeignKey, Identity, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    event_type: Mapped[str]
    target_type: Mapped[str | None]
    target_id: Mapped[int | None]
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))       # NULL이면 시스템
    result: Mapped[str | None]
    reason: Mapped[str | None]                   # 원문은 저장하지 않음
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)


class LlmCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    inquiry_id: Mapped[int | None] = mapped_column(ForeignKey("inquiries.id"), index=True)
    purpose: Mapped[str]
    model: Mapped[str]
    adapter: Mapped[str]
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    success: Mapped[bool]
    error_code: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())