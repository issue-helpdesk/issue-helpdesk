from typing import Annotated

from fastapi import Depends
from sqlalchemy import select, update

from app.db.session import DbSession
from app.models import GuideCluster, TicketGuideState
from app.utils import datetime_utils


class GuideClusterRepository:
    def __init__(self, db: DbSession) -> None:
        self.db = db

    def registered_to(self, version_id: int) -> list[GuideCluster]:
        """이 버전에 등록한 묶음. 현행 전환 검사 동안 거절·수정이 끼어들지 않게 잠근다."""
        return list(self.db.scalars(
            select(GuideCluster).where(GuideCluster.registered_version_id == version_id)
            .order_by(GuideCluster.id).with_for_update()
        ))

    def mark_applied(self, clusters: list[GuideCluster]) -> None:
        """묶음과 소속 티켓을 함께 APPLIED 로. 티켓 상태는 묶음 상태와 같아야 한다 (06 H장)."""
        if not clusters:
            return
        now = datetime_utils.now()
        for cluster in clusters:
            cluster.status, cluster.updated_at = "APPLIED", now
        self.db.execute(
            update(TicketGuideState)
            .where(TicketGuideState.cluster_id.in_([c.id for c in clusters]))
            .values(status="APPLIED", updated_at=now)
        )


GuideClusterRepositoryDep = Annotated[GuideClusterRepository, Depends(GuideClusterRepository)]
