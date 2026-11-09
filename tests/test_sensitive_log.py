"""서버 로그 안전망 (M4-2-3, docs/10 5.3 ④) 테스트."""
import io
import logging

import pytest

import app.agent.sensitive.log_filter as log_filter_module
from app.agent.sensitive import MaskSecretsFilter, install_log_filter


@pytest.fixture
def log():
    """MaskSecretsFilter 를 붙인 핸들러로 하위 로거에서 남긴 기록을 받는다"""
    out = io.StringIO()
    handler = logging.StreamHandler(out)
    handler.addFilter(MaskSecretsFilter())
    handler.setFormatter(logging.Formatter('%(message)s'))
    parent = logging.getLogger('test_sensitive_log')
    parent.addHandler(handler)
    parent.setLevel(logging.INFO)
    yield logging.getLogger('test_sensitive_log.child'), out
    parent.removeHandler(handler)


def test_message_and_args_are_masked(log):
    logger, out = log
    logger.info('사용자 글: %s', '비밀번호는 Abc123! 인데 010-1234-5678')
    assert out.getvalue().strip() == '사용자 글: 비밀번호는 ●●●●●● 인데 010-1234-5678'


def test_exception_text_is_masked(log):
    logger, out = log
    try:
        raise ValueError('주민번호 900101-1234567 처리 실패')
    except ValueError:
        logger.exception('저장 실패')
    text = out.getvalue()
    assert '900101-1234567' not in text
    assert 'ValueError: 주민번호 ●●●●●● 처리 실패' in text


def test_trace_id_is_kept(log):
    """traceId 로 오류 원인을 찾으므로 가리지 않는다 (07 5.7). 같은 줄의 비밀값은 가린다"""
    logger, out = log
    try:
        raise ValueError('비밀번호는 Abc123!')
    except ValueError:
        logger.exception('처리하지 못한 오류 traceId=%s', '550e8400-e29b-41d4-a716-446655440000')
    text = out.getvalue()
    assert text.startswith('처리하지 못한 오류 traceId=550e8400-e29b-41d4-a716-446655440000')
    assert 'ValueError: 비밀번호는 ●●●●●●' in text


def test_failure_drops_content(log, monkeypatch):
    """가리다 실패하면 내용을 지우고 남긴다 (docs/10 3.3)"""
    def broken(_text):
        raise RuntimeError('필터 오류')
    monkeypatch.setattr(log_filter_module, 'mask_secrets', broken)
    logger, out = log
    logger.info('비밀번호는 Abc123!')
    assert out.getvalue().strip() == log_filter_module.FAILED_TEXT


@pytest.fixture
def clean_filters():
    """install_log_filter 가 붙인 필터를 시험 뒤에 뗀다 (lastResort 는 프로세스 전체가 쓴다)"""
    yield
    handlers = list(logging.getLogger().handlers) + [logging.lastResort]
    for lg in logging.Logger.manager.loggerDict.values():
        if isinstance(lg, logging.Logger):
            handlers += lg.handlers
    for h in handlers:
        for f in [f for f in h.filters if isinstance(f, MaskSecretsFilter)]:
            h.removeFilter(f)


def test_install_attaches_to_existing_handlers_once(clean_filters):
    out = io.StringIO()
    handler = logging.StreamHandler(out)
    handler.setFormatter(logging.Formatter('%(message)s'))
    logger = logging.getLogger('test_sensitive_log.install')
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        assert install_log_filter() >= 2                       # 이 핸들러와 lastResort
        assert install_log_filter() == 0                       # 다시 불러도 겹쳐 붙지 않는다
        logger.info('비밀번호는 Abc123!')
        assert out.getvalue().strip() == '비밀번호는 ●●●●●●'
        assert any(isinstance(f, MaskSecretsFilter) for f in logging.lastResort.filters)
    finally:
        logger.removeHandler(handler)


def test_uvicorn_access_log_keeps_format(clean_filters):
    """uvicorn 접속 기록 서식은 args 5개를 꺼내 쓴다. 묶음을 지우지 않고 하나씩 가린다"""
    from uvicorn.logging import AccessFormatter
    out = io.StringIO()
    handler = logging.StreamHandler(out)
    handler.setFormatter(AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False))
    logger = logging.getLogger('uvicorn.access')
    old = (logger.handlers[:], logger.level, logger.propagate)
    logger.handlers, logger.propagate = [handler], False
    logger.setLevel(logging.INFO)
    try:
        install_log_filter()
        logger.info('%s - "%s %s HTTP/%s" %d', '127.0.0.1:5000', 'GET', '/api/v1/login?password=Abc123!', '1.1', 200)
        line = out.getvalue().strip()
        assert line.startswith('127.0.0.1:5000 - "GET /api/v1/login?') and line.endswith('HTTP/1.1" 200 OK')
        assert 'Abc123!' not in line
    finally:
        logger.handlers, logger.propagate = old[0], old[2]
        logger.setLevel(old[1])
