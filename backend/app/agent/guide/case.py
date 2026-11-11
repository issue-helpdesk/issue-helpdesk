"""case_guide 함수 연결 (open_basis · ticket_warnings).

이 함수들은 psycopg 연결(`%s` 형식)을 받는다. 워커는 SQLAlchemy Session 을 쓰므로, API(services/guide_cluster.py)와
같은 방법(`session.connection().connection.driver_connection`)으로 같은 트랜잭션의 연결을 넘긴다.
모두 DB 를 읽기만 하고 commit 하지 않는다. 시험(SQLite)에서는 가짜 함수를 넣는다.
"""
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class CaseFns:
    open_basis: Callable[..., dict]                     # (판단, **인자) → {'draft_basis', 'draft_md', 'warnings'}
    ticket_warnings: Callable[[list[int]], list[str]]

    @classmethod
    def for_session(cls, session: Session) -> 'CaseFns':
        from app.rag.case_guide.open_basis import open_basis, ticket_warnings

        def conn():                                     # 티켓마다 커밋하므로 부를 때마다 지금 연결을 꺼낸다
            return session.connection().connection.driver_connection

        return cls(open_basis=lambda judgment, **kw: open_basis(conn(), judgment, **kw),
                   ticket_warnings=lambda ids: ticket_warnings(conn(), ids))
