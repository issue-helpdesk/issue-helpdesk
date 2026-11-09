from datetime import datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy import select, update

from app.db.session import DbSession
from app.models import GuideAnalysisRun


class GuideAnalysisRunRepository:
    def __init__(self, db: DbSession) -> None:
        self.db = db

    def latest(self) -> GuideAnalysisRun | None:
        return self.db.scalar(select(GuideAnalysisRun).order_by(GuideAnalysisRun.id.desc()).limit(1))

    def latest_succeeded(self) -> GuideAnalysisRun | None:
        return self.db.scalar(select(GuideAnalysisRun).where(GuideAnalysisRun.status == "SUCCEEDED")
                              .order_by(GuideAnalysisRun.id.desc()).limit(1))

    def running(self) -> GuideAnalysisRun | None:
        return self.db.scalar(select(GuideAnalysisRun).where(GuideAnalysisRun.status == "RUNNING"))

    def for_schedule(self, scheduled_for: datetime) -> list[GuideAnalysisRun]:
        """이 회차의 시도들, 오래된 순. 직접 실행(scheduled_for 없음)은 회차에 들어가지 않는다."""
        return list(self.db.scalars(select(GuideAnalysisRun).where(GuideAnalysisRun.scheduled_for == scheduled_for)
                                    .order_by(GuideAnalysisRun.id)))

    def add_running(self, scheduled_for: datetime | None, now: datetime) -> GuideAnalysisRun:
        """실행 중인 행은 하나뿐이다 (부분 UNIQUE). 이미 있으면 flush 에서 IntegrityError."""
        run = GuideAnalysisRun(scheduled_for=scheduled_for, status="RUNNING", started_at=now)
        self.db.add(run)
        self.db.flush()
        return run

    def finish(
        self, run_id: int, status: str, now: datetime, counts: dict | None = None, error_code: str | None = None,
    ) -> None:
        run = self.db.get(GuideAnalysisRun, run_id)
        run.status, run.finished_at, run.error_code = status, now, error_code
        if counts is not None:
            run.counts = counts

    def fail_running(self, code: str, now: datetime, *, before: datetime | None = None,
                     since: datetime | None = None) -> int:
        """실행 중으로 남은 행을 실패로 닫는다. before: 이 시각 전에 시작한 행만, since: 이 시각 뒤에 시작한 행만."""
        stmt = update(GuideAnalysisRun).where(GuideAnalysisRun.status == "RUNNING")
        if before is not None:
            stmt = stmt.where(GuideAnalysisRun.started_at < before)
        if since is not None:
            stmt = stmt.where(GuideAnalysisRun.started_at >= since)
        return self.db.execute(stmt.values(status="FAILED", finished_at=now, error_code=code)).rowcount


GuideAnalysisRunRepositoryDep = Annotated[GuideAnalysisRunRepository, Depends(GuideAnalysisRunRepository)]
