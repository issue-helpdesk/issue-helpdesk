from datetime import datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy import update

from app.db.session import DbSession
from app.models import AuthSession


class AuthSessionRepository:
    def __init__(self, db: DbSession) -> None:
        self.db = db

    def add(self, session: AuthSession) -> AuthSession:
        self.db.add(session)
        self.db.flush()
        return session

    def get(self, session_id: int) -> AuthSession | None:
        return self.db.get(AuthSession, session_id)

    def get_for_update(self, session_id: int) -> AuthSession | None:
        return self.db.get(AuthSession, session_id, with_for_update=True)

    def revoke_all(self, user_id: int, reason: str, now: datetime) -> None:
        self.db.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now, revoke_reason=reason)
            .execution_options(synchronize_session="fetch")
        )


AuthSessionRepositoryDep = Annotated[AuthSessionRepository, Depends(AuthSessionRepository)]
