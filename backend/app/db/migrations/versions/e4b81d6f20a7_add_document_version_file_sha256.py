"""add document version file sha256

같은 파일을 다시 올려 파싱·임베딩·저장 공간을 쓰지 않도록 내용 해시를 저장한다. 기존 행은 NULL 이고 db/backfill_document_hashes.py 로 채운다.

Revision ID: e4b81d6f20a7
Revises: c7e2a91f4d30
Create Date: 2026-11-03 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4b81d6f20a7'
down_revision: Union[str, Sequence[str], None] = 'c7e2a91f4d30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('document_versions', sa.Column('file_sha256', sa.Text(), nullable=True))
    op.create_index('uq_document_versions_file_sha256', 'document_versions', ['file_sha256'], unique=True,
                    postgresql_where=sa.text('file_sha256 is not null'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_document_versions_file_sha256', table_name='document_versions',
                  postgresql_where=sa.text('file_sha256 is not null'))
    op.drop_column('document_versions', 'file_sha256')
