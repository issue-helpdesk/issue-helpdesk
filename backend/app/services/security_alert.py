"""보안·감사 알림 (06 security_alerts, AUDIT-01·03·04).

- detect                : 원천 사건(audit_logs)을 남기는 곳에서 같은 트랜잭션으로 부른다. 커밋은 호출자가 한다
- SecurityAlertService  : 관리자 화면. 목록·집계·확인 시작·종결·원문 열람 (docs/api/05 SA-01~06)
"""
from typing import Annotated

from fastapi import Depends
from sqlalchemy import case, func, select

from app.agent.sensitive import mask_secrets
from app.constants.security import SECURITY_RULES
from app.constants.security_alert import FIXED_SEVERITY, MEDIUM_SENSITIVE_TYPES, SEVERITY_RANK
from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.db.session import DbSession
from app.models import AuditLog, ChatSession, Department, Message, SecurityAlert, User
from app.repositories.security_alert import SecurityAlertRepository
from app.schemas.common import Page
from app.schemas.inquiry import UserRef
from app.schemas.security_alert import (SecurityAlertView, SecurityCounts, SecurityHistory, SecurityMessage,
                                       SecurityOriginal, SecurityQuery)
from app.utils import datetime_utils
from app.utils.dict_utils import add_counts


class SecurityAlertService:
    def __init__(self, db: DbSession):
        self.db = db

    def find(self, alert_id: int, lock=False) -> SecurityAlert:
        q = select(SecurityAlert).where(SecurityAlert.id == alert_id)
        row = self.db.scalar(q.with_for_update() if lock else q)
        if row is None:
            raise AppError(ErrorCode.SECURITY_ALERT_NOT_FOUND)
        return row

    def counts(self) -> SecurityCounts:
        counts = dict(self.db.execute(select(SecurityAlert.status, func.count()).group_by(SecurityAlert.status)).all())
        high = self.db.scalar(select(func.count()).select_from(SecurityAlert).where(
            SecurityAlert.status != 'CLOSED', SecurityAlert.severity == 'HIGH'))
        return SecurityCounts(new=counts.get('NEW', 0), in_review=counts.get('IN_REVIEW', 0),
                              closed=counts.get('CLOSED', 0), open_high=high, total=sum(counts.values()))

    def list(self, query: SecurityQuery) -> Page[SecurityAlertView]:
        where = []
        if query.status:
            where.append(SecurityAlert.status == query.status)
        if query.alert_type:
            where.append(SecurityAlert.alert_type == query.alert_type)
        total = self.db.scalar(select(func.count()).select_from(SecurityAlert).where(*where))
        status_rank = case({'NEW': 0, 'IN_REVIEW': 1, 'CLOSED': 2}, value=SecurityAlert.status)
        severity_rank = case({'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}, value=SecurityAlert.severity)
        rows = self.db.scalars(select(SecurityAlert).where(*where).order_by(status_rank, severity_rank,
            SecurityAlert.first_detected_at.desc(), SecurityAlert.id.desc()).offset(query.offset).limit(query.size))
        return Page.of([self.view(r, history=False) for r in rows], query.page, query.size, total)

    def user_ref(self, user_id: int | None) -> UserRef | None:
        row = self.db.get(User, user_id) if user_id else None
        return UserRef.model_validate(row) if row else None

    def view(self, row: SecurityAlert, history=True) -> SecurityAlertView:
        user = self.db.get(User, row.subject_user_id)
        dept = self.db.get(Department, user.department_id) if user.department_id else None
        logs = []
        if history:
            records = self.db.scalars(select(AuditLog).where(AuditLog.target_type == 'security_alert',
                AuditLog.target_id == row.id).order_by(AuditLog.id.desc()).limit(100))
            logs = [SecurityHistory(kind=h.result or h.event_type, actor=self.user_ref(h.actor_id),
                                    reason=h.reason, created_at=h.created_at) for h in records]
            logs.append(SecurityHistory(kind='DETECTED', actor=None, reason=None, created_at=row.first_detected_at))
        label, _, explanation = SECURITY_RULES[row.alert_type]
        return SecurityAlertView(id=row.id, alert_type=row.alert_type, severity=row.severity, status=row.status,
            subject=UserRef.model_validate(user), subject_department_name=dept.name if dept else None,
            target_type=row.target_type, target_id=row.target_id,
            summary=f'{explanation} · 누적 {row.occurrence_count}회', rule=label, detail=row.detail,
            occurrence_count=row.occurrence_count, first_detected_at=row.first_detected_at,
            last_detected_at=row.last_detected_at, has_original=row.target_type == 'inquiry',
            reviewer=self.user_ref(row.reviewer_id), review_started_at=row.review_started_at,
            closed_by=self.user_ref(row.closed_by), closed_at=row.closed_at, close_reason=row.close_reason, history=logs)

    def log(self, row: SecurityAlert, actor: User, kind: str, reason: str | None = None):
        safe_reason = mask_secrets(reason).text if reason else None
        event = {'REVIEW': 'SECURITY_ALERT_REVIEW', 'CLOSE': 'SECURITY_ALERT_CLOSE',
                 'VIEW_ORIGINAL': 'SECURITY_ALERT_VIEW'}[kind]
        self.db.add(AuditLog(event_type=event, target_type='security_alert', target_id=row.id,
                            actor_id=actor.id, result=kind, reason=safe_reason))

    def start(self, alert_id: int, actor: User) -> SecurityAlertView:
        row = self.find(alert_id, lock=True)
        if row.status != 'NEW':
            raise AppError(ErrorCode.SECURITY_ALERT_INVALID_STATE)
        row.status, row.reviewer_id, row.review_started_at = 'IN_REVIEW', actor.id, datetime_utils.now()
        self.log(row, actor, 'REVIEW')
        self.db.commit()
        return self.view(row)

    def close(self, alert_id: int, actor: User, reason: str) -> SecurityAlertView:
        row = self.find(alert_id, lock=True)
        if row.status != 'IN_REVIEW':
            raise AppError(ErrorCode.SECURITY_ALERT_INVALID_STATE)
        row.status, row.closed_by, row.closed_at = 'CLOSED', actor.id, datetime_utils.now()
        row.close_reason = mask_secrets(reason).text
        self.log(row, actor, 'CLOSE', reason)
        self.db.commit()
        return self.view(row)

    def context(self, alert_id: int, actor: User, reason: str) -> SecurityOriginal:
        row = self.find(alert_id, lock=True)
        if row.target_type != 'inquiry':
            raise AppError(ErrorCode.SECURITY_ALERT_NO_ORIGINAL)
        # 비밀값은 저장 전에 가렸지만, 돌려주기 전에 한 번 더 가린다
        records = self.db.scalars(select(Message).join(ChatSession, Message.session_id == ChatSession.id)
            .where(ChatSession.inquiry_id == row.target_id, Message.sender == 'USER',
                   Message.kind == 'TEXT', Message.content.is_not(None)).order_by(Message.id))
        messages = [SecurityMessage(id=m.id, content=mask_secrets(m.content).text, created_at=m.created_at)
                    for m in records]
        self.log(row, actor, 'VIEW_ORIGINAL', reason)
        self.db.commit()  # 열람 기록이 커밋돼야만 원문을 돌려준다 (실패하면 원문도 나가지 않는다)
        return SecurityOriginal(messages=messages)


SecurityAlertServiceDep = Annotated[SecurityAlertService, Depends(SecurityAlertService)]


def severity_of(alert_type: str, detail: dict[str, int]) -> str:
    """감지 유형 표의 심각도. SENSITIVE_INPUT 은 OTP 만 가렸으면 MEDIUM, 그 밖은 HIGH."""
    if alert_type == "SENSITIVE_INPUT":
        return "MEDIUM" if set(detail) <= MEDIUM_SENSITIVE_TYPES else "HIGH"
    return FIXED_SEVERITY[alert_type]


def detect(
    alerts: SecurityAlertRepository,
    alert_type: str,
    subject_user_id: int,
    target_type: str,
    target_id: int,
    detail: dict[str, int] | None = None,
) -> SecurityAlert:
    """알림을 만들거나, 같은 대상의 종결 전 알림에 합친다.

    detail 은 유형별 개수만 받는다 (값·원문 금지). 합칠 때 개수를 더하고, 횟수·마지막 감지 시각을 올리고,
    심각도는 올리기만 한다. 종결된 알림에는 합치지 않으므로 다시 감지되면 새 알림이 생긴다.
    """
    detail = dict(detail or {})
    key = (alert_type, subject_user_id, target_type, target_id)
    now = datetime_utils.now()

    alert = alerts.open_for_update(*key)
    if alert is None:
        alert = SecurityAlert(
            alert_type=alert_type, severity=severity_of(alert_type, detail), status="NEW",
            subject_user_id=subject_user_id, target_type=target_type, target_id=target_id,
            detail=detail, occurrence_count=1, first_detected_at=now, last_detected_at=now,
        )
        if alerts.add_open(alert):
            return alert
        # 다른 요청이 같은 대상의 알림을 먼저 만들었다. 그 알림에 합친다
        alert = alerts.open_for_update(*key)

    alert.occurrence_count += 1
    alert.last_detected_at = now
    alert.detail = add_counts(alert.detail, detail)     # 새 dict 를 넣어야 JSONB 변경이 저장된다
    severity = severity_of(alert_type, alert.detail)
    if SEVERITY_RANK[severity] > SEVERITY_RANK[alert.severity]:
        alert.severity = severity
    return alert
