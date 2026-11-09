from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AdminAuth
from app.schemas.common import Page
from app.schemas.guide_cluster import (
    GuideClusterDetail,
    GuideClusterDraftUpdateRequest,
    GuideClusterListQuery,
    GuideClusterRegisterRequest,
    GuideClusterRegisterResponse,
    GuideClusterRejectRequest,
    GuideClusterSummary,
)
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


@router.patch("/{cluster_id}", response_model=GuideClusterDetail)
def save_draft(
    cluster_id: int, body: GuideClusterDraftUpdateRequest, _: AdminAuth, service: GuideClusterServiceDep,
) -> GuideClusterDetail:
    """초안 글 저장. draftRevision 이 다르면 409 (다른 관리자가 먼저 고침)."""
    return service.save_draft(cluster_id, body.draft_md, body.draft_revision)


@router.post("/{cluster_id}/register", response_model=GuideClusterRegisterResponse)
def register_cluster(
    cluster_id: int, body: GuideClusterRegisterRequest, auth: AdminAuth, service: GuideClusterServiceDep,
) -> GuideClusterRegisterResponse:
    """초안을 가이드의 현행이 아닌 버전으로 등록한다. 검색 준비는 백그라운드로 돌고, 현행 전환은 DC-09 로 한다."""
    return service.register(cluster_id, body.draft_revision, body.view_scope, body.transfer_policy, auth.user)


@router.post("/{cluster_id}/reject", response_model=GuideClusterDetail)
def reject_cluster(
    cluster_id: int, body: GuideClusterRejectRequest, auth: AdminAuth, service: GuideClusterServiceDep,
) -> GuideClusterDetail:
    return service.reject(cluster_id, body.reason, auth.user)


@router.post("/{cluster_id}/apply", response_model=GuideClusterDetail)
def mark_cluster_applied(cluster_id: int, auth: AdminAuth, service: GuideClusterServiceDep) -> GuideClusterDetail:
    """관리자가 직접 반영한 묶음(주로 매뉴얼 후보)을 반영 표시한다. 등록한 묶음은 DC-09 현행 전환으로 반영된다."""
    return service.mark_applied(cluster_id, auth.user)
