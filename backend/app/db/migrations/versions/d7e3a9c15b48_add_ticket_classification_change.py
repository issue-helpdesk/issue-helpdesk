"""add ticket classification change

접수 분류 변경(TK-15)의 Jira 필드 갱신 작업(JIRA_UPDATE_FIELDS)과 분류 이상 신고(TK-16~18) 테이블.

Revision ID: d7e3a9c15b48
Revises: c5d8f2a41e76
Create Date: 2026-11-10 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7e3a9c15b48'
down_revision: Union[str, Sequence[str], None] = 'c5d8f2a41e76'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_TYPES = "'JIRA_CREATE', 'JIRA_ASSIGN', 'JIRA_TRANSITION'"
NEW_TYPES = OLD_TYPES + ", 'JIRA_UPDATE_FIELDS'"
OLD_ACTIVE = "status in ('PENDING', 'RUNNING') and job_type in ('JIRA_ASSIGN', 'JIRA_TRANSITION')"
NEW_ACTIVE = "status in ('PENDING', 'RUNNING') and job_type in ('JIRA_ASSIGN', 'JIRA_TRANSITION', 'JIRA_UPDATE_FIELDS')"
JOB_TYPE_CHECK = 'ck_integration_jobs_job_type'
ONE_ACTIVE = 'uq_integration_jobs_one_active'
OPEN_REPORT = "status = 'OPEN'"


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(op.f(JOB_TYPE_CHECK), 'integration_jobs', type_='check')
    op.create_check_constraint(op.f(JOB_TYPE_CHECK), 'integration_jobs', f'job_type in ({NEW_TYPES})')
    op.drop_index(ONE_ACTIVE, table_name='integration_jobs')
    op.create_index(ONE_ACTIVE, 'integration_jobs', ['ticket_id', 'job_type'], unique=True,
                    postgresql_where=sa.text(NEW_ACTIVE))

    op.create_table(
        'ticket_classification_reports',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('ticket_id', sa.BigInteger(), nullable=False),
        sa.Column('reporter_id', sa.BigInteger(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('suggested_inquiry_type_id', sa.BigInteger(), nullable=True),
        sa.Column('status', sa.Text(), server_default=sa.text("'OPEN'"), nullable=False),
        sa.Column('resolved_by', sa.BigInteger(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolution_note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("status in ('OPEN', 'RESOLVED', 'REJECTED')",
                           name=op.f('ck_ticket_classification_reports_status')),
        sa.CheckConstraint("status = 'OPEN' or (resolved_by is not null and resolved_at is not null "
                           "and resolution_note is not null)",
                           name=op.f('ck_ticket_classification_reports_resolved_ref')),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'],
                                name=op.f('fk_ticket_classification_reports_ticket_id_tickets')),
        sa.ForeignKeyConstraint(['reporter_id'], ['users.id'],
                                name=op.f('fk_ticket_classification_reports_reporter_id_users')),
        sa.ForeignKeyConstraint(['suggested_inquiry_type_id'], ['inquiry_types.id'],
                                name=op.f('fk_ticket_classification_reports_suggested_inquiry_type_id_inquiry_types')),
        sa.ForeignKeyConstraint(['resolved_by'], ['users.id'],
                                name=op.f('fk_ticket_classification_reports_resolved_by_users')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_ticket_classification_reports')),
    )
    op.create_index(op.f('ix_ticket_classification_reports_ticket_id'), 'ticket_classification_reports',
                    ['ticket_id'], unique=False)
    op.create_index('uq_ticket_classification_reports_one_open', 'ticket_classification_reports', ['ticket_id'],
                    unique=True, postgresql_where=sa.text(OPEN_REPORT))


def downgrade() -> None:
    """Downgrade schema.

    JIRA_UPDATE_FIELDS 작업이 남아 있으면 제약을 만들 때 실패한다. 연동 이력을 지우지 않도록 일부러 막는다.
    """
    op.drop_index('uq_ticket_classification_reports_one_open', table_name='ticket_classification_reports')
    op.drop_index(op.f('ix_ticket_classification_reports_ticket_id'), table_name='ticket_classification_reports')
    op.drop_table('ticket_classification_reports')

    op.drop_index(ONE_ACTIVE, table_name='integration_jobs')
    op.create_index(ONE_ACTIVE, 'integration_jobs', ['ticket_id', 'job_type'], unique=True,
                    postgresql_where=sa.text(OLD_ACTIVE))
    op.drop_constraint(op.f(JOB_TYPE_CHECK), 'integration_jobs', type_='check')
    op.create_check_constraint(op.f(JOB_TYPE_CHECK), 'integration_jobs', f'job_type in ({OLD_TYPES})')
