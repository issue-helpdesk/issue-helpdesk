"""create faq_source_documents

관리자가 FAQ 에 출처 문서를 직접 지정한다 (R-41). 기존 meta.faq_ids 연결은 그대로 둔다.

Revision ID: a3d94f7c1e62
Revises: b6f2c81d4e93
Create Date: 2026-11-05 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3d94f7c1e62'
down_revision: Union[str, Sequence[str], None] = 'b6f2c81d4e93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'faq_source_documents',
        sa.Column('faq_id', sa.BigInteger(), nullable=False),
        sa.Column('document_id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['knowledge_documents.id'],
                                name=op.f('fk_faq_source_documents_document_id_knowledge_documents')),
        sa.ForeignKeyConstraint(['faq_id'], ['faqs.id'], name=op.f('fk_faq_source_documents_faq_id_faqs'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('faq_id', 'document_id', name=op.f('pk_faq_source_documents')),
    )
    op.create_index('ix_faq_source_documents_document_id', 'faq_source_documents', ['document_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_faq_source_documents_document_id', table_name='faq_source_documents')
    op.drop_table('faq_source_documents')
