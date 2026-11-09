from typing import Annotated

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.session import DbSession
from app.models import SecurityAlert


class SecurityAlertRepository:
    def __init__(self, db: DbSession) -> None:
        self.db = db

    def open_for_update(self, alert_type: str, subject_user_id: int, target_type: str, target_id: int) -> SecurityAlert | None:
        """같은 대상의 종결 전 알림. 합치는 동안 다른 요청이 같은 행을 바꾸지 않게 잠근다."""
        return self.db.scalar(
            select(SecurityAlert).where(
                SecurityAlert.alert_type == alert_type,
                SecurityAlert.subject_user_id == subject_user_id,
                SecurityAlert.target_type == target_type,
                SecurityAlert.target_id == target_id,
                SecurityAlert.status != "CLOSED",
            ).with_for_update()
        )

    def add_open(self, alert: SecurityAlert) -> bool:
        """새 열린 알림을 넣는다. 같은 대상의 열린 알림이 먼저 생겼으면(UNIQUE) 넣지 않고 False.

        savepoint 안에서 넣으므로 실패해도 호출자의 트랜잭션(원천 기록 등)은 그대로다.
        """
        try:
            with self.db.begin_nested():
                self.db.add(alert)
            return True
        except IntegrityError:
            return False


SecurityAlertRepositoryDep = Annotated[SecurityAlertRepository, Depends(SecurityAlertRepository)]
