"""해결 사례 가이드화 주간 실행기와 GC-09. SQLite 메모리 DB 와 가짜 run_round 만 쓴다 (Claude·임베딩 모델을 부르지 않는다)."""
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.agent.guide.run import DraftRun, JudgeRun
from app.models import GuideAnalysisRun
from app.services import guide_analysis as analysis
from app.utils import datetime_utils
from app.workers import guide_analysis as worker
from test_auth import TABLES, add_user, bearer, client, error_code, login  # noqa: F401
from test_inquiries import create_sqlite_tables

KST = datetime_utils.KST
SLOT = datetime(2026, 11, 9, 0, 0, tzinfo=KST).astimezone(timezone.utc)     # 월요일 00:00
AFTER = SLOT + timedelta(hours=3)
API = "/api/v1/guide-clusters/analysis-status"


@pytest.fixture
def engine():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    create_sqlite_tables(e, TABLES + ["guide_analysis_runs"])
    yield e
    e.dispose()


@pytest.fixture
def db(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture
def factory(engine):
    return lambda: Session(engine)


def add_run(db, status="SUCCEEDED", scheduled_for=SLOT, started=SLOT, finished=None, **fields):
    if status != "RUNNING":
        finished = finished or started + timedelta(minutes=10)
    run = GuideAnalysisRun(scheduled_for=scheduled_for, status=status, started_at=started, finished_at=finished, **fields)
    db.add(run)
    db.commit()
    return run


def runs(db):
    db.expire_all()
    return list(db.scalars(select(GuideAnalysisRun).order_by(GuideAnalysisRun.id)))


# ------------------------------------------------------------------ 회차 계산


@pytest.mark.parametrize("now, expected", [
    (datetime(2026, 11, 9, 0, 0, tzinfo=KST), datetime(2026, 11, 9, tzinfo=KST)),       # 월요일 00:00 정각
    (datetime(2026, 11, 8, 23, 59, tzinfo=KST), datetime(2026, 11, 2, tzinfo=KST)),     # 일요일 밤은 지난주
    (datetime(2026, 11, 8, 15, 30, tzinfo=timezone.utc), datetime(2026, 11, 9, tzinfo=KST)),    # UTC 로는 일요일, KST 는 월요일
])
def test_week_start_is_monday_midnight_kst(now, expected):
    assert datetime_utils.kst_week_start(now) == expected
    assert datetime_utils.kst_next_week_start(now) == expected + timedelta(days=7)


def test_due_without_any_run_catches_up_latest_slot(db):
    """여러 주를 놓쳤어도 가장 최근 회차 하나만."""
    assert analysis.due_slot(db, AFTER + timedelta(days=30)) == datetime_utils.kst_week_start(AFTER + timedelta(days=30))


def test_not_due_after_success_until_next_week(db):
    add_run(db)
    assert analysis.due_slot(db, AFTER) is None
    assert analysis.due_slot(db, SLOT + timedelta(days=7)) == SLOT + timedelta(days=7)


def test_manual_run_does_not_fill_the_slot(db):
    add_run(db, scheduled_for=None)
    assert analysis.due_slot(db, AFTER) == SLOT


def test_not_due_while_another_run_is_running(db):
    add_run(db, "RUNNING", scheduled_for=None, started=AFTER - timedelta(minutes=1))
    assert analysis.due_slot(db, AFTER) is None


def test_failed_slot_retries_after_an_hour(db):
    add_run(db, "FAILED", started=AFTER - timedelta(minutes=40), finished=AFTER - timedelta(minutes=30))
    assert analysis.due_slot(db, AFTER) is None
    assert analysis.due_slot(db, AFTER + timedelta(minutes=31)) == SLOT


def test_failed_slot_gives_up_after_three_attempts_until_next_week(db):
    for _ in range(analysis.MAX_ATTEMPTS):
        add_run(db, "FAILED")
    assert analysis.due_slot(db, AFTER + timedelta(days=1)) is None
    assert analysis.due_slot(db, SLOT + timedelta(days=7)) == SLOT + timedelta(days=7)


def test_stale_running_row_is_closed_and_slot_becomes_due(db):
    add_run(db, "RUNNING", started=SLOT)
    now = SLOT + analysis.STALE_AFTER + timedelta(minutes=1)
    assert analysis.due_slot(db, now) is None             # 방금 닫혔으니 재시도 간격을 지킨다
    row = runs(db)[0]
    assert (row.status, row.error_code) == ("FAILED", "STALE")
    assert analysis.due_slot(db, now + analysis.RETRY_AFTER) == SLOT


# ------------------------------------------------------------------ 겹침 방지


def test_claim_refuses_second_running_row(db):
    assert analysis.claim(db, SLOT, AFTER) is not None
    assert analysis.claim(db, None, AFTER) is None
    assert [r.status for r in runs(db)] == ["RUNNING"]


def test_claim_takes_over_stale_row(db):
    add_run(db, "RUNNING", started=SLOT)
    assert analysis.claim(db, None, SLOT + analysis.STALE_AFTER + timedelta(seconds=1)) is not None
    assert [r.status for r in runs(db)] == ["FAILED", "RUNNING"]


# ------------------------------------------------------------------ 한 회차


def materials(db):
    return "port", "search", "embed"


def test_run_once_passes_materials_and_records_counts(db, factory):
    seen = []

    def runner(session, port, search, embed):
        seen.append((isinstance(session, Session), port, search, embed))
        return JudgeRun(forwarded=[object(), object()], excluded=3, failed=1, sec=2), DraftRun(created=1, attached=1)

    assert analysis.run_once(factory, SLOT, materials=materials, runner=runner) == 0

    assert seen == [(True, "port", "search", "embed")]
    row = runs(db)[0]
    assert (row.status, row.scheduled_for is not None, row.finished_at is not None) == ("SUCCEEDED", True, True)
    assert row.counts == {"forwarded": 2, "excluded": 3, "judge_failed": 1, "sec": 2, "created": 1, "attached": 1,
                          "waiting": 0, "draft_failed": 0}


def test_run_once_failure_closes_row_with_error_kind_only(db, factory):
    def runner(*_):
        raise RuntimeError("티켓 원문이 들어간 메시지")

    assert analysis.run_once(factory, SLOT, materials=materials, runner=runner) == 1
    row = runs(db)[0]
    assert (row.status, row.error_code) == ("FAILED", "RuntimeError")


def test_missing_model_fails_before_running(db, factory):
    """모델 파일이 없으면 티켓마다 검색 실패로 끝나 '성공'으로 남지 않게 회차 실패로 기록한다."""
    called = []

    def broken(_):
        raise FileNotFoundError("모델 없음")

    assert analysis.run_once(factory, SLOT, materials=broken, runner=lambda *a: called.append(a)) == 1
    assert called == []
    assert runs(db)[0].error_code == "FileNotFoundError"


def test_termination_signal_closes_row_and_propagates(db, factory):
    def runner(*_):
        raise SystemExit(143)

    with pytest.raises(SystemExit):
        analysis.run_once(factory, SLOT, materials=materials, runner=runner)
    row = runs(db)[0]
    assert (row.status, row.error_code) == ("FAILED", "SystemExit")


def test_run_once_skips_when_already_running(db, factory):
    add_run(db, "RUNNING", started=datetime_utils.now())
    assert analysis.run_once(factory, SLOT, materials=materials, runner=lambda *a: pytest.fail("돌면 안 된다")) == 0
    assert len(runs(db)) == 1


# ------------------------------------------------------------------ 일정 실행


def test_tick_starts_child_for_due_slot(db, factory, monkeypatch):
    monkeypatch.setattr(datetime_utils, "now", lambda: AFTER)
    commands = []
    worker.tick(factory, threading.Event(), child=lambda c, _: commands.append(c) or 0)

    assert len(commands) == 1
    assert commands[0][1:5] == ["-m", "app.workers.guide_analysis", "--once", "--scheduled-for"]
    assert datetime.fromisoformat(commands[0][5]) == SLOT


def test_tick_does_nothing_when_not_due(db, factory, monkeypatch):
    add_run(db)
    monkeypatch.setattr(datetime_utils, "now", lambda: AFTER)
    worker.tick(factory, threading.Event(), child=lambda *_: pytest.fail("돌면 안 된다"))


def test_tick_closes_row_left_by_killed_child(db, factory):
    def killed(*_):
        add_run(db, "RUNNING", started=datetime_utils.now())
        return -9

    worker.tick(factory, threading.Event(), child=killed)

    row = runs(db)[0]
    assert (row.status, row.error_code) == ("FAILED", "ABORTED")


def test_run_child_terminates_process_on_stop():
    stop = threading.Event()
    stop.set()
    started = time.monotonic()
    code = worker.run_child([sys.executable, "-c", "import time; time.sleep(30)"], stop)
    assert code != 0
    assert time.monotonic() - started < 10


def test_schedule_loop_survives_db_error_and_stops(monkeypatch):
    stop = threading.Event()
    calls = []

    def boom(*_):
        calls.append(1)
        stop.set()
        raise RuntimeError("DB 연결 끊김")

    monkeypatch.setattr(worker, "tick", boom)
    worker.schedule_loop(lambda: None, stop, poll=0.01)
    assert calls == [1]


# ------------------------------------------------------------------ GC-09


@pytest.fixture
def users(client, db):
    for no, role in (("E0001", "EMPLOYEE"), ("E0002", "AGENT"), ("E0009", "ADMIN")):
        add_user(db, no, service_role=role)
    db.commit()
    return {name: bearer(login(client, no)) for name, no in (("employee", "E0001"), ("agent", "E0002"), ("admin", "E0009"))}


@pytest.mark.parametrize("who", ["employee", "agent"])
def test_status_is_admin_only(client, users, who):
    assert error_code(client.get(API, headers=users[who])) == "FORBIDDEN"


def test_status_before_first_run(client, users, monkeypatch):
    monkeypatch.setattr(datetime_utils, "now", lambda: AFTER)
    body = client.get(API, headers=users["admin"]).json()
    assert body == {"lastAnalyzedAt": None, "nextAnalysisAt": "2026-11-16T00:00:00+09:00", "lastRunStatus": None}


def test_status_shows_last_success_and_latest_attempt(client, users, db, monkeypatch):
    add_run(db, started=SLOT)
    add_run(db, "FAILED", scheduled_for=SLOT + timedelta(days=7), started=SLOT + timedelta(days=7))
    monkeypatch.setattr(datetime_utils, "now", lambda: SLOT + timedelta(days=7, hours=1))

    body = client.get(API, headers=users["admin"]).json()

    assert body == {"lastAnalyzedAt": "2026-11-09T00:00:00+09:00", "nextAnalysisAt": "2026-11-23T00:00:00+09:00",
                    "lastRunStatus": "FAILED"}
