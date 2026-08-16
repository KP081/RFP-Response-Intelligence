"""04_add_is_deleted_to_documents

Revision ID: 04_add_is_deleted_to_documents
Revises: 03_create_documents_tables
Create Date: 2026-08-16

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '04_add_is_deleted_to_documents'
down_revision: Union[str, Sequence[str], None] = '03_create_documents_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('documents', sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'))
    op.create_index('ix_documents_is_deleted', 'documents', ['is_deleted'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_documents_is_deleted', table_name='documents')
    op.drop_column('documents', 'is_deleted')