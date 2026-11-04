"""업로드 문서 적재를 서버 안에서 한 건씩 돌린다 (DC-07). 적재는 CPU 를 많이 쓰므로 검색이 느려지지 않게 줄 세운다.

임베딩 모델은 검색과 같은 것을 쓴다. DB 연결 실패나 서버 중단으로 PENDING 으로 남은 버전은 서버 시작 때와
그 뒤 주기적으로 이어서 한다.
"""
import asyncio
import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated

from fastapi import Depends

from app.core.config import get_settings
from app.rag.ingest import connect
from app.rag.ingest.upload import ingest_version, resume_pending
from app.rag.search.runtime import get_embedder
from app.services.document_file import STORAGE_DIR, cleanup_temp_files

logger = logging.getLogger(__name__)

RESUME_INTERVAL_SECONDS = 300

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="document-ingest")
_resume_slot = threading.Lock()         # 잡고 있으면 이어 하기가 이미 줄에 있거나 도는 중이다


def submit_ingest(version_id: int) -> None:
    _executor.submit(run_ingest, version_id)


def submit_resume() -> None:
    """시작을 막지 않도록 줄에 넣기만 한다. 앞선 이어 하기가 안 끝났으면 또 넣지 않는다."""
    if _resume_slot.acquire(blocking=False):
        _executor.submit(run_resume).add_done_callback(lambda _: _resume_slot.release())


async def resume_periodically() -> None:
    """서버가 도는 동안 멈춘 적재를 주기적으로 잇는다. DB 연결이 돌아오면 재시작 없이 풀린다."""
    while True:
        await asyncio.sleep(RESUME_INTERVAL_SECONDS)
        submit_resume()


def submit_cleanup() -> None:
    """서버 시작 때 부른다. 남은 임시 파일을 지운다."""
    _executor.submit(run_cleanup)


def run_cleanup() -> None:
    try:
        cleanup_temp_files()
        if STORAGE_DIR.exists():                # 업로드한 적이 없으면 DB 에 붙지 않는다
            with connect(get_settings().dsn, allow_remote=True) as conn:
                paths = {p for (p,) in conn.execute("select file_path from document_versions where file_path is not null")}
            cleanup_temp_files(known_paths=paths)
    except Exception:
        logger.exception("업로드 파일 정리 실패")


def run_ingest(version_id: int) -> None:
    try:
        with connect(get_settings().dsn, allow_remote=True) as conn:
            try:
                embedder = get_embedder()
            except Exception:
                logger.exception("임베딩 모델을 열지 못했습니다 version_id=%s", version_id)
                conn.execute("update document_versions set ingest_status = 'FAILED', ingest_error = %s "
                             "where id = %s and ingest_status = 'PENDING'",
                             ("임베딩 모델을 열지 못했습니다. 서버 설정을 확인한 뒤 새 버전으로 다시 올려 주세요.", version_id))
                conn.commit()
                return
            ingest_version(conn, version_id, embedder)
    except Exception:                       # 실행기 스레드는 계속 살아 있어야 다음 적재를 한다
        logger.exception("문서 적재 실패 version_id=%s", version_id)


def run_resume() -> None:
    try:
        with connect(get_settings().dsn, allow_remote=True) as conn:
            resume_pending(conn, get_embedder())
    except Exception:
        logger.exception("적재 이어 하기 실패")


def ingest_submitter() -> Callable[[int], None]:
    return submit_ingest


IngestSubmitterDep = Annotated[Callable[[int], None], Depends(ingest_submitter)]
