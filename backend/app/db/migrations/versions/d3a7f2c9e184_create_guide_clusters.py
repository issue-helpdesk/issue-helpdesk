"""create guide_clusters, ticket_guide_states

해결 사례 가이드화 (기획_해결사례_가이드화). 묶음·초안·등록 연결은 guide_clusters, 티켓별 상태·실패 기록은
ticket_guide_states 에 둔다. tickets(Jira 연동)는 바꾸지 않는다. 기존 티켓은 행이 없다 = 아직 분석 안 함 (백필 없음).

Revision ID: d3a7f2c9e184
Revises: b5d1e8a3c702
Create Date: 2026-11-08 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd3a7f2c9e184'
down_revision: Union[str, Sequence[str], None] = 'b5d1e8a3c702'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'guide_clusters',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('category_code', sa.Text(), nullable=False),
        sa.Column('judgment', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), server_default=sa.text("'REVIEWING'"), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('target_document_id', sa.BigInteger(), nullable=True),
        sa.Column('base_version_id', sa.BigInteger(), nullable=True),
        sa.Column('compared_items', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"),
                  nullable=False),
        sa.Column('draft_md', sa.Text(), nullable=True),
        sa.Column('draft_basis', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('review_info', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"),
                  nullable=False),
        sa.Column('draft_revision', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('registered_version_id', sa.BigInteger(), nullable=True),
        sa.Column('reject_reason', sa.Text(), nullable=True),
        sa.Column('reviewed_by', sa.BigInteger(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("judgment in ('ADD_ITEM', 'CHANGE', 'NEW_GUIDE', 'MANUAL_CANDIDATE', 'SEC_MANUAL')",
                           name=op.f('ck_guide_clusters_judgment')),
        sa.CheckConstraint("status in ('REVIEWING', 'APPLIED', 'REJECTED')", name=op.f('ck_guide_clusters_status')),
        sa.CheckConstraint("status <> 'REJECTED' or reject_reason is not null",
                           name=op.f('ck_guide_clusters_reject_ref')),
        sa.CheckConstraint('draft_revision >= 0', name=op.f('ck_guide_clusters_draft_revision')),
        sa.ForeignKeyConstraint(['category_code'], ['categories.code'],
                                name=op.f('fk_guide_clusters_category_code_categories')),
        sa.ForeignKeyConstraint(['target_document_id'], ['knowledge_documents.id'],
                                name=op.f('fk_guide_clusters_target_document_id_knowledge_documents')),
        sa.ForeignKeyConstraint(['base_version_id'], ['document_versions.id'],
                                name=op.f('fk_guide_clusters_base_version_id_document_versions')),
        sa.ForeignKeyConstraint(['registered_version_id'], ['document_versions.id'],
                                name=op.f('fk_guide_clusters_registered_version_id_document_versions')),
        sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], name=op.f('fk_guide_clusters_reviewed_by_users')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_guide_clusters')),
    )
    op.create_index(op.f('ix_guide_clusters_registered_version_id'), 'guide_clusters', ['registered_version_id'],
                    unique=False)

    op.create_table(
        'ticket_guide_states',
        sa.Column('ticket_id', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.Text(), nullable=True),
        sa.Column('cluster_id', sa.BigInteger(), nullable=True),
        sa.Column('fail_code', sa.Text(), nullable=True),
        sa.Column('fail_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('exclude_reason', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("status in ('WAITING', 'EXCLUDED', 'REVIEWING', 'APPLIED', 'REJECTED')",
                           name=op.f('ck_ticket_guide_states_status')),
        sa.CheckConstraint("(status in ('REVIEWING', 'APPLIED', 'REJECTED')) = (cluster_id is not null)",
                           name=op.f('ck_ticket_guide_states_cluster_ref')),
        sa.CheckConstraint("(status = 'EXCLUDED') = (exclude_reason is not null)",
                           name=op.f('ck_ticket_guide_states_exclude_ref')),
        sa.CheckConstraint('fail_count >= 0', name=op.f('ck_ticket_guide_states_fail_count')),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], name=op.f('fk_ticket_guide_states_ticket_id_tickets')),
        sa.ForeignKeyConstraint(['cluster_id'], ['guide_clusters.id'],
                                name=op.f('fk_ticket_guide_states_cluster_id_guide_clusters')),
        sa.PrimaryKeyConstraint('ticket_id', name=op.f('pk_ticket_guide_states')),
    )
    op.create_index(op.f('ix_ticket_guide_states_cluster_id'), 'ticket_guide_states', ['cluster_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_ticket_guide_states_cluster_id'), table_name='ticket_guide_states')
    op.drop_table('ticket_guide_states')
    op.drop_index(op.f('ix_guide_clusters_registered_version_id'), table_name='guide_clusters')
    op.drop_table('guide_clusters')
