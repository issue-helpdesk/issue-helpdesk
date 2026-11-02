"""Jira 생성 작업 독립 실행기 — 서버(FastAPI)와 별개 프로세스로 대기 중인 JIRA_CREATE 작업을 처리한다.

    uv run python backend/app/integrations/jira/worker.py --once            # 한 번만 돌고 종료
    uv run python backend/app/integrations/jira/worker.py --interval 30     # 30초마다 반복 (Ctrl+C 로 종료)

한 번 돌 때 하는 일 (services/jira_create.py 의 함수를 그대로 부른다)
    1. 오래 RUNNING 으로 방치된 작업을 되돌린다 (requeue_stale_running_jobs)
    2. 실행 시각이 된 PENDING 작업을 오래된 순서로 최대 --limit 건 실행한다 (run_due_jira_create_jobs)

필요한 것: 루트 .env 의 DATABASE_URL · JIRA_BASE_URL · JIRA_EMAIL · JIRA_API_TOKEN
서버 안에 붙이는 일(앱 시작 시 백그라운드로 띄우기)은 main.py 담당이 정한다. 이 파일은 main.py 를 건드리지 않는다.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # backend/

from sqlalchemy.orm import Session  # noqa: E402

from app.integrations.jira.client import JiraClient  # noqa: E402
from app.services import jira_create  # noqa: E402
from app.services.jira_create import JobResult  # noqa: E402

logger = logging.getLogger("jira_worker")


@dataclass(frozen=True)
class RoundReport:
    """한 번 돈 결과."""

    requeued: int
    results: list[JobResult]

    def summary(self) -> str:
        counts: dict[str, int] = {}
        for r in self.results:
            counts[r.outcome] = counts.get(r.outcome, 0) + 1
        done = ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "처리할 작업 없음"
        return f"되돌린 방치 작업 {self.requeued}건 · {done}"


def run_round(
    db: Session,
    jira: JiraClient,
    *,
    limit: int = 10,
    stale_after: timedelta = timedelta(minutes=5),
    now: datetime | None = None,
) -> RoundReport:
    """방치된 작업을 되돌린 뒤 실행할 때가 된 작업을 처리한다. 각 작업의 결과는 서비스가 커밋한다."""
    requeued = jira_create.requeue_stale_running_jobs(db, older_than=stale_after, now=now)
    results = jira_create.run_due_jira_create_jobs(db, jira, limit=limit, now=now)
    return RoundReport(requeued, results)


def run_loop(
    session_factory,
    jira: JiraClient,
    *,
    interval: float,
    limit: int,
    stale_after: timedelta,
    stop: threading.Event,
    once: bool = False,
) -> int:
    """stop 이 켜질 때까지 반복한다. 한 번 도는 중 예외가 나도 다음 주기에 다시 시도한다.

    돌려주는 값은 종료 코드: --once 에서 예외가 났으면 1, 그 외 0.
    """
    failed = False
    while not stop.is_set():
        try:
            with session_factory() as db:
                report = run_round(db, jira, limit=limit, stale_after=stale_after)
            logger.info(report.summary())
            failed = False
        except Exception:  # 코드·DB 오류. 작업은 RUNNING 으로 남고 다음에 requeue 된다
            logger.exception("작업 처리 중 오류")
            failed = True
        if once:
            break
        stop.wait(interval)
    return 1 if (once and failed) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Jira 생성 작업 독립 실행기")
    parser.add_argument("--once", action="store_true", help="한 번만 돌고 종료")
    parser.add_argument("--interval", type=float, default=30.0, help="반복 주기(초), 기본 30")
    parser.add_argument("--limit", type=int, default=10, help="한 번에 처리할 최대 작업 수, 기본 10")
    parser.add_argument("--stale-minutes", type=float, default=5.0, help="이 시간 넘게 RUNNING 이면 방치로 보고 되돌림, 기본 5분")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from app.db.session import get_engine  # DB 연결 설정은 읽기만 한다

    engine = get_engine()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    with JiraClient.from_env() as jira:
        logger.info("시작: interval=%ss limit=%s once=%s", args.interval, args.limit, args.once)
        code = run_loop(
            lambda: Session(engine),
            jira,
            interval=args.interval,
            limit=args.limit,
            stale_after=timedelta(minutes=args.stale_minutes),
            stop=stop,
            once=args.once,
        )
    logger.info("종료")
    return code


if __name__ == "__main__":
    sys.exit(main())
