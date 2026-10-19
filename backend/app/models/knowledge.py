from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Identity, Index, Integer, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

VIEW_SCOPE = "view_scope in ('ALL', 'AGENT', 'ADMIN')"
TRANSFER_POLICY = "transfer_policy in ('ALLOWED', 'MASKED', 'BLOCKED')"


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        CheckConstraint("doc_type in ('GUIDE', 'FAQ', 'MANUAL', 'STANDARD')", name="doc_type"),   # STANDARD: 공통 기준
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    doc_code: Mapped[str] = mapped_column(unique=True)
    doc_type: Mapped[str]
    title: Mapped[str]
    category_code: Mapped[str | None] = mapped_column(ForeignKey("categories.code"))
    owner_group_id: Mapped[int | None] = mapped_column(ForeignKey("support_groups.id"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version", name="uq_document_versions_document_id_version"),
        CheckConstraint("file_format in ('PDF', 'DOCX', 'PPTX', 'MD', 'TEXT')", name="file_format"),
        CheckConstraint(VIEW_SCOPE, name="view_scope"),
        CheckConstraint(TRANSFER_POLICY, name="transfer_policy"),
        CheckConstraint("ingest_status in ('PENDING', 'DONE', 'FAILED')", name="ingest_status"),
        # 현행 버전은 문서마다 최대 하나, 적재가 끝난 버전만 현행 (SRS GUIDE-05)
        CheckConstraint("not is_current or ingest_status = 'DONE'", name="current_needs_done"),
        Index("uq_document_versions_one_current", "document_id", unique=True, postgresql_where=text("is_current")),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id"))
    version: Mapped[str]
    file_path: Mapped[str | None]
    file_format: Mapped[str | None]
    view_scope: Mapped[str] = mapped_column(server_default="ADMIN")          # 정책 미지정 시 가장 좁게
    transfer_policy: Mapped[str] = mapped_column(server_default="BLOCKED")
    is_current: Mapped[bool] = mapped_column(server_default=text("false"))
    ingest_status: Mapped[str]
    ingest_error: Mapped[str | None]
    registered_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    registered_at: Mapped[datetime] = mapped_column(server_default=func.now())


class DocumentChunk(Base):
    """검색 단위. 칸 설명과 meta 계약은 backend/app/rag/청크_메타데이터.md, 행은 app.rag.chunker.chunk_row()."""
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("version_id", "seq", name="uq_document_chunks_version_id_seq"),
        UniqueConstraint("version_id", "unit_key", "part", name="uq_document_chunks_version_id_unit_key_part"),
        CheckConstraint("chunk_type in ('ITEM', 'CHAPTER', 'FAQ', 'PREFACE')", name="chunk_type"),
        CheckConstraint("part >= 1", name="part"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id"))
    heading_path: Mapped[str | None]
    location: Mapped[str | None]
    content: Mapped[str]
    seq: Mapped[int] = mapped_column(Integer)                        # 문서 안 순번
    unit_key: Mapped[str] = mapped_column(index=True)                # 같은 항목·장·질문의 조각 묶음
    chunk_type: Mapped[str]                                          # ITEM·CHAPTER·FAQ·PREFACE
    part: Mapped[int] = mapped_column(Integer, server_default=text("1"))           # 묶음 안 조각 번호
    meta: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))  # 원문 메모 (키 고정)


class LegacyInquiry(Base):
    __tablename__ = "legacy_inquiries"
    __table_args__ = (
        CheckConstraint("channel in ('PHONE', 'MAIL', 'MESSENGER')", name="channel"),
        CheckConstraint("handling_type in ('IMMEDIATE', 'TICKET')", name="handling_type"),
        CheckConstraint("urgency in ('P1', 'P2', 'P3', 'P4')", name="urgency"),
        CheckConstraint("impact_scope in ('PERSONAL', 'DEPARTMENT', 'COMPANY')", name="impact_scope"),
        CheckConstraint(VIEW_SCOPE, name="view_scope"),
        CheckConstraint(TRANSFER_POLICY, name="transfer_policy"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    legacy_no: Mapped[str] = mapped_column(unique=True)
    received_at: Mapped[datetime]
    resolved_at: Mapped[datetime | None]
    channel: Mapped[str | None]
    handling_type: Mapped[str | None]
    requester_department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    inquiry_type_id: Mapped[int | None] = mapped_column(ForeignKey("inquiry_types.id"))
    urgency: Mapped[str | None]
    impact_scope: Mapped[str | None]
    title: Mapped[str | None]
    description: Mapped[str | None]
    root_cause: Mapped[str | None]
    resolution: Mapped[str | None]
    prevention: Mapped[str | None]
    group_id: Mapped[int | None] = mapped_column(ForeignKey("support_groups.id"))
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    view_scope: Mapped[str] = mapped_column(server_default="ADMIN")
    transfer_policy: Mapped[str] = mapped_column(server_default="BLOCKED")