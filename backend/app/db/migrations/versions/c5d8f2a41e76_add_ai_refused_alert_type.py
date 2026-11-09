"""Add AI_REFUSED security alert type.

Revision ID: c5d8f2a41e76
Revises: a9c3e5b17d62
"""
from alembic import op

revision = 'c5d8f2a41e76'
down_revision = 'a9c3e5b17d62'
branch_labels = None
depends_on = None

OLD = ("'SENSITIVE_INPUT','BLOCKED_DOC_QUERY','ACCOUNT_LOCKED','LOGIN_BLOCKED','URGENT_CLOSED','MASS_QUERY',"
       "'S01','S02','S03','S04','S05','S06'")
NEW = OLD + ",'AI_REFUSED'"
NAME = 'ck_security_alerts_alert_type'


def upgrade():
    op.drop_constraint(op.f(NAME), 'security_alerts', type_='check')
    op.create_check_constraint(op.f(NAME), 'security_alerts', f'alert_type in ({NEW})')


def downgrade():
    # AI_REFUSED 알림이 남아 있으면 제약을 만들 때 실패한다. 알림을 지우면 증거가 사라지므로 일부러 막는다
    op.drop_constraint(op.f(NAME), 'security_alerts', type_='check')
    op.create_check_constraint(op.f(NAME), 'security_alerts', f'alert_type in ({OLD})')
