"""Extend security alert types with AI review rules S01-S06.

Revision ID: a9c3e5b17d62
Revises: b6c41e7a9d52
"""
from alembic import op

revision = 'a9c3e5b17d62'
down_revision = 'b6c41e7a9d52'
branch_labels = None
depends_on = None

OLD = "'SENSITIVE_INPUT','BLOCKED_DOC_QUERY','ACCOUNT_LOCKED','LOGIN_BLOCKED','URGENT_CLOSED','MASS_QUERY'"
NEW = OLD + ",'S01','S02','S03','S04','S05','S06'"
NAME = 'ck_security_alerts_alert_type'


def upgrade():
    op.drop_constraint(op.f(NAME), 'security_alerts', type_='check')
    op.create_check_constraint(op.f(NAME), 'security_alerts', f'alert_type in ({NEW})')


def downgrade():
    # S01~S06 알림이 남아 있으면 제약을 만들 때 실패한다. 알림을 지우거나 다른 유형으로 바꾸면 증거가 사라지므로 일부러 막는다
    op.drop_constraint(op.f(NAME), 'security_alerts', type_='check')
    op.create_check_constraint(op.f(NAME), 'security_alerts', f'alert_type in ({OLD})')
