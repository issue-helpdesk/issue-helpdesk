from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Identity, Index, Integer, func, text
from sqlalchemy.dialects.postgresql import JSONB
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


OPEN_ALERT = "status <> 'CLOSED'"


class SecurityAlert(Base):
    """보안·감사 알림 (06 security_alerts, AUDIT-01~04). 처리 이력은 audit_logs(target_type=security_alert)에 남긴다."""
    __tablename__ = "security_alerts"
    __table_args__ = (
        CheckConstraint("alert_type in ('SENSITIVE_INPUT', 'BLOCKED_DOC_QUERY', 'ACCOUNT_LOCKED', 'LOGIN_BLOCKED', "
                        "'URGENT_CLOSED', 'MASS_QUERY')", name="alert_type"),
        CheckConstraint("severity in ('HIGH', 'MEDIUM', 'LOW')", name="severity"),
        CheckConstraint("status in ('NEW', 'IN_REVIEW', 'CLOSED')", name="status"),
        CheckConstraint("target_type in ('inquiry', 'user')", name="target_type"),
        CheckConstraint("occurrence_count >= 1", name="occurrence_count"),
        CheckConstraint("status = 'NEW' or (reviewer_id is not null and review_started_at is not null)",
                        name="review_ref"),
        CheckConstraint("status <> 'CLOSED' or (closed_by is not null and closed_at is not null "
                        "and close_reason is not null)", name="close_ref"),
        Index("ix_security_alerts_status", "status", text("first_detected_at desc")),
        # 같은 대상의 열린 알림은 하나로 합친다
        Index("uq_security_alerts_one_open", "alert_type", "subject_user_id", "target_type", "target_id", unique=True,
              postgresql_where=text(OPEN_ALERT), sqlite_where=text(OPEN_ALERT)),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    alert_type: Mapped[str]
    severity: Mapped[str]
    status: Mapped[str] = mapped_column(server_default=text("'NEW'"))
    subject_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))      # 신호를 일으킨 사람
    target_type: Mapped[str]                                                  # inquiry / user
    target_id: Mapped[int]
    # 값·원문은 넣지 않는다. 기본값은 PostgreSQL 이 '{}'::jsonb 로 저장한다 (SQLite 테스트도 만들 수 있게 캐스트 없이 씀)
    detail: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"))
    occurrence_count: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    first_detected_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_detected_at: Mapped[datetime] = mapped_column(server_default=func.now())
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    review_started_at: Mapped[datetime | None]
    closed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    closed_at: Mapped[datetime | None]
    close_reason: Mapped[str | None]
