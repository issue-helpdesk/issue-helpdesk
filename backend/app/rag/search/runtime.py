"""서버에서 검색 부르기 (WBS M3-2-2). 임베딩 모델은 서버에서 한 번만 열고 요청마다 같은 것을 쓴다.

    # main.py lifespan: EMBEDDING_PRELOAD=true 면 서버가 시작할 때 모델을 미리 연다
    runtime.preload()

    # API·서비스: 의존성으로 받아 M4 판단 흐름에 그대로 넘긴다
    def handler(..., search_fn: SearchFnDep):
        run_flow(..., search_fn)

- 모델을 여는 데 노트북 약 10초, EC2(2 vCPU) 약 28초. 요청마다 열면 매번 그만큼 걸린다.
- EMBEDDING_PRELOAD 가 꺼져 있으면 첫 검색 때 연다. 모델 파일이 없는 개발 PC·시험에서도 서버를 띄울 수 있게 기본은 끈다.
- 처음에 요청이 동시에 와도 한 번만 연다.
- search_fn 은 그 요청의 DB 세션으로 검색한다. 검색이 필요 없는 요청(1차 판단에서 끝남)에서는 모델을 열지 않는다.
"""
import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends

from app.db.session import DbSession
from app.rag.embedding import DEFAULT_MODEL, Embedder
from app.rag.search.result import SearchRequest, SearchResponse
from app.rag.search.service import search

logger = logging.getLogger(__name__)

SearchFn = Callable[[SearchRequest], SearchResponse]     # M4 판단 흐름(run_flow)이 받는 모양

_lock = threading.Lock()
_embedder: Embedder | None = None


def preload_enabled() -> bool:
    return os.environ.get('EMBEDDING_PRELOAD', '').strip().lower() in ('1', 'true', 'yes')


def get_embedder() -> Embedder:
    """서버에서 하나뿐인 Embedder. 처음 부를 때 연다. 모델 파일이 없으면 FileNotFoundError."""
    global _embedder
    if _embedder is None:
        with _lock:
            if _embedder is None:
                started = time.perf_counter()
                _embedder = Embedder(DEFAULT_MODEL)
                logger.info('임베딩 모델 %s 를 열었습니다 (%.1f초)', _embedder.model_id, time.perf_counter() - started)
    return _embedder


def is_loaded() -> bool:
    """모델이 열려 있는가. 서버 준비 확인(/ready)에 쓸 수 있다."""
    return _embedder is not None


def preload() -> None:
    """EMBEDDING_PRELOAD=true 면 지금 연다. 서버에서는 모델이 없으면 시작할 때 바로 실패하는 편이 낫다."""
    if preload_enabled():
        get_embedder()


def get_search_fn(db: DbSession) -> SearchFn:
    return lambda request: search(db, request, get_embedder())


SearchFnDep = Annotated[SearchFn, Depends(get_search_fn)]
