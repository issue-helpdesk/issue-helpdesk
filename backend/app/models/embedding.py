from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

EMBED_DIM = 1024

class DocumentChunkEmbedding(Base):
    __tablename__ = "document_chunk_embeddings"

    # 복합 PK (chunk_id, model): 청크 1개에 모델별로 벡터 하나
    chunk_id: Mapped[int] = mapped_column(ForeignKey("document_chunks.id", ondelete="CASCADE"), primary_key=True)
    model: Mapped[str] = mapped_column(primary_key=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM))
    source_text: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class LegacyInquiryEmbedding(Base):
    __tablename__ = "legacy_inquiry_embeddings"

    legacy_inquiry_id: Mapped[int] = mapped_column(ForeignKey("legacy_inquiries.id", ondelete="CASCADE"),
                                                   primary_key=True)
    model: Mapped[str] = mapped_column(primary_key=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM))
    source_text: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())