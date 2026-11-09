"""add message kind

문의자가 누른 버튼과 카드를 대화 기록으로 남긴다 (R-29). 문구는 저장하지 않고 화면이 code 로 정한다.
기존 SYSTEM 메시지는 모두 안내이므로 NOTICE 로 옮긴다.

Revision ID: c4e7a1d95f28
Revises: a3d94f7c1e62
Create Date: 2026-11-05 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4e7a1d95f28'
down_revision: Union[str, Sequence[str], None] = 'a3d94f7c1e62'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('messages', sa.Column('kind', sa.Text(), server_default=sa.text("'TEXT'"), nullable=False))
    op.add_column('messages', sa.Column('code', sa.Text(), nullable=True))
    op.add_column('messages', sa.Column('draft_id', sa.BigInteger(), nullable=True))
    op.alter_column('messages', 'content', existing_type=sa.Text(), nullable=True)
    op.create_foreign_key(op.f('fk_messages_draft_id_ticket_drafts'), 'messages', 'ticket_drafts', ['draft_id'], ['id'])
    op.execute("UPDATE messages SET kind = 'NOTICE' WHERE sender = 'SYSTEM'")
    op.create_check_constraint(op.f('ck_messages_kind'), 'messages',
                               "kind in ('TEXT', 'CHOICE', 'NOTICE', 'DRAFT_CARD', 'TICKET_CARD')")
    op.create_check_constraint(op.f('ck_messages_code'), 'messages',
                               "code in ('RESOLVED', 'UNRESOLVED', 'CONNECT', 'NO_CONNECT', 'CONFIRM', 'CANCEL', 'TICKET_RESOLVED', 'TICKET_UNRESOLVED')")
    op.create_check_constraint(op.f('ck_messages_choice_code'), 'messages', "(kind = 'CHOICE') = (code is not null)")
    op.create_check_constraint(op.f('ck_messages_content_ref'), 'messages',
                               "(kind in ('TEXT', 'NOTICE')) = (content is not null)")
    op.create_check_constraint(op.f('ck_messages_draft_ref'), 'messages',
                               "(kind = 'DRAFT_CARD') = (draft_id is not null)")


def downgrade() -> None:
    """Downgrade schema. 버튼·카드 행은 content 가 없어 content NOT NULL 로 되돌리기 전에 지운다."""
    op.execute("DELETE FROM messages WHERE kind IN ('CHOICE', 'DRAFT_CARD', 'TICKET_CARD')")
    op.drop_constraint(op.f('ck_messages_draft_ref'), 'messages', type_='check')
    op.drop_constraint(op.f('ck_messages_content_ref'), 'messages', type_='check')
    op.drop_constraint(op.f('ck_messages_choice_code'), 'messages', type_='check')
    op.drop_constraint(op.f('ck_messages_code'), 'messages', type_='check')
    op.drop_constraint(op.f('ck_messages_kind'), 'messages', type_='check')
    op.drop_constraint(op.f('fk_messages_draft_id_ticket_drafts'), 'messages', type_='foreignkey')
    op.alter_column('messages', 'content', existing_type=sa.Text(), nullable=False)
    op.drop_column('messages', 'draft_id')
    op.drop_column('messages', 'code')
    op.drop_column('messages', 'kind')
