"""add ticket_status_history.resolution_note

완료할 때의 처리 결과를 이력에 남긴다. tickets.resolution_note 는 재완료 때 덮어쓰므로 지금 값은 마지막 완료 이력에 옮겨 둔다.

Revision ID: b6f2c81d4e93
Revises: e4b81d6f20a7
Create Date: 2026-11-04 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b6f2c81d4e93'
down_revision: Union[str, Sequence[str], None] = 'e4b81d6f20a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


FILL_LAST_FINISH = """
update ticket_status_history as h
set resolution_note = (select t.resolution_note from tickets t where t.id = h.ticket_id)
where h.to_status = 'FIN'
  and not exists (
    select 1 from ticket_status_history later
    where later.ticket_id = h.ticket_id and later.to_status = 'FIN'
      and (later.changed_at > h.changed_at or (later.changed_at = h.changed_at and later.id > h.id))
  )
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('ticket_status_history', sa.Column('resolution_note', sa.Text(), nullable=True))
    op.execute(FILL_LAST_FINISH)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('ticket_status_history', 'resolution_note')
