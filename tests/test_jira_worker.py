"""독립 실행기(integrations/jira/worker.py) — SQLite 메모리 DB + Jira 모의 응답. 실제 Jira 호출 없음."""

import threading
from datetime import timedelta

import pytest

from app.integrations.jira import worker
from app.models import IntegrationJob, Ticket
import httpx

from test_jira_create_service import FakeJira as _BaseJira, POST_ISSUE, T0, db, make_job, make_ticket, reload  # noqa: F401  (db 는 fixture)


class FakeJira(_BaseJira):
    """생성할 때마다 다른 키를 준다 (기본 모의 서버는 항상 ITHD-999 라서 두 번째 접수가 키 충돌로 걸린다)."""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        response = super().__call__(request)
        if (request.method, request.url.path) == POST_ISSUE and response.status_code == 201:
            n = self.calls.count(POST_ISSUE)
            return httpx.Response(201, json={"id": str(20000 + n), "key": f"ITHD-{900 + n}"})
        return response


def test_round_runs_due_jobs_oldest_first_and_summarizes(db):
    t1 = make_ticket(db, id=42, receipt_no="RCPT-0042", draft_id=142)
    t2 = make_ticket(db, id=43, receipt_no="RCPT-0043", draft_id=143)
    make_job(db, t1)
    make_job(db, t2)
    jira = FakeJira()

    report = worker.run_round(db, jira.client(), now=T0)

    assert [r.outcome for r in report.results] == ["CREATED", "CREATED"]
    assert report.requeued == 0 and "CREATED 2" in report.summary()
    assert jira.posts == 2


def test_round_respects_limit_and_leaves_rest_pending(db):
    for i in (42, 43, 44):
        make_job(db, make_ticket(db, id=i, receipt_no=f"RCPT-{i:04d}", draft_id=100 + i))
    jira = FakeJira()

    report = worker.run_round(db, jira.client(), limit=2, now=T0)

    assert len(report.results) == 2
    pending = db.query(IntegrationJob).filter_by(status="PENDING").count()
    assert pending == 1


def test_round_skips_job_not_yet_due(db):
    ticket = make_ticket(db)
    make_job(db, ticket, next_retry_at=T0 + timedelta(minutes=3))
    jira = FakeJira()

    report = worker.run_round(db, jira.client(), now=T0)

    assert report.results == [] and jira.posts == 0
    assert "처리할 작업 없음" in report.summary()


def test_stale_running_job_is_requeued_then_only_looked_up(db):
    """방치된 RUNNING 작업은 새로 만들지 않고 Jira에서 찾기만 한다(중복 이슈 방지)."""
    ticket = make_ticket(db)
    job = make_job(db, ticket, status="RUNNING", updated_at=T0 - timedelta(minutes=10))
    jira = FakeJira(existing=True)

    report = worker.run_round(db, jira.client(), now=T0)

    assert report.requeued == 1
    assert [r.outcome for r in report.results] == ["LINKED"]
    assert jira.posts == 0                                           # POST(생성)는 한 번도 없음
    assert reload(db, Ticket, 42).jira_key == "ITHD-77"
    assert reload(db, IntegrationJob, job.id).status == "DONE"


def test_recent_running_job_is_left_alone(db):
    ticket = make_ticket(db)
    make_job(db, ticket, status="RUNNING", updated_at=T0 - timedelta(minutes=1))
    jira = FakeJira()

    report = worker.run_round(db, jira.client(), now=T0)

    assert report.requeued == 0 and report.results == [] and jira.posts == 0


# ------------------------------------------------------------------ 반복 · 종료

class _Session:
    """run_loop 에 넘길 session_factory 용 가짜. 호출 횟수를 세고, 지정한 번째 호출에서 예외를 낸다."""

    def __init__(self, stop, *, fail_on=(), stop_after=2):
        self.calls, self.fail_on, self.stop_after, self.stop = 0, set(fail_on), stop_after, stop

    def __call__(self):
        self.calls += 1
        if self.calls >= self.stop_after:
            self.stop.set()
        if self.calls in self.fail_on:
            raise RuntimeError("DB 끊김")
        return _Ctx()


class _Ctx:
    def __enter__(self):
        return object()

    def __exit__(self, *a):
        return False


@pytest.fixture
def fake_round(monkeypatch):
    seen = []
    monkeypatch.setattr(worker, "run_round", lambda db, jira, **kw: seen.append(kw) or worker.RoundReport(0, []))
    return seen


def test_loop_keeps_going_after_an_error(fake_round):
    stop = threading.Event()
    factory = _Session(stop, fail_on={1}, stop_after=3)

    code = worker.run_loop(factory, None, interval=0, limit=5, stale_after=timedelta(minutes=5), stop=stop)

    assert code == 0
    assert factory.calls == 3                      # 1회차 실패 후에도 계속 돌았다
    assert len(fake_round) == 2                    # 실패한 회차는 run_round 까지 못 갔다
    assert fake_round[0]["limit"] == 5


def test_once_returns_zero_on_success_and_one_on_error(fake_round):
    stop = threading.Event()
    assert worker.run_loop(_Session(stop, stop_after=99), None, interval=0, limit=1, stale_after=timedelta(0), stop=stop, once=True) == 0
    assert len(fake_round) == 1
    stop2 = threading.Event()
    assert worker.run_loop(_Session(stop2, fail_on={1}, stop_after=99), None, interval=0, limit=1, stale_after=timedelta(0), stop=stop2, once=True) == 1


def test_loop_stops_when_stop_is_already_set(fake_round):
    stop = threading.Event()
    stop.set()
    factory = _Session(stop)
    assert worker.run_loop(factory, None, interval=0, limit=1, stale_after=timedelta(0), stop=stop) == 0
    assert factory.calls == 0
