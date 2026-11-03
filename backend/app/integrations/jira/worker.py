"""Jira 연동 작업 독립 실행기 — 생성·배정·상태 변경과 웹훅 이벤트 반영을 별도 프로세스에서 처리한다.

    uv run python backend/app/integrations/jira/worker.py --once            # 한 번만 돌고 종료
    uv run python backend/app/integrations/jira/worker.py --interval 30     # 30초마다 반복 (Ctrl+C 로 종료)

한 번 돌 때 생성 → 배정 → 상태 변경 순으로 각 서비스의 중단 복구·단건 실행 함수를 호출하고,
마지막에 API 가 저장해 둔 웹훅 이벤트(PENDING)를 run_due_webhook_events 로 DB 에 반영한다.
웹훅을 마지막에 두는 이유: ITssue 가 보낸 변경이 되돌아온 이벤트는 위 작업이 끝난 뒤라야 값이 같아 그대로 끝난다.
--limit 은 종류별 상한이다(웹훅은 Jira 를 부른 건수 기준). --ticket-id 를 주면 조회·복구·실행 모두 해당 접수만 처리하고,
웹훅 이벤트는 접수별로 고르는 기능이 없어 그때는 처리하지 않는다. 웹훅만 끄려면 --no-webhook.

필요한 것: 루트 .env 의 DATABASE_URL · JIRA_BASE_URL · JIRA_EMAIL · JIRA_API_TOKEN
서버 안에 붙이는 일(앱 시작 시 백그라운드로 띄우기)은 main.py 담당이 정한다. 이 파일은 main.py 를 건드리지 않는다.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # backend/

from sqlalchemy import or_, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.integrations.jira.client import JiraClient  # noqa: E402
from app.models import IntegrationJob  # noqa: E402
from app.services import jira_assign, jira_create, jira_transition, jira_webhook  # noqa: E402
from app.utils import datetime_utils  # noqa: E402
from app.services.jira_create import JobResult  # noqa: E402
from app.services.jira_assign import AssignmentResult  # noqa: E402
from app.services.jira_transition import TransitionResult  # noqa: E402
from app.services.jira_webhook import WebhookResult  # noqa: E402

logger = logging.getLogger("jira_worker")

JOB_TYPES = ("JIRA_CREATE", "JIRA_ASSIGN", "JIRA_TRANSITION")
WEBHOOK_KIND = "WEBHOOK"     # 작업표(IntegrationJob)의 종류가 아니라 jira_webhook_events 를 처리하는 단계의 이름


@dataclass
class RoundReport:
    """한 번 돈 결과."""

    requeued: int
    results: list[JobResult | AssignmentResult | TransitionResult | WebhookResult]
    result_types: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        counts: dict[str, int] = {}
        for i, r in enumerate(self.results):
            label = f"{self.result_types[i]}:{r.outcome}" if self.result_types else r.outcome
            counts[label] = counts.get(label, 0) + 1
        done = ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "처리할 작업 없음"
        return f"되돌린 방치 작업 {self.requeued}건 · {done} · 오류 {len(self.errors)}건"


def _due_ids(db: Session, job_type: str, *, limit: int, now: datetime, ticket_id: int | None) -> list[int]:
    """실행할 때가 된 PENDING 작업 ID를 오래된 순으로 최대 limit 건."""
    query = select(IntegrationJob.id).where(
        IntegrationJob.job_type == job_type, IntegrationJob.status == "PENDING",
        or_(IntegrationJob.next_retry_at.is_(None), IntegrationJob.next_retry_at <= now),
    )
    if ticket_id is not None:
        query = query.where(IntegrationJob.ticket_id == ticket_id)
    return list(db.scalars(query.order_by(IntegrationJob.id).limit(limit)))


def run_round(
    db: Session,
    jira: JiraClient,
    *,
    limit: int = 10,
    stale_after: timedelta = timedelta(minutes=5),
    now: datetime | None = None,
    job_types: tuple[str, ...] = JOB_TYPES,
    ticket_id: int | None = None,
    webhook: bool = True,
) -> RoundReport:
    """종류별 복구 뒤 단건 실행, 이어서 웹훅 이벤트 반영. 예외는 rollback하고 나머지 작업을 계속한다."""
    if limit < 1 or stale_after <= timedelta(0) or (ticket_id is not None and ticket_id < 1):
        raise ValueError("limit·stale_after·ticket_id는 양수여야 합니다.")
    if not job_types or set(job_types) - set(JOB_TYPES):
        raise ValueError("지원하지 않는 작업 종류입니다.")
    now = now or datetime_utils.now()
    handlers = {
        "JIRA_CREATE": (jira_create.requeue_stale_running_jobs, jira_create.run_jira_create_job),
        "JIRA_ASSIGN": (jira_assign.requeue_stale_assign_jobs, jira_assign.run_jira_assign_job),
        "JIRA_TRANSITION": (jira_transition.requeue_stale_transition_jobs, jira_transition.run_jira_transition_job),
    }
    report = RoundReport(0, [])
    for kind in JOB_TYPES:
        if kind not in job_types:
            continue
        recover, execute = handlers[kind]
        try:
            report.requeued += recover(db, older_than=stale_after, now=now, ticket_id=ticket_id)
            ids = _due_ids(db, kind, limit=limit, now=now, ticket_id=ticket_id)
            # 선택 조회의 트랜잭션을 닫고 단건 서비스가 다시 선점·검증한다.
            db.rollback()
        except Exception as error:
            db.rollback()
            report.errors.append(f"{kind}:prepare:{type(error).__name__}")
            logger.error("작업 준비 실패: kind=%s error=%s", kind, type(error).__name__)
            continue
        for job_id in ids:
            try:
                result = execute(db, jira, job_id, now=now)
                report.results.append(result)
                report.result_types.append(kind)
                logger.info("작업 결과: kind=%s job_id=%s outcome=%s", kind, job_id, result.outcome)
            except Exception as error:
                # 서비스가 커밋한 RUNNING·조회 전용 표식은 보존한다. 다음 주기에 복구한다.
                db.rollback()
                report.errors.append(f"{kind}:{job_id}:{type(error).__name__}")
                logger.error("작업 실행 실패: kind=%s job_id=%s error=%s", kind, job_id, type(error).__name__)
    if webhook and ticket_id is None:
        _run_webhooks(db, jira, report, limit=limit, now=now)
    return report


def _run_webhooks(db: Session, jira: JiraClient, report: RoundReport, *, limit: int, now: datetime) -> None:
    """저장된 웹훅 이벤트를 반영한다. 이벤트 한 건씩 커밋하므로 중간에 예외가 나도 앞의 결과는 남는다."""
    try:
        results = jira_webhook.run_due_webhook_events(db, jira, limit=limit, now=now)
    except Exception as error:
        db.rollback()
        report.errors.append(f"{WEBHOOK_KIND}:run:{type(error).__name__}")
        logger.error("웹훅 이벤트 처리 실패: error=%s", type(error).__name__)
        return
    for result in results:
        report.results.append(result)
        report.result_types.append(WEBHOOK_KIND)
        logger.info("웹훅 결과: event_id=%s outcome=%s reason=%s", result.event_id, result.outcome, result.reason)


def run_loop(
    session_factory,
    jira: JiraClient,
    *,
    interval: float,
    limit: int,
    stale_after: timedelta,
    stop: threading.Event,
    once: bool = False,
    job_types: tuple[str, ...] = JOB_TYPES,
    ticket_id: int | None = None,
    webhook: bool = True,
) -> int:
    """stop 이 켜질 때까지 반복한다. 한 번 도는 중 예외가 나도 다음 주기에 다시 시도한다.

    돌려주는 값은 종료 코드: --once 에서 예외가 났으면 1, 그 외 0.
    """
    failed = False
    while not stop.is_set():
        try:
            with session_factory() as db:
                report = run_round(db, jira, limit=limit, stale_after=stale_after,
                                   job_types=job_types, ticket_id=ticket_id, webhook=webhook)
            logger.info(report.summary())
            failed = bool(report.errors)
        except Exception:  # 코드·DB 오류. 작업은 RUNNING 으로 남고 다음에 requeue 된다
            logger.error("작업 회차 실패", exc_info=False)
            failed = True
        if once:
            break
        stop.wait(interval)
    return 1 if (once and failed) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Jira 생성·배정·상태 변경·웹훅 반영 독립 실행기")
    parser.add_argument("--once", action="store_true", help="한 번만 돌고 종료")
    parser.add_argument("--interval", type=float, default=30.0, help="반복 주기(초), 기본 30")
    parser.add_argument("--limit", type=int, default=10, help="종류별 한 회차 최대 작업 수, 기본 10")
    parser.add_argument("--stale-minutes", type=float, default=5.0, help="이 시간 넘게 RUNNING 이면 방치로 보고 되돌림, 기본 5분")
    parser.add_argument("--job-types", nargs="+", choices=JOB_TYPES, default=list(JOB_TYPES),
                        help="처리할 작업 종류, 기본값은 생성·배정·상태 변경 모두")
    parser.add_argument("--ticket-id", type=int, help="지정한 접수만 복구·실행 (단건 시험용, 웹훅 반영은 하지 않음)")
    parser.add_argument("--no-webhook", action="store_true", help="웹훅 이벤트 반영을 건너뜀 (기본은 매 회차 반영)")
    args = parser.parse_args(argv)
    if (args.interval <= 0 or args.limit < 1 or args.stale_minutes <= 0
            or (args.ticket_id is not None and args.ticket_id < 1)):
        parser.error("interval·limit·stale-minutes·ticket-id는 양수여야 합니다.")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from app.db.session import get_engine  # DB 연결 설정은 읽기만 한다

    engine = get_engine()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    with JiraClient.from_env() as jira:
        logger.info("시작: interval=%ss limit=%s once=%s webhook=%s", args.interval, args.limit, args.once,
                    not args.no_webhook and args.ticket_id is None)
        code = run_loop(
            lambda: Session(engine),
            jira,
            interval=args.interval,
            limit=args.limit,
            stale_after=timedelta(minutes=args.stale_minutes),
            stop=stop,
            once=args.once,
            job_types=tuple(args.job_types),
            ticket_id=args.ticket_id,
            webhook=not args.no_webhook,
        )
    logger.info("종료")
    return code


if __name__ == "__main__":
    sys.exit(main())
