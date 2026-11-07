from typing import Annotated

from fastapi import Depends
from sqlalchemy import func, select, update
from sqlalchemy.orm import aliased

from app.db.session import DbSession
from app.models import Category, DocumentVersion, GuideCluster, KnowledgeDocument, Ticket, TicketGuideState
from app.utils import datetime_utils

RegisteredVersion = aliased(DocumentVersion)


class GuideClusterRepository:
    def __init__(self, db: DbSession) -> None:
        self.db = db

    def search(
        self, category_codes: list[str], judgments: list[str], statuses: list[str], offset: int, limit: int,
    ) -> tuple[list[tuple], int]:
        """(묶음, 분류, 넣을 문서, 등록 버전, 티켓 수). 티켓 많은 순 → 분석일 최신순 (기획: 건수 많은 순)."""
        conditions = []
        if category_codes:
            conditions.append(GuideCluster.category_code.in_(category_codes))
        if judgments:
            conditions.append(GuideCluster.judgment.in_(judgments))
        if statuses:
            conditions.append(GuideCluster.status.in_(statuses))
        total = self.db.scalar(select(func.count()).select_from(GuideCluster).where(*conditions))
        counts = (select(TicketGuideState.cluster_id, func.count().label("n"))
                  .where(TicketGuideState.cluster_id.is_not(None))
                  .group_by(TicketGuideState.cluster_id).subquery())
        ticket_count = func.coalesce(counts.c.n, 0)
        rows = self.db.execute(
            select(GuideCluster, Category, KnowledgeDocument, RegisteredVersion, ticket_count)
            .join(Category, Category.code == GuideCluster.category_code)
            .outerjoin(KnowledgeDocument, KnowledgeDocument.id == GuideCluster.target_document_id)
            .outerjoin(RegisteredVersion, RegisteredVersion.id == GuideCluster.registered_version_id)
            .outerjoin(counts, counts.c.cluster_id == GuideCluster.id)
            .where(*conditions)
            .order_by(ticket_count.desc(), GuideCluster.created_at.desc(), GuideCluster.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return [tuple(r) for r in rows], total

    def get(self, cluster_id: int) -> GuideCluster | None:
        return self.db.get(GuideCluster, cluster_id)

    def get_for_update(self, cluster_id: int) -> GuideCluster | None:
        """잠금 순서는 문서 → 버전 → 묶음이다 (DC-09 와 같다). 문서를 먼저 잠근 뒤 부른다."""
        return self.db.get(GuideCluster, cluster_id, with_for_update=True, populate_existing=True)

    def tickets(self, cluster_id: int) -> list[Ticket]:
        """근거 티켓. 해결 확인 시각 순."""
        return list(self.db.scalars(
            select(Ticket).join(TicketGuideState, TicketGuideState.ticket_id == Ticket.id)
            .where(TicketGuideState.cluster_id == cluster_id)
            .order_by(Ticket.closed_at, Ticket.id)
        ))

    def registered_to(self, version_id: int) -> list[GuideCluster]:
        """이 버전에 등록한 묶음. 현행 전환 검사 동안 거절·수정이 끼어들지 않게 잠근다."""
        return list(self.db.scalars(
            select(GuideCluster).where(GuideCluster.registered_version_id == version_id)
            .order_by(GuideCluster.id).with_for_update()
        ))

    def mark_applied(self, clusters: list[GuideCluster]) -> None:
        self.change_status(clusters, "APPLIED")

    def change_status(self, clusters: list[GuideCluster], status: str) -> None:
        """묶음과 소속 티켓의 상태를 함께 바꾼다. 티켓 상태는 묶음 상태와 같아야 한다 (06 H장)."""
        if not clusters:
            return
        now = datetime_utils.now()
        for cluster in clusters:
            cluster.status, cluster.updated_at = status, now
        self.db.execute(
            update(TicketGuideState)
            .where(TicketGuideState.cluster_id.in_([c.id for c in clusters]))
            .values(status=status, updated_at=now)
        )


GuideClusterRepositoryDep = Annotated[GuideClusterRepository, Depends(GuideClusterRepository)]
