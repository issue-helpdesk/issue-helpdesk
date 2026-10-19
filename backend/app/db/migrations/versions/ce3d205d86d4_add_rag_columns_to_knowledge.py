"""add rag columns to knowledge

Revision ID: ce3d205d86d4
Revises: 2793dd581cae
Create Date: 2026-10-19 20:49:07.136366

가이드 청크 적재(M2-2-1)에 필요한 칸과 규칙을 Knowledge 표에 더한다.
- document_chunks: seq·unit_key·chunk_type·part·meta (청크 순서, 나뉜 조각 묶음, 원문 메모)
- knowledge_documents.doc_type: STANDARD (공통 기준 IT-STD)
- document_versions: 현행 버전은 문서마다 최대 하나, 적재가 끝난(DONE) 버전만 현행

이미 FAQ 시드가 들어 있는 DB도 올릴 수 있게 ① 칸 추가 → ② 기존 행 채우기 → ③ 검사 → ④ 제약 순서로 한다.
칸 설명은 backend/app/rag/청크_메타데이터.md.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'ce3d205d86d4'
down_revision: Union[str, Sequence[str], None] = '2793dd581cae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ① 칸 추가. 기본값이 없는 칸은 기존 행 때문에 NULL 허용으로 먼저 만든다
    op.add_column('document_chunks', sa.Column('seq', sa.Integer(), nullable=True))
    op.add_column('document_chunks', sa.Column('unit_key', sa.Text(), nullable=True))
    op.add_column('document_chunks', sa.Column('chunk_type', sa.Text(), nullable=True))
    op.add_column('document_chunks', sa.Column('part', sa.Integer(), server_default=sa.text('1'), nullable=False))
    op.add_column('document_chunks', sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()),
                                               server_default=sa.text("'{}'::jsonb"), nullable=False))

    # ② 기존 행 채우기. 지금 들어 있는 청크는 FAQ 시드뿐이다 (버전 하나에 청크 하나)
    op.execute("""
        update document_chunks c
           set seq = 1,
               unit_key = d.doc_code || '@' || v.version || '/faq:' || d.doc_code,
               chunk_type = 'FAQ'
          from document_versions v
          join knowledge_documents d on d.id = v.document_id
         where v.id = c.version_id and c.seq is null
    """)
    # 적재(임베딩)가 끝나지 않은 버전은 현행일 수 없다 (아래 ④의 규칙)
    op.execute("update document_versions set is_current = false where is_current and ingest_status <> 'DONE'")

    # ③ 검사. 하나라도 걸리면 예외로 멈추고 아무것도 반영하지 않는다
    op.execute("""
        do $$ begin
          if exists (select 1 from document_chunks
                      where seq is null or unit_key is null or chunk_type is null) then
            raise exception '빈 값이 남은 document_chunks 행이 있음 (FAQ 외 청크가 이미 들어 있는지 확인)';
          end if;
          if exists (select 1 from document_chunks group by version_id, seq having count(*) > 1) then
            raise exception '한 버전 안에 같은 seq 가 둘 이상';
          end if;
          if exists (select 1 from document_versions where is_current
                      group by document_id having count(*) > 1) then
            raise exception '현행 버전이 둘 이상인 문서가 있음';
          end if;
        end $$
    """)

    # ④ 제약
    for name in ('seq', 'unit_key', 'chunk_type'):
        op.alter_column('document_chunks', name, nullable=False)
    op.create_unique_constraint(op.f('uq_document_chunks_version_id_seq'), 'document_chunks',
                                ['version_id', 'seq'])
    op.create_unique_constraint(op.f('uq_document_chunks_version_id_unit_key_part'), 'document_chunks',
                                ['version_id', 'unit_key', 'part'])
    op.create_check_constraint(op.f('ck_document_chunks_chunk_type'), 'document_chunks',
                               "chunk_type in ('ITEM', 'CHAPTER', 'FAQ', 'PREFACE')")
    op.create_check_constraint(op.f('ck_document_chunks_part'), 'document_chunks', 'part >= 1')
    op.create_index(op.f('ix_document_chunks_unit_key'), 'document_chunks', ['unit_key'])

    # 공통 기준 문서 (IT-STD-001·002)
    op.drop_constraint(op.f('ck_knowledge_documents_doc_type'), 'knowledge_documents', type_='check')
    op.create_check_constraint(op.f('ck_knowledge_documents_doc_type'), 'knowledge_documents',
                               "doc_type in ('GUIDE', 'FAQ', 'MANUAL', 'STANDARD')")

    # 현행 버전은 문서마다 최대 하나, 적재가 끝난 버전만 현행 (SRS GUIDE-05)
    op.create_index(op.f('uq_document_versions_one_current'), 'document_versions', ['document_id'],
                    unique=True, postgresql_where=sa.text('is_current'))
    op.create_check_constraint(op.f('ck_document_versions_current_needs_done'), 'document_versions',
                               "not is_current or ingest_status = 'DONE'")


def downgrade() -> None:
    """Downgrade schema.

    STANDARD 문서가 이미 들어 있으면 doc_type CHECK 를 되돌릴 수 없다. 그 행을 먼저 지운다.
    """
    op.drop_constraint(op.f('ck_document_versions_current_needs_done'), 'document_versions', type_='check')
    op.drop_index(op.f('uq_document_versions_one_current'), table_name='document_versions')

    op.drop_constraint(op.f('ck_knowledge_documents_doc_type'), 'knowledge_documents', type_='check')
    op.create_check_constraint(op.f('ck_knowledge_documents_doc_type'), 'knowledge_documents',
                               "doc_type in ('GUIDE', 'FAQ', 'MANUAL')")

    op.drop_index(op.f('ix_document_chunks_unit_key'), table_name='document_chunks')
    op.drop_constraint(op.f('ck_document_chunks_part'), 'document_chunks', type_='check')
    op.drop_constraint(op.f('ck_document_chunks_chunk_type'), 'document_chunks', type_='check')
    op.drop_constraint(op.f('uq_document_chunks_version_id_unit_key_part'), 'document_chunks', type_='unique')
    op.drop_constraint(op.f('uq_document_chunks_version_id_seq'), 'document_chunks', type_='unique')
    for name in ('meta', 'part', 'chunk_type', 'unit_key', 'seq'):
        op.drop_column('document_chunks', name)
