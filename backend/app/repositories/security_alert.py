"""원천 감사 사건과 같은 트랜잭션에서 알림 생성. 사용자 행 잠금으로 열린 알림을 합친다."""
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants.security import SECURITY_RULES, SEVERITY_RANK
from app.models import AuditLog, ChatSession, Inquiry, Message, SecurityAlert, User
from app.utils import datetime_utils


def record_security_event(db: Session, event: str, target_type: str, target_id: int,
                          result: str | None, actor_id: int | None) -> None:
    if event == 'SECURITY_REVIEW':
        rule = result
    elif event == 'BLOCK' and result == 'ALL_BLOCKED':
        rule = 'BLOCKED_DOC_QUERY'
    elif event == 'FAIL' and result == 'FILTER_FAILED':
        rule = result
    elif event in ('ACCOUNT_LOCKED', 'LOGIN_BLOCKED', 'URGENT_CLOSED', 'UNSAFE_REPLY'):
        rule = event
    else:
        return
    if rule not in SECURITY_RULES:
        return
    subject_id = target_id if target_type == 'user' else actor_id
    if target_type == 'inquiry':
        subject_id = db.scalar(select(Inquiry.user_id).where(Inquiry.id == target_id))
    if subject_id is None:
        return  # deleted/nonexistent targets cannot become an attributed alert
    emit(db, target_type, target_id, subject_id, rule)
    if event == 'SECURITY_REVIEW' and rule in ('S02', 'S03', 'S04', 'S05', 'S06'):
        # Catch the same risk across new chats too; the LLM only sees the current chat history.
        prior_ids = set(db.scalars(select(AuditLog.target_id).where(
            AuditLog.event_type == 'SECURITY_REVIEW', AuditLog.result == rule,
            AuditLog.target_type == 'inquiry',
            AuditLog.target_id.in_(select(Inquiry.id).where(Inquiry.user_id == subject_id)),
            AuditLog.created_at >= datetime_utils.now() - timedelta(minutes=10))))
        if len(prior_ids | {target_id}) >= 3:
            emit(db, 'user', subject_id, subject_id, 'S07')


def emit(db: Session, target_type: str, target_id: int, subject_id: int, rule: str,
         detail: dict | None = None, severity: str | None = None) -> SecurityAlert:
    # Lock order: subject user → open alert, also used by login. Rule/user IDs never come from model text.
    db.execute(select(User.id).where(User.id == subject_id).with_for_update())
    now = datetime_utils.now()
    row = db.scalar(select(SecurityAlert).where(SecurityAlert.target_type == target_type,
        SecurityAlert.target_id == target_id, SecurityAlert.subject_user_id == subject_id,
        SecurityAlert.alert_type == rule, SecurityAlert.status != 'CLOSED').with_for_update())
    level = severity or SECURITY_RULES[rule][1]
    if row is None:
        row = SecurityAlert(target_type=target_type, target_id=target_id, subject_user_id=subject_id,
            alert_type=rule, severity=level, status='NEW', detail=detail or {}, occurrence_count=1,
            first_detected_at=now, last_detected_at=now)
        db.add(row)
        db.flush()
    else:
        row.occurrence_count += 1
        row.last_detected_at = now
        if SEVERITY_RANK[level] > SEVERITY_RANK[row.severity]:
            row.severity = level
        if detail:
            row.detail = {k: row.detail.get(k, 0) + detail.get(k, 0) for k in row.detail.keys() | detail.keys()}
    return row


def record_sensitive_counts(db: Session, inquiry_id: int, actor_id: int, counts: dict[str, int]):
    if counts:
        # One message with multiple secret types produces one alert occurrence, not one per type.
        severity = 'HIGH' if set(counts) - {'OTP'} else 'MEDIUM'
        emit(db, 'inquiry', inquiry_id, actor_id, 'SENSITIVE_INPUT', counts, severity)


def record_query_volume(db: Session, actor_id: int):
    """Only saved USER messages; never count AI notices, page reloads, failed requests or raw secrets."""
    db.flush()
    since = datetime_utils.now() - timedelta(minutes=3)
    count = db.scalar(select(func.count()).select_from(Message).join(ChatSession,
        ChatSession.id == Message.session_id).join(Inquiry, Inquiry.id == ChatSession.inquiry_id)
        .where(Inquiry.user_id == actor_id, Message.sender == 'USER', Message.created_at >= since))
    if count >= 41:
        emit(db, 'user', actor_id, actor_id, 'MASS_QUERY')
