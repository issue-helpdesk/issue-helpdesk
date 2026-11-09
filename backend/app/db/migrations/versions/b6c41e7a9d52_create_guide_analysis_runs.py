"""해결 사례 가이드화 주간 분석의 실행 기록 (중복 실행 방지·놓친 회차 보충·GC-09 표시).

Revision ID: b6c41e7a9d52
Revises: d3a7f2c9e184
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'b6c41e7a9d52'
down_revision = 'd3a7f2c9e184'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'guide_analysis_runs',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('scheduled_for', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('counts', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"),
                  nullable=False),
        sa.Column('error_code', sa.Text(), nullable=True),
        sa.CheckConstraint("status in ('RUNNING', 'SUCCEEDED', 'FAILED')", name=op.f('ck_guide_analysis_runs_status')),
        sa.CheckConstraint("(status = 'RUNNING') = (finished_at is null)",
                           name=op.f('ck_guide_analysis_runs_finished_ref')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_guide_analysis_runs')),
    )
    op.create_index('uq_guide_analysis_runs_running', 'guide_analysis_runs', ['status'], unique=True,
                    postgresql_where=sa.text("status = 'RUNNING'"))


def downgrade() -> None:
    op.drop_index('uq_guide_analysis_runs_running', table_name='guide_analysis_runs')
    op.drop_table('guide_analysis_runs')
