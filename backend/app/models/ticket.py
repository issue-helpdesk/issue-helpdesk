from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Identity, Index, Integer, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.inquiry import URGENCY


class TicketDraft(Base):
    __tablename__ = "ticket_drafts"
    __table_args__ = (
        CheckConstraint(URGENCY, name="urgency"),
        CheckConstraint("status in ('EDITING', 'CONFIRMED', 'CANCELLED')", name="status"),
        # 문의당 작성 중 초안은 하나 (06 v0.8)
        Index("uq_ticket_drafts_one_editing", "inquiry_id", unique=True,
              postgresql_where=text("status = 'EDITING'"), sqlite_where=text("status = 'EDITING'")),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    inquiry_id: Mapped[int] = mapped_column(ForeignKey("inquiries.id"), index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id"))
    summary: Mapped[str | None]
    target_system: Mapped[str | None]
    symptom: Mapped[str | None]
    occurred_at: Mapped[str | None]              # 사용자 표현 그대로 (날짜 아님)
    category_code: Mapped[str | None] = mapped_column(ForeignKey("categories.code"))
    inquiry_type_id: Mapped[int | None] = mapped_column(ForeignKey("inquiry_types.id"))
    urgency: Mapped[str | None]
    urgency_reason: Mapped[str | None]
    business_impact: Mapped[str | None]
    tried_actions: Mapped[str | None]
    recommended_group_id: Mapped[int | None] = mapped_column(ForeignKey("support_groups.id"))
    status: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime | None]


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint(URGENCY, name="urgency"),
        CheckConstraint("jira_sync_status in ('PENDING', 'VERIFYING', 'SYNCED', 'NEEDS_ADMIN')",
                        name="jira_sync_status"),
        CheckConstraint("assign_status in ('PENDING', 'ASSIGNED', 'NEEDS_ADMIN')", name="assign_status"),
        CheckConstraint("work_status in ('RDY', 'WIP', 'FIN', 'CLS')", name="work_status"),
        CheckConstraint("requested_work_status in ('RDY', 'WIP', 'FIN', 'CLS')", name="requested_work_status"),
        CheckConstraint("transition_status in ('IDLE', 'PENDING', 'NEEDS_ADMIN')", name="transition_status"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    receipt_no: Mapped[str] = mapped_column(unique=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("ticket_drafts.id"), unique=True)
    inquiry_id: Mapped[int] = mapped_column(ForeignKey("inquiries.id"), unique=True)     # 문의당 접수 하나 (06 v0.8)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id"))
    summary: Mapped[str]                         # 아래는 확정 시점 스냅샷
    target_system: Mapped[str | None]
    symptom: Mapped[str | None]
    occurred_at: Mapped[str | None]
    category_code: Mapped[str | None] = mapped_column(ForeignKey("categories.code"))
    inquiry_type_id: Mapped[int | None] = mapped_column(ForeignKey("inquiry_types.id"))
    urgency: Mapped[str | None]
    urgency_reason: Mapped[str | None]
    business_impact: Mapped[str | None]
    tried_actions: Mapped[str | None]
    group_id: Mapped[int | None] = mapped_column(ForeignKey("support_groups.id"))
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    jira_key: Mapped[str | None] = mapped_column(unique=True)
    jira_sync_status: Mapped[str]
    assign_status: Mapped[str]
    work_status: Mapped[str | None]
    # 업무 상태 변경 요청 (TK-07, 06 v0.8). 확인된 상태는 work_status, 요청한 목표는 requested_work_status
    requested_work_status: Mapped[str | None]
    transition_status: Mapped[str] = mapped_column(server_default=text("'IDLE'"))
    work_status_confirmed_at: Mapped[datetime | None]      # Jira 최신 조회로 마지막 확인한 시각
    resolution_confirmed_at: Mapped[datetime | None]       # 문의자가 해결 확인을 요청한 시각
    assignment_revision: Mapped[int] = mapped_column(server_default=text("0"))   # 재배정마다 증가
    resolution_note: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None]
    closed_at: Mapped[datetime | None]


class TicketStatusHistory(Base):
    __tablename__ = "ticket_status_history"
    __table_args__ = (
        CheckConstraint("source in ('JIRA', 'ITSSUE')", name="source"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    from_status: Mapped[str | None]
    to_status: Mapped[str]
    source: Mapped[str]
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str | None]
    changed_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AssignmentLog(Base):
    __tablename__ = "assignment_logs"
    __table_args__ = (
        CheckConstraint("event in ('RECOMMEND', 'ASSIGN', 'FAIL', 'REASSIGN')", name="event"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    event: Mapped[str]
    group_id: Mapped[int | None] = mapped_column(ForeignKey("support_groups.id"))
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("routing_rules.id"))
    reason: Mapped[str | None]
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))       # NULL이면 시스템
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


ACTIVE_JOB = "status in ('PENDING', 'RUNNING') and job_type in ('JIRA_ASSIGN', 'JIRA_TRANSITION')"


class IntegrationJob(Base):
    __tablename__ = "integration_jobs"
    __table_args__ = (
        CheckConstraint("job_type in ('JIRA_CREATE', 'JIRA_ASSIGN', 'JIRA_TRANSITION')", name="job_type"),
        CheckConstraint("status in ('PENDING', 'RUNNING', 'DONE', 'FAILED', 'NEEDS_ADMIN')", name="status"),
        # 배정·상태 변경은 접수·종류별 진행 중 작업을 하나로 제한한다 (06 v0.8)
        Index("uq_integration_jobs_one_active", "ticket_id", "job_type", unique=True,
              postgresql_where=text(ACTIVE_JOB), sqlite_where=text(ACTIVE_JOB)),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    job_type: Mapped[str]
    status: Mapped[str]
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    next_retry_at: Mapped[datetime | None]
    last_error: Mapped[str | None]
    idempotency_key: Mapped[str] = mapped_column(unique=True)
    payload: Mapped[dict] = mapped_column(JSONB)            # 등록 시점 입력. 실행 중 바꾸지 않는다
    retry_of_job_id: Mapped[int | None] = mapped_column(ForeignKey("integration_jobs.id"))   # 재처리한 원본 작업
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime | None]


class JiraWebhookEvent(Base):
    """Jira 웹훅 수신 기록 (TK-13, 06 v0.8). 먼저 저장하고 나중에 처리한다."""
    __tablename__ = "jira_webhook_events"
    __table_args__ = (
        CheckConstraint("status in ('PENDING', 'DONE', 'IGNORED', 'NEEDS_ADMIN')", name="status"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    event_key: Mapped[str] = mapped_column(unique=True)    # 이벤트 ID. 없으면 이슈 키·변경 이력 ID, 둘 다 없으면 본문 해시
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id"), index=True)   # 아직 연결 안 된 이슈면 NULL
    issue_key: Mapped[str]
    changed_at: Mapped[datetime | None]
    received_at: Mapped[datetime] = mapped_column(server_default=func.now())
    status: Mapped[str]


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("status in ('PENDING', 'SENT', 'FAILED')", name="status"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str]
    status: Mapped[str]
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    sent_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())