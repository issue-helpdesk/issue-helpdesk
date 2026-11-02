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

# 생성·배정·상태 변경 연결 및 한 작업의 실패 격리
from test_jira_assign_service import (assign_db, make_assignment, FakeAssignment, ACCOUNT)  # noqa: E402,F401
from test_jira_transition_service import (transition_db, make_transition, Workflow, NOW)  # noqa: E402,F401
from app.models import Base, TicketStatusHistory  # noqa: E402
from app.services import jira_create, jira_assign, jira_transition  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402


def test_round_consumes_assignment_and_confirms_db(assign_db):
    ticket, job = make_assignment(assign_db)
    jira = FakeAssignment()
    report = worker.run_round(assign_db, jira.client(), now=NOW)
    assert not report.errors
    assert report.result_types == ['JIRA_ASSIGN']
    assert [r.outcome for r in report.results] == ['ASSIGNED']
    assert reload(assign_db, Ticket, ticket.id).assign_status == 'ASSIGNED'
    assert reload(assign_db, IntegrationJob, job.id).status == 'DONE'
    assert jira.puts == 1


def test_round_consumes_transition_and_confirms_history(transition_db):
    ticket, job = make_transition(transition_db)
    jira = Workflow()
    report = worker.run_round(transition_db, jira.client(), now=NOW)
    assert not report.errors
    assert report.result_types == ['JIRA_TRANSITION']
    assert [r.outcome for r in report.results] == ['CONFIRMED']
    assert reload(transition_db, Ticket, ticket.id).work_status == 'WIP'
    assert transition_db.query(TicketStatusHistory).count() == 1
    assert jira.transitions == 1


@pytest.mark.parametrize('kind', ['JIRA_ASSIGN', 'JIRA_TRANSITION'])
def test_round_recovers_stale_writes_by_lookup_without_sending_again(assign_db, kind):
    db = assign_db
    if kind == 'JIRA_ASSIGN':
        ticket, job = make_assignment(db)
        jira = FakeAssignment(ACCOUNT)
    else:
        Base.metadata.tables['ticket_status_history'].create(db.bind)
        ticket, job = make_transition(db)
        jira = Workflow('WIP')
        jira.histories = [{'created': NOW.isoformat(), 'items': [
            {'field': 'status', 'from': '10004', 'to': '10005'}]}]
    job.status, job.updated_at = 'RUNNING', T0 - timedelta(minutes=10)
    db.commit()
    report = worker.run_round(db, jira.client(), now=NOW)
    assert not report.errors and report.requeued == 1
    assert reload(db, IntegrationJob, job.id).status == 'DONE'
    assert not any(m in ('POST', 'PUT') for m, p in jira.calls)


def test_deferred_reopens_do_not_starve_later_transitions(transition_db):
    db = transition_db
    ticket, job = make_transition(db, 'FIN', 'WIP')
    # 정상 전환을 더 뒤 ID로 넣고 limit=1로 실행한다.
    t2 = make_ticket(db, id=43, draft_id=56, receipt_no='RCPT-0043', jira_key='ITHD-43',
                     jira_sync_status='SYNCED', work_status='RDY', requested_work_status='WIP', transition_status='PENDING')
    payload = {**job.payload, 'ticketId': 43, 'receiptNo': t2.receipt_no, 'jiraKey': t2.jira_key,
               'fromStatus': 'RDY', 'toStatus': 'WIP', 'requestedBy': 18}
    normal = jira_transition.enqueue_jira_transition(db, t2, payload)
    db.commit()
    jira = Workflow()
    report = worker.run_round(db, jira.client(), now=NOW, limit=1)
    assert not report.errors and report.deferred == 1
    assert [r.job_id for r in report.results] == [normal.id]
    assert reload(db, IntegrationJob, job.id).status == 'PENDING'
    assert reload(db, IntegrationJob, job.id).attempts == 0
    assert reload(db, Ticket, ticket.id).work_status == 'FIN'
    assert reload(db, Ticket, 43).work_status == 'WIP'


@pytest.mark.parametrize('kind', worker.JOB_TYPES)
def test_ticket_scope_excludes_other_pending_and_stale_jobs(db, kind):
    mine = make_ticket(db)
    other = make_ticket(db, id=43, draft_id=56, receipt_no='RCPT-0043')
    # 외부 호출 없이 malformed 작업을 서비스가 NEEDS_ADMIN으로 처리하게 한다.
    for t in (mine, other):
        db.add(IntegrationJob(ticket_id=t.id, job_type=kind, status='RUNNING', attempts=1,
                              idempotency_key=f'{kind}:{t.id}', payload={}, updated_at=T0-timedelta(minutes=10)))
    db.commit()
    jira = FakeJira()
    report = worker.run_round(db, jira.client(), now=T0, ticket_id=mine.id, job_types=(kind,))
    assert not report.errors and report.requeued == 1
    untouched = db.query(IntegrationJob).filter_by(ticket_id=other.id).one()
    assert (untouched.status, untouched.attempts, untouched.last_error) == ('RUNNING', 1, None)


def test_unexpected_job_error_rolls_back_and_runs_remaining_jobs_and_types(assign_db, monkeypatch):
    db = assign_db
    t1 = make_ticket(db)
    t2 = make_ticket(db, id=43, draft_id=56, receipt_no='RCPT-0043')
    make_job(db, t1)
    make_job(db, t2)
    seen = []
    real = jira_create.run_jira_create_job
    def fail_first(db, jira, job_id, **kw):
        seen.append(job_id)
        if len(seen) == 1:
            db.execute(__import__('sqlalchemy').text('select 1'))
            raise OperationalError('COMMIT', {}, Exception('DB unavailable'))
        return real(db, jira, job_id, **kw)
    monkeypatch.setattr(jira_create, 'run_jira_create_job', fail_first)
    _, assignment = make_assignment(db, id=44, draft_id=57, receipt_no='RCPT-0044')
    monkeypatch.setattr(jira_assign, 'run_jira_assign_job', lambda db, jira, job_id, **kw:
                        jira_assign.AssignmentResult(job_id, 'SKIPPED'))
    jira = FakeJira()
    report = worker.run_round(db, jira.client(), now=T0)
    assert len(report.errors) == 1 and len(seen) == 2
    # 생성에 성공한 t2는 최초 자동배정(#181)이 JIRA_ASSIGN 작업을 하나 더 등록하므로 같은 회차에 배정 2건이 돈다
    assert report.result_types == ['JIRA_CREATE', 'JIRA_ASSIGN', 'JIRA_ASSIGN']
    assert [r.outcome for r in report.results] == ['CREATED', 'SKIPPED', 'SKIPPED']


def test_selected_job_type_does_not_process_other_kind(assign_db):
    ticket, job = make_assignment(assign_db)
    report = worker.run_round(assign_db, FakeAssignment().client(), now=NOW, job_types=('JIRA_CREATE',))
    assert not report.errors and not report.results
    assert reload(assign_db, IntegrationJob, job.id).status == 'PENDING'


def test_once_returns_failure_if_round_reports_unexpected_errors(monkeypatch):
    monkeypatch.setattr(worker, 'run_round', lambda *a, **kw: worker.RoundReport(0, [], errors=['JIRA_ASSIGN:1:OperationalError']))
    stop = threading.Event()
    code = worker.run_loop(_Session(stop, stop_after=99), None, interval=0, limit=1,
                           stale_after=timedelta(minutes=5), stop=stop, once=True)
    assert code == 1


@pytest.mark.parametrize('args', [['--limit','0'], ['--interval','0'], ['--stale-minutes','0'], ['--ticket-id','0']])
def test_cli_rejects_nonpositive_values_before_connecting(args):
    with pytest.raises(SystemExit) as exc:
        worker.main(args)
    assert exc.value.code == 2
