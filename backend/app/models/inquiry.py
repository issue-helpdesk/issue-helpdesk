from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Identity, Index, Integer, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

URGENCY = "urgency in ('P1', 'P2', 'P3', 'P4')"
ACTION = "action in ('ANSWER', 'ASK_MORE', 'ESCALATE', 'OUT_OF_SCOPE')"


class Inquiry(Base):
    __tablename__ = "inquiries"
    __table_args__ = (
        CheckConstraint("status in ('IN_PROGRESS', 'AI_RESOLVED', 'UNCONFIRMED', 'CLOSED_UNRESOLVED', "
                        "'RECEIVED', 'HANDED_OFF')", name="status"),
        CheckConstraint(URGENCY, name="urgency"),
        CheckConstraint(ACTION, name="action"),
        CheckConstraint("resolution_result in ('RESOLVED', 'UNRESOLVED', 'NO_RESPONSE')", name="resolution_result"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str | None]
    status: Mapped[str]
    category_code: Mapped[str | None] = mapped_column(ForeignKey("categories.code"))
    inquiry_type_id: Mapped[int | None] = mapped_column(ForeignKey("inquiry_types.id"))
    urgency: Mapped[str | None]
    action: Mapped[str | None]
    recommended_group_id: Mapped[int | None] = mapped_column(ForeignKey("support_groups.id"))
    resolution_result: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime | None]
    closed_at: Mapped[datetime | None]


class InquiryAssessment(Base):
    __tablename__ = "inquiry_assessments"
    __table_args__ = (
        CheckConstraint(URGENCY, name="urgency"),
        CheckConstraint(ACTION, name="action"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    inquiry_id: Mapped[int] = mapped_column(ForeignKey("inquiries.id"), index=True)
    facts: Mapped[dict | None] = mapped_column(JSONB)
    missing_items: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    urgent_signal: Mapped[bool] = mapped_column(server_default=text("false"))
    category_code: Mapped[str | None] = mapped_column(ForeignKey("categories.code"))
    inquiry_type_id: Mapped[int | None] = mapped_column(ForeignKey("inquiry_types.id"))
    urgency: Mapped[str | None]
    urgency_reason: Mapped[str | None]
    action: Mapped[str | None]
    ai_output: Mapped[dict | None] = mapped_column(JSONB)                          # AI 원래 판단
    override_reasons: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (
        CheckConstraint("end_reason in ('USER_END', 'NO_RESPONSE', 'HANDED_OFF')", name="end_reason"),
        # 문의당 열린 세션은 하나 (06 v0.8)
        Index("uq_chat_sessions_one_open", "inquiry_id", unique=True,
              postgresql_where=text("ended_at is null"), sqlite_where=text("ended_at is null")),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    inquiry_id: Mapped[int] = mapped_column(ForeignKey("inquiries.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    ended_at: Mapped[datetime | None]
    end_reason: Mapped[str | None]


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("session_id", "seq", name="uq_messages_session_id_seq"),
        CheckConstraint("sender in ('USER', 'AI', 'SYSTEM')", name="sender"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id"))
    seq: Mapped[int] = mapped_column(Integer)
    sender: Mapped[str]
    content: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class MessageSource(Base):
    __tablename__ = "message_sources"
    __table_args__ = (
        CheckConstraint("source_kind in ('DOCUMENT', 'LEGACY')", name="source_kind"),
        CheckConstraint(
            "(source_kind = 'DOCUMENT' and legacy_inquiry_id is null and doc_code is not null and version is not null)"
            " or (source_kind = 'LEGACY' and chunk_id is null and legacy_inquiry_id is not null)",
            name="source_ref"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), index=True)
    source_kind: Mapped[str]
    chunk_id: Mapped[int | None] = mapped_column(ForeignKey("document_chunks.id", ondelete="SET NULL"))
    legacy_inquiry_id: Mapped[int | None] = mapped_column(ForeignKey("legacy_inquiries.id"))
    doc_code: Mapped[str | None]          # 아래 4개는 답변 당시 출처 스냅샷
    version: Mapped[str | None]
    location: Mapped[str | None]
    excerpt: Mapped[str | None]
    rank: Mapped[int | None] = mapped_column(Integer)