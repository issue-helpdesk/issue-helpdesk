"""Jira 개인 담당자 배정 작업(JIRA_ASSIGN) 등록 — TK-09 배정·재배정을 연동 작업 큐에 넣는다.

payload 에 그룹·담당자·assignment_revision 을 남긴다. 실행기는 실행 시점의 tickets.assignment_revision 과
payload 의 값이 다르면 더 새 배정이 있는 것이므로 Jira 를 바꾸지 않는다 (06 연동 보완).

실행(Jira 담당자 변경 → 확인 → assign_status = ASSIGNED)은 아직 없다.
"""
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import IntegrationJob, Ticket

JOB_TYPE = "JIRA_ASSIGN"


def enqueue_jira_assign(db: Session, ticket: Ticket, payload: dict[str, Any]) -> IntegrationJob:
    """flush 만 한다. 커밋은 호출자가 한다. 접수당 진행 중 배정 작업은 하나다 (uq_integration_jobs_one_active)."""
    job = IntegrationJob(ticket_id=ticket.id, job_type=JOB_TYPE, status="PENDING", attempts=0,
                         idempotency_key=f"assign:{uuid.uuid4()}", payload=payload)
    db.add(job)
    db.flush()
    return job
