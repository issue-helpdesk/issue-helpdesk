"""해결 사례 가이드화 주간 분석 실행기. 회차 규칙과 한 회차 실행은 app/services/guide_analysis.py 에 있다.

    cd backend
    python -m app.workers.guide_analysis          # 일정대로 반복 (서버의 guide-worker)
    python -m app.workers.guide_analysis --once   # 지금 한 번만. 실제 Claude 를 부르고 .env 의 DB 에 묶음을 쓴다

임베딩 모델이 쉬는 동안 메모리에 남지 않게, 회차마다 별도 프로세스(--once)로 돌린다.
"""
import argparse
import logging
import signal
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from datetime import datetime

from sqlalchemy.orm import Session

from app.agent.sensitive import install_log_filter
from app.services.guide_analysis import SessionFactory, abandon_running, due_slot, run_once
from app.utils import datetime_utils

logger = logging.getLogger('guide_worker')

POLL_SECONDS = 300.0
TERMINATE_SECONDS = 50                  # 컨테이너 stop_grace_period(60초) 안에 끝나게


def run_child(command: Sequence[str], stop: threading.Event) -> int:
    """회차 프로세스가 끝날 때까지 기다린다. 종료 신호를 받으면 회차도 끝낸다."""
    process = subprocess.Popen(list(command))
    while process.poll() is None:
        if stop.wait(1):
            process.terminate()
            try:
                process.wait(TERMINATE_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    return process.returncode


def _child_command(slot: datetime) -> list[str]:
    return [sys.executable, '-m', 'app.workers.guide_analysis', '--once', '--scheduled-for', slot.isoformat()]


def tick(session_factory: SessionFactory, stop: threading.Event,
         child: Callable[[Sequence[str], threading.Event], int] = run_child) -> None:
    """회차가 되었으면 한 번 돌린다."""
    started = datetime_utils.now()
    with session_factory() as db:
        slot = due_slot(db, started)
    if slot is None:
        return
    code = child(_child_command(slot), stop)
    if code:
        logger.error('분석 프로세스 비정상 종료: scheduled_for=%s code=%s', slot, code)
        abandon_running(session_factory, since=started)


def schedule_loop(session_factory: SessionFactory, stop: threading.Event, poll: float = POLL_SECONDS) -> None:
    """stop 이 켜질 때까지 회차를 확인한다. DB 오류가 나도 다음 확인에서 다시 시도한다."""
    while not stop.is_set():
        try:
            tick(session_factory, stop)
        except Exception as e:
            logger.error('회차 확인 실패: %s', type(e).__name__)
        now = datetime_utils.now()
        stop.wait(max(1.0, min(poll, (datetime_utils.kst_next_week_start(now) - now).total_seconds())))


def _exit_on_term(*_) -> None:
    raise SystemExit(143)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='해결 사례 가이드화 주간 분석 실행기')
    parser.add_argument('--once', action='store_true', help='지금 한 번만 돌고 종료 (실제 Claude 호출, DB 저장)')
    parser.add_argument('--poll-seconds', type=float, default=POLL_SECONDS, help='회차를 확인하는 주기(초), 기본 300')
    parser.add_argument('--scheduled-for', type=datetime.fromisoformat, help=argparse.SUPPRESS)     # 일정 실행이 넘긴다
    args = parser.parse_args(argv)
    if args.poll_seconds <= 0:
        parser.error('poll-seconds 는 양수여야 합니다.')

    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    install_log_filter()

    from app.db.session import get_engine

    engine = get_engine()
    factory = lambda: Session(engine)
    if args.once:
        signal.signal(signal.SIGTERM, _exit_on_term)
        return run_once(factory, args.scheduled_for)

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    logger.info('시작: 매주 월요일 00:00(KST), 확인 주기 %s초', args.poll_seconds)
    schedule_loop(factory, stop, args.poll_seconds)
    logger.info('종료')
    return 0


if __name__ == '__main__':
    sys.exit(main())
