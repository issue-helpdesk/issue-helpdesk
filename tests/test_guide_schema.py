"""해결 사례 가이드화 표(guide_clusters·ticket_guide_states)의 제약과 마이그레이션을 DB 없이 검사한다."""
import os
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from app.models import GuideCluster, TicketGuideState
from test_auth import bigint_as_integer  # noqa: F401  (SQLite 에서 BigInteger 자동 증가)
from test_inquiries import create_sqlite_tables

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
CLUSTERS, STATES = GuideCluster.__table__, TicketGuideState.__table__


@pytest.fixture
def conn():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    create_sqlite_tables(engine, ['guide_clusters', 'ticket_guide_states'])
    with engine.begin() as c:
        yield c
    engine.dispose()


def cluster(conn, **values):
    row = {'category_code': 'NET', 'judgment': 'ADD_ITEM', 'title': 'VPN 연결 시 인터넷 끊김', **values}
    return conn.execute(insert(CLUSTERS).values(**row)).inserted_primary_key[0]


def state(conn, ticket_id=1, **values):
    conn.execute(insert(STATES).values(ticket_id=ticket_id, **values))


def rejects(conn, fn, *args, **values):
    nested = conn.begin_nested()
    with pytest.raises(IntegrityError):
        fn(conn, *args, **values)
    nested.rollback()


def test_cluster_defaults_and_rules(conn):
    cid = cluster(conn)
    row = conn.execute(CLUSTERS.select().where(CLUSTERS.c.id == cid)).mappings().one()
    assert (row['status'], row['draft_revision'], row['draft_basis']) == ('REVIEWING', 0, None)
    cluster(conn, status='REJECTED', reject_reason='이미 매뉴얼에 있음')
    rejects(conn, cluster, status='REJECTED')                 # 거절은 사유가 있어야 한다
    rejects(conn, cluster, judgment='UNKNOWN')
    rejects(conn, cluster, status='WAITING')                  # 대기는 티켓 상태다
    rejects(conn, cluster, draft_revision=-1)


def test_ticket_state_cluster_and_exclude_refs(conn):
    cid = cluster(conn)
    state(conn, 1, status='REVIEWING', cluster_id=cid)
    state(conn, 2, status='WAITING')
    state(conn, 3, status='EXCLUDED', exclude_reason='특정 층 AP 재부팅 (일회성)')
    state(conn, 4, fail_code='LLM_TIMEOUT', fail_count=2)     # 아직 판단 못 받음 = 상태 없음, 실패 기록만
    rejects(conn, state, 5, status='APPLIED')                 # 묶음 상태는 묶음이 있어야 한다
    rejects(conn, state, 6, status='WAITING', cluster_id=cid)  # 대기·제외는 묶음에 붙지 않는다
    rejects(conn, state, 7, status='EXCLUDED')                # 제외는 이유가 있어야 한다
    rejects(conn, state, 8, status='WAITING', exclude_reason='x')
    rejects(conn, state, 9, status='DONE')
    rejects(conn, state, 10, fail_count=-1)
    rejects(conn, state, 1, status='WAITING')                 # 티켓당 한 행


def test_migration_sql_offline():
    """두 표를 만들고 tickets 는 건드리지 않는다. 기존 티켓은 행이 없다 (백필 없음)."""
    env = {**os.environ, 'DATABASE_URL': 'postgresql://u:p@localhost/offline', 'PYTHONIOENCODING': 'utf-8'}
    out = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'b5d1e8a3c702:d3a7f2c9e184', '--sql'],
                         cwd=os.path.join(ROOT, 'backend'), env=env, capture_output=True, text=True,
                         encoding='utf-8', check=True).stdout
    steps = ['CREATE TABLE guide_clusters', 'ix_guide_clusters_registered_version_id', 'CREATE TABLE ticket_guide_states',
             'ix_ticket_guide_states_cluster_id', 'COMMIT']
    pos = [out.find(s) for s in steps]
    assert all(i >= 0 for i in pos) and pos == sorted(pos), dict(zip(steps, pos))
    lowered = out.lower()
    assert 'alter table tickets' not in lowered and 'insert into ticket_guide_states' not in lowered
    # 모델 제약 이름이 마이그레이션과 같아야 나중에 이름으로 고칠 수 있다
    for table in (CLUSTERS, STATES):
        for c in table.constraints:
            if c.name and str(c.name).startswith(('ck_', 'fk_')):
                assert str(c.name) in out, c.name
