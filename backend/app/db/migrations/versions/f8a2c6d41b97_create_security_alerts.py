"""create security_alerts

보안·감사 알림 (06 security_alerts, AUDIT-01~04). 이미 쌓인 audit_logs 로 알림을 만들지 않는다 (백필 없음).

Revision ID: f8a2c6d41b97
Revises: c4e7a1d95f28
Create Date: 2026-11-06 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f8a2c6d41b97'
down_revision: Union[str, Sequence[str], None] = 'c4e7a1d95f28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OPEN_ALERT = "status <> 'CLOSED'"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'security_alerts',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('alert_type', sa.Text(), nullable=False),
        sa.Column('severity', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), server_default=sa.text("'NEW'"), nullable=False),
        sa.Column('subject_user_id', sa.BigInteger(), nullable=False),
        sa.Column('target_type', sa.Text(), nullable=False),
        sa.Column('target_id', sa.BigInteger(), nullable=False),
        sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"),
                  nullable=False),
        sa.Column('occurrence_count', sa.Integer(), server_default=sa.text('1'), nullable=False),
        sa.Column('first_detected_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_detected_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('reviewer_id', sa.BigInteger(), nullable=True),
        sa.Column('review_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('closed_by', sa.BigInteger(), nullable=True),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('close_reason', sa.Text(), nullable=True),
        sa.CheckConstraint(
            "alert_type in ('SENSITIVE_INPUT', 'BLOCKED_DOC_QUERY', 'ACCOUNT_LOCKED', 'LOGIN_BLOCKED', "
            "'URGENT_CLOSED', 'MASS_QUERY')", name=op.f('ck_security_alerts_alert_type')),
        sa.CheckConstraint("severity in ('HIGH', 'MEDIUM', 'LOW')", name=op.f('ck_security_alerts_severity')),
        sa.CheckConstraint("status in ('NEW', 'IN_REVIEW', 'CLOSED')", name=op.f('ck_security_alerts_status')),
        sa.CheckConstraint("target_type in ('inquiry', 'user')", name=op.f('ck_security_alerts_target_type')),
        sa.CheckConstraint('occurrence_count >= 1', name=op.f('ck_security_alerts_occurrence_count')),
        sa.CheckConstraint("status = 'NEW' or (reviewer_id is not null and review_started_at is not null)",
                           name=op.f('ck_security_alerts_review_ref')),
        sa.CheckConstraint("status <> 'CLOSED' or (closed_by is not null and closed_at is not null "
                           "and close_reason is not null)", name=op.f('ck_security_alerts_close_ref')),
        sa.ForeignKeyConstraint(['subject_user_id'], ['users.id'],
                                name=op.f('fk_security_alerts_subject_user_id_users')),
        sa.ForeignKeyConstraint(['reviewer_id'], ['users.id'], name=op.f('fk_security_alerts_reviewer_id_users')),
        sa.ForeignKeyConstraint(['closed_by'], ['users.id'], name=op.f('fk_security_alerts_closed_by_users')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_security_alerts')),
    )
    op.create_index('ix_security_alerts_status', 'security_alerts', ['status', sa.text('first_detected_at desc')],
                    unique=False)
    op.create_index('uq_security_alerts_one_open', 'security_alerts',
                    ['alert_type', 'subject_user_id', 'target_type', 'target_id'], unique=True,
                    postgresql_where=sa.text(OPEN_ALERT))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_security_alerts_one_open', table_name='security_alerts', postgresql_where=sa.text(OPEN_ALERT))
    op.drop_index('ix_security_alerts_status', table_name='security_alerts')
    op.drop_table('security_alerts')
