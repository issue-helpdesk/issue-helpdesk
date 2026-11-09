"""해결 사례 가이드화 주간 분석의 회차 규칙과 한 회차 실행. 반복 실행은 app/workers/guide_analysis.py 가 한다.

회차는 "이번 주 월요일 00:00(KST)" 이고 guide_analysis_runs 에 시도를 남긴다.
- 서버가 꺼져 회차를 놓치면 켜질 때 가장 최근 회차만 한 번 돌린다 (여러 주를 놓쳐도 한 번)
- 회차 전체가 실패하면 1시간 뒤 다시, 3번까지. 티켓·묶음 하나의 실패는 run_round 안에서 다음 회차로 넘어간다
- 실행 중인 행은 DB 에서 하나뿐이라 두 회차가 겹치지 않는다. 프로세스가 강제로 죽어 남은 행은 24시간 뒤 실패로 닫는다
"""
import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent.guide.run import DraftRun, JudgeRun, run_round
from app.repositories.guide_analysis_run import GuideAnalysisRunRepository
from app.utils import datetime_utils

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3                        # 한 회차에 실패해도 다시 해 보는 횟수
RETRY_AFTER = timedelta(hours=1)
STALE_AFTER = timedelta(hours=24)       # 첫 회차는 대상이 많을 수 있어 넉넉히 둔다

SessionFactory = Callable[[], Session]


def due_slot(db: Session, now: datetime) -> datetime | None:
    """지금 돌려야 할 회차. 없으면 None."""
    runs = GuideAnalysisRunRepository(db)
    runs.fail_running('STALE', now, before=now - STALE_AFTER)
    db.commit()
    if runs.running() is not None:
        return None
    slot = datetime_utils.kst_week_start(now)
    attempts = runs.for_schedule(slot)
    if any(r.status == 'SUCCEEDED' for r in attempts) or len(attempts) >= MAX_ATTEMPTS:
        return None
    if attempts and now - datetime_utils.as_utc(attempts[-1].finished_at) < RETRY_AFTER:
        return None
    return slot


def claim(db: Session, scheduled_for: datetime | None, now: datetime) -> int | None:
    """실행 기록을 만들고 그 id 를 돌려준다. 이미 실행 중이면 None."""
    runs = GuideAnalysisRunRepository(db)
    try:
        runs.fail_running('STALE', now, before=now - STALE_AFTER)
        run_id = runs.add_running(scheduled_for, now).id
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    return run_id


def _materials(db: Session) -> tuple:
    """(모델, 검색, 임베딩). 키나 모델 파일이 없으면 여기서 실패해, 티켓마다 실패한 채 '성공'으로 끝나지 않게 한다."""
    from app.agent.llm.config import get_llm_adapter
    from app.rag.search.runtime import get_embedder
    from app.rag.search.service import search

    port, embedder = get_llm_adapter(), get_embedder()
    return port, (lambda request: search(db, request, embedder)), embedder.embed_documents


def counts_of(judged: JudgeRun, drafted: DraftRun) -> dict[str, int]:
    return {'forwarded': len(judged.forwarded), 'excluded': judged.excluded, 'judge_failed': judged.failed,
            'sec': judged.sec, 'created': drafted.created, 'attached': drafted.attached,
            'waiting': drafted.waiting, 'draft_failed': drafted.failed}


def _finish(session_factory: SessionFactory, run_id: int, status: str, **values) -> None:
    try:
        with session_factory() as db:
            GuideAnalysisRunRepository(db).finish(run_id, status, datetime_utils.now(), **values)
            db.commit()
    except Exception as e:                      # 기록을 못 닫아도 STALE_AFTER 뒤에 닫힌다
        logger.error('실행 기록을 닫지 못함: run_id=%s error=%s', run_id, type(e).__name__)


def run_once(session_factory: SessionFactory, scheduled_for: datetime | None = None, *,
             materials: Callable[[Session], tuple] = _materials, runner: Callable[..., tuple] = run_round) -> int:
    """한 회차. 돌려주는 값은 종료 코드: 회차 전체가 실패하면 1, 그 외 0."""
    with session_factory() as db:
        run_id = claim(db, scheduled_for, datetime_utils.now())
    if run_id is None:
        logger.warning('이미 실행 중인 분석이 있어 건너뜁니다')
        return 0
    logger.info('분석 시작: run_id=%s scheduled_for=%s', run_id, scheduled_for)
    try:
        with session_factory() as db:
            judged, drafted = runner(db, *materials(db))
    except BaseException as e:                  # 종료 신호(SystemExit)도 기록을 닫고 끝낸다
        _finish(session_factory, run_id, 'FAILED', error_code=type(e).__name__)
        logger.error('분석 실패: run_id=%s error=%s', run_id, type(e).__name__)     # 원문은 남기지 않는다 (docs/10 5.3)
        if not isinstance(e, Exception):
            raise
        return 1
    counts = counts_of(judged, drafted)
    _finish(session_factory, run_id, 'SUCCEEDED', counts=counts)
    logger.info('분석 끝: run_id=%s %s', run_id, counts)
    return 0


def abandon_running(session_factory: SessionFactory, since: datetime) -> None:
    """강제로 죽은 프로세스가 남긴 실행 기록을 닫는다. 재시도가 STALE_AFTER 만큼 밀리지 않게 한다."""
    with session_factory() as db:
        GuideAnalysisRunRepository(db).fail_running('ABORTED', datetime_utils.now(), since=since)
        db.commit()
