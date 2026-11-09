"""add document_chunks.content_transfer_policy

매뉴얼 3.x 항목별 내용 외부 전송 (해결 사례 가이드화 선행 작업). 비어 있으면 버전의 transfer_policy 를 따르므로
기존 행은 비워 둔다 (백필 없음). 값은 매뉴얼 적재 때 허용 목록으로 채운다.

Revision ID: b5d1e8a3c702
Revises: f8a2c6d41b97
Create Date: 2026-11-08 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b5d1e8a3c702'
down_revision: Union[str, Sequence[str], None] = 'f8a2c6d41b97'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('document_chunks', sa.Column('content_transfer_policy', sa.Text(), nullable=True))
    op.create_check_constraint(op.f('ck_document_chunks_content_transfer_policy'), 'document_chunks',
                               "content_transfer_policy in ('ALLOWED', 'BLOCKED')")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f('ck_document_chunks_content_transfer_policy'), 'document_chunks', type_='check')
    op.drop_column('document_chunks', 'content_transfer_policy')
