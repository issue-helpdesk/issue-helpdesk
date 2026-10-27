"""서버 로그 안전망 (M4-2-3, docs/10 5.3 ④) 테스트."""
import io
import logging

import pytest

import app.agent.sensitive.log_filter as log_filter_module
from app.agent.sensitive import MaskSecretsFilter


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
