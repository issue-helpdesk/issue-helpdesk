"""rebuild notifications for screen

Slack 발송 구조를 화면 알림 구조로 바꾼다. 발송 상태 칸을 빼고 읽음 시각을 넣는다. 표는 아직 쓰인 적이 없어 옮길 데이터가 없다.

Revision ID: c7e2a91f4d30
Revises: 5cb42aafeaa1
Create Date: 2026-11-03 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7e2a91f4d30'
down_revision: Union[str, Sequence[str], None] = '5cb42aafeaa1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(op.f('ck_notifications_status'), 'notifications', type_='check')
    op.drop_column('notifications', 'status')
    op.drop_column('notifications', 'attempts')
    op.drop_column('notifications', 'sent_at')
    op.add_column('notifications', sa.Column('read_at', sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(op.f('ck_notifications_kind'), 'notifications', "kind in ('ASSIGNED', 'FIN')")
    op.create_index('ix_notifications_recipient', 'notifications', ['recipient_id', 'id'], unique=False)
    op.create_index('ix_notifications_unread', 'notifications', ['recipient_id', 'ticket_id'], unique=False,
                    postgresql_where=sa.text('read_at is null'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_notifications_unread', table_name='notifications', postgresql_where=sa.text('read_at is null'))
    op.drop_index('ix_notifications_recipient', table_name='notifications')
    op.drop_constraint(op.f('ck_notifications_kind'), 'notifications', type_='check')
    op.drop_column('notifications', 'read_at')
    op.add_column('notifications', sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('notifications', sa.Column('attempts', sa.Integer(), server_default=sa.text('0'), nullable=False))
    op.add_column('notifications', sa.Column('status', sa.Text(), server_default=sa.text("'SENT'"), nullable=False))
    op.alter_column('notifications', 'status', server_default=None)
    op.create_check_constraint(op.f('ck_notifications_status'), 'notifications', "status in ('PENDING', 'SENT', 'FAILED')")
