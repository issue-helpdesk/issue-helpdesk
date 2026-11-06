from typing import Annotated

from fastapi import Depends
from sqlalchemy import case, func, select

from app.agent.sensitive import mask_secrets
from app.constants.security import SECURITY_RULES
from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.db.session import DbSession
from app.models import AuditLog, ChatSession, Department, Message, SecurityAlert, User
from app.schemas.common import Page
from app.schemas.inquiry import UserRef
from app.schemas.security_alert import (SecurityAlertView, SecurityCounts, SecurityHistory, SecurityMessage,
                                       SecurityOriginal, SecurityQuery)
from app.utils import datetime_utils


class SecurityAlertService:
    def __init__(self, db: DbSession):
        self.db = db

    def find(self, alert_id: int, lock=False) -> SecurityAlert:
        q = select(SecurityAlert).where(SecurityAlert.id == alert_id)
        if lock:
            subject_id = self.db.scalar(select(SecurityAlert.subject_user_id).where(SecurityAlert.id == alert_id))
            if subject_id is not None:
                # Match event ingestion's user → alert lock order, including an admin reviewing their own alert.
                self.db.execute(select(User.id).where(User.id == subject_id).with_for_update())
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
        # Original credentials never existed in storage. Scan again before returning saved context.
        records = self.db.scalars(select(Message).join(ChatSession, Message.session_id == ChatSession.id)
            .where(ChatSession.inquiry_id == row.target_id, Message.sender == 'USER').order_by(Message.id))
        messages = [SecurityMessage(id=m.id, content=mask_secrets(m.content).text, created_at=m.created_at)
                    for m in records]
        self.log(row, actor, 'VIEW_ORIGINAL', reason)
        self.db.commit()  # fail closed: no context returned unless audit transaction commits
        return SecurityOriginal(messages=messages)


SecurityAlertServiceDep = Annotated[SecurityAlertService, Depends(SecurityAlertService)]
