"""API 서버 시작 때의 설정 검사. 실제 DB·모델에는 붙지 않는다."""
import logging

import pytest
from fastapi.testclient import TestClient

from app import main
from app.core.config import FEATURE_ENV_NAMES, get_auth_settings, get_settings


def clear_caches():
    get_settings.cache_clear()
    get_auth_settings.cache_clear()


@pytest.fixture(autouse=True)
def valid_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/offline")
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    for name in FEATURE_ENV_NAMES:
        monkeypatch.setenv(name, "secret-value")
    monkeypatch.delenv("EMBEDDING_PRELOAD", raising=False)
    monkeypatch.setattr(main, "submit_cleanup", lambda: None)
    clear_caches()
    yield
    clear_caches()


def warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.name == "app.core.config" and r.levelno == logging.WARNING]


def test_starts_without_warning_when_all_set(caplog):
    with TestClient(main.app):
        pass
    assert warnings(caplog) == []


@pytest.mark.parametrize("name, value", [("JWT_SECRET", None), ("JWT_SECRET", "x" * 31), ("DATABASE_URL", None)])
def test_required_setting_stops_startup_before_loading_model(monkeypatch, name, value):
    if value is None:
        monkeypatch.delenv(name)
    else:
        monkeypatch.setenv(name, value)
    preloaded = []
    monkeypatch.setattr(main.search_runtime, "preload", lambda: preloaded.append(1))

    with pytest.raises(RuntimeError, match=name):
        with TestClient(main.app):
            pass

    assert preloaded == []


def test_missing_feature_settings_only_warn_with_names(monkeypatch, caplog):
    monkeypatch.delenv("LLM_API_KEY")
    monkeypatch.setenv("JIRA_WEBHOOK_SECRET", "")

    with TestClient(main.app):
        pass

    [message] = warnings(caplog)
    assert "LLM_API_KEY" in message and "JIRA_WEBHOOK_SECRET" in message
    assert "JIRA_EMAIL" not in message and "secret-value" not in message
