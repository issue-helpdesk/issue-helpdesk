"""서버에서 검색 부르기(runtime) 테스트. 모델 파일 없이 가짜 Embedder 로 '한 번만 연다'는 규칙만 본다."""
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.rag.search import SearchRequest
from app.rag.search import runtime


class FakeEmbedder:
    opened = 0

    def __init__(self, key):
        time.sleep(0.05)                    # 여는 데 시간이 걸리는 동안 다른 요청이 들어오는 상황
        FakeEmbedder.opened += 1
        self.model_id = f'{key}@fake/v1'


@pytest.fixture(autouse=True)
def fake_model(monkeypatch):
    FakeEmbedder.opened = 0
    monkeypatch.setattr(runtime, 'Embedder', FakeEmbedder)
    monkeypatch.setattr(runtime, '_embedder', None)
    monkeypatch.delenv('EMBEDDING_PRELOAD', raising=False)


def test_preload_off_by_default():
    """기본은 미리 열지 않는다 (모델 파일이 없는 개발 PC에서도 서버가 뜬다)."""
    runtime.preload()
    assert not runtime.is_loaded() and FakeEmbedder.opened == 0


@pytest.mark.parametrize('value', ['true', '1', 'YES'])
def test_preload_on(monkeypatch, value):
    monkeypatch.setenv('EMBEDDING_PRELOAD', value)
    runtime.preload()
    assert runtime.is_loaded() and FakeEmbedder.opened == 1


def test_opens_once_and_reuses():
    first = runtime.get_embedder()
    assert runtime.get_embedder() is first and FakeEmbedder.opened == 1


def test_opens_once_under_concurrent_first_requests():
    """처음에 요청이 동시에 몰려도 모델은 한 번만 연다."""
    got = []
    threads = [threading.Thread(target=lambda: got.append(runtime.get_embedder())) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert FakeEmbedder.opened == 1 and all(e is got[0] for e in got)


def test_search_fn_uses_request_session_and_shared_model(monkeypatch):
    """search_fn 은 그 요청의 DB 세션과 서버의 Embedder 로 search() 를 부른다. 부르기 전에는 모델을 열지 않는다."""
    calls = []
    monkeypatch.setattr(runtime, 'search', lambda db, req, emb: calls.append((db, req, emb)) or 'resp')
    session = object()
    search_fn = runtime.get_search_fn(session)
    assert not runtime.is_loaded()

    req = SearchRequest(query='노트북이 안 켜져요', service_role='EMPLOYEE')
    assert search_fn(req) == 'resp'
    assert calls == [(session, req, runtime.get_embedder())] and FakeEmbedder.opened == 1


@pytest.mark.parametrize('preload, loaded', [(None, False), ('true', True)])
def test_server_start_preloads_only_when_enabled(monkeypatch, preload, loaded):
    """main.py lifespan: EMBEDDING_PRELOAD=true 일 때만 서버가 시작하면서 모델을 연다."""
    from app.main import app

    if preload:
        monkeypatch.setenv('EMBEDDING_PRELOAD', preload)
    with TestClient(app):
        assert runtime.is_loaded() is loaded
