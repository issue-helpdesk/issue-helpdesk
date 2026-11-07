"""해결 사례 가이드화 (기획_해결사례_가이드화, SRS GUIDE-03·08). 모두 ITssue DB 에만 두고 Jira 로 보내지 않는다.

guide_clusters      : 주간 분석이 묶은 해결 티켓 묶음과 그 초안·검토 정보·등록 연결
ticket_guide_states : 티켓별 가이드화 상태. tickets(Jira 연동)와 나눠 둔다. 행이 없으면 아직 분석하지 않은 티켓이다
"""
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Identity, Integer, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

CLUSTER_JUDGMENTS = ("ADD_ITEM", "CHANGE", "NEW_GUIDE", "MANUAL_CANDIDATE", "SEC_MANUAL")
CLUSTER_STATUSES = ("REVIEWING", "APPLIED", "REJECTED")
TICKET_GUIDE_STATUSES = ("WAITING", "EXCLUDED", "REVIEWING", "APPLIED", "REJECTED")
IN_CLUSTER = "('REVIEWING', 'APPLIED', 'REJECTED')"     # 묶음에 속한 티켓의 상태 = 그 묶음의 상태


def _values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class GuideCluster(Base):
    """묶음 하나. 등록하면 근거 티켓을 고정하고, 현행 전환 때 이 묶음과 티켓을 APPLIED 로 바꾼다."""
    __tablename__ = "guide_clusters"
    __table_args__ = (
        CheckConstraint(f"judgment in ({_values(CLUSTER_JUDGMENTS)})", name="judgment"),
        CheckConstraint(f"status in ({_values(CLUSTER_STATUSES)})", name="status"),
        CheckConstraint("status <> 'REJECTED' or reject_reason is not null", name="reject_ref"),
        CheckConstraint("draft_revision >= 0", name="draft_revision"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    category_code: Mapped[str] = mapped_column(ForeignKey("categories.code"))
    judgment: Mapped[str]
    status: Mapped[str] = mapped_column(server_default=text("'REVIEWING'"))
    title: Mapped[str]                                                          # 목록에 보여 줄 주제
    # 새 가이드는 문서 등록(DC-02) 전까지 둘 다 비어 있다
    target_document_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_documents.id"))
    base_version_id: Mapped[int | None] = mapped_column(ForeignKey("document_versions.id"))
    # 기본값은 PostgreSQL 이 jsonb 로 저장한다 (SQLite 테스트도 만들 수 있게 캐스트 없이 씀)
    compared_items: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'"))   # 판단에 쓴 문서·버전·항목 번호
    draft_md: Mapped[str | None]                                                # 매뉴얼 후보는 비어 있다
    # 등록 검사에 쓰는 초안 기준: 기준 md 원문, 등록될 버전, 새 항목 번호, 이어 쓰는 초안 버전 id·파일 경로.
    # 등록할 때만 읽고 화면에 내려 주지 않는다. 초안이 없는 매뉴얼 후보는 비어 있다
    draft_basis: Mapped[dict | None] = mapped_column(JSONB)
    review_info: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"))  # 판단 이유·경고·추정 표시 등 (docs/08)
    draft_revision: Mapped[int] = mapped_column(Integer, server_default=text("0"))  # 저장마다 1 증가. 다른 관리자 변경 확인
    # UNIQUE 아님: 같은 가이드의 사례 초안은 이어 쓰므로 여러 묶음이 한 버전을 가리킬 수 있다
    registered_version_id: Mapped[int | None] = mapped_column(ForeignKey("document_versions.id"), index=True)
    reject_reason: Mapped[str | None]
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))    # 거절·반영 표시한 관리자
    reviewed_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())   # 분석일
    updated_at: Mapped[datetime | None]


class TicketGuideState(Base):
    """티켓 하나의 가이드화 상태 (tickets 와 1:1). 분석에 성공하거나 실패하면 행을 만든다.

    status 가 비어 있으면 분석을 시도했지만 아직 판단을 받지 못한 티켓이다 (실패 기록만 있음).
    """
    __tablename__ = "ticket_guide_states"
    __table_args__ = (
        CheckConstraint(f"status in ({_values(TICKET_GUIDE_STATUSES)})", name="status"),
        CheckConstraint(f"(status in {IN_CLUSTER}) = (cluster_id is not null)", name="cluster_ref"),
        CheckConstraint("(status = 'EXCLUDED') = (exclude_reason is not null)", name="exclude_ref"),
        CheckConstraint("fail_count >= 0", name="fail_count"),
    )

    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), primary_key=True)
    status: Mapped[str | None]
    cluster_id: Mapped[int | None] = mapped_column(ForeignKey("guide_clusters.id"), index=True)
    fail_code: Mapped[str | None]                       # 마지막 실패 사유. 오류 코드만
    fail_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))   # 성공하면 0
    exclude_reason: Mapped[str | None]                  # AI 가 제외한 이유. EXCLUDED 일 때만
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
