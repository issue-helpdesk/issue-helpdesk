from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AdminAuth
from app.schemas.common import Page
from app.schemas.guide_cluster import GuideClusterDetail, GuideClusterListQuery, GuideClusterSummary
from app.services.guide_cluster import GuideClusterServiceDep

router = APIRouter(prefix="/guide-clusters", tags=["guide-clusters"])


@router.get("", response_model=Page[GuideClusterSummary])
def list_clusters(
    query: Annotated[GuideClusterListQuery, Query()], _: AdminAuth, service: GuideClusterServiceDep,
) -> Page[GuideClusterSummary]:
    return service.list_clusters(query)


@router.get("/{cluster_id}", response_model=GuideClusterDetail)
def get_cluster(cluster_id: int, _: AdminAuth, service: GuideClusterServiceDep) -> GuideClusterDetail:
    return service.get_cluster(cluster_id)
