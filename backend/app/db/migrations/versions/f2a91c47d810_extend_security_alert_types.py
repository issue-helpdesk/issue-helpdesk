"""Extend security alert types for LLM review and filter failures.

Revision ID: f2a91c47d810
Revises: d3a7f2c9e184
"""
from alembic import op

revision = 'f2a91c47d810'
down_revision = 'd3a7f2c9e184'
branch_labels = None
depends_on = None

OLD = "'SENSITIVE_INPUT','BLOCKED_DOC_QUERY','ACCOUNT_LOCKED','LOGIN_BLOCKED','URGENT_CLOSED','MASS_QUERY'"
NEW = OLD + ",'S01','S02','S03','S04','S05','S06','S07','FILTER_FAILED','UNSAFE_REPLY'"
NAME = 'ck_security_alerts_alert_type'


def upgrade():
    op.drop_constraint(op.f(NAME), 'security_alerts', type_='check')
    op.create_check_constraint(op.f(NAME), 'security_alerts', f'alert_type in ({NEW})')


def downgrade():
    # Preserve review data. Downgrade deliberately fails if expanded types are still present;
    # silently deleting alerts or relabeling them as a different incident would lose evidence.
    op.drop_constraint(op.f(NAME), 'security_alerts', type_='check')
    op.create_check_constraint(op.f(NAME), 'security_alerts', f'alert_type in ({OLD})')
