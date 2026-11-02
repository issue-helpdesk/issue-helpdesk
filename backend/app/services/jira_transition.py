"""Jira 업무 상태 변경 작업(JIRA_TRANSITION) 등록 — TK-07 요청을 연동 작업 큐에 넣는다.

TK-07 은 Ticket 의 확인된 상태(work_status)를 바로 바꾸지 않는다. 목표 상태·처리 결과·사유를 payload 에 담아
작업을 등록하고, Jira 반영이 조회로 확인된 뒤에 상태·처리 결과·시각과 이력을 갱신한다 (API 03 1.3).

실행(Jira 호출 → 확인 → 반영)은 아직 없다. 실행기가 이 payload 를 읽는다.
"""
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import IntegrationJob, Ticket

JOB_TYPE = "JIRA_TRANSITION"


def enqueue_jira_transition(db: Session, ticket: Ticket, payload: dict[str, Any]) -> IntegrationJob:
    """flush 만 한다. 커밋은 호출자가 한다.

    접수당 진행 중(PENDING·RUNNING) 상태 변경 작업은 하나다 (uq_integration_jobs_one_active).
    동시에 두 요청이 들어오면 두 번째는 IntegrityError 가 난다. 키는 논리 작업마다 새 UUID (06 연동 보완).
    """
    job = IntegrationJob(ticket_id=ticket.id, job_type=JOB_TYPE, status="PENDING", attempts=0,
                         idempotency_key=f"transition:{uuid.uuid4()}", payload=payload)
    db.add(job)
    db.flush()
    return job
