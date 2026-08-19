"""add_ready_for_chunking_to_document_status

Revision ID: 2e5988b95c3c
Revises: 3e02c6964bfd
Create Date: 2026-08-18 10:33:53.530164

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '2e5988b95c3c'
down_revision: Union[str, Sequence[str], None] = '3e02c6964bfd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add missing enum values to document_status
    op.execute("ALTER TYPE document_status ADD VALUE IF NOT EXISTS 'ready_for_chunking'")
    # Note: We also need to ensure 'processing' is in the enum (it should be from original migration)
    # But let's also add any other missing values from the model
    op.execute("ALTER TYPE document_status ADD VALUE IF NOT EXISTS 'processing'")


def downgrade() -> None:
    """Downgrade schema."""
    # Cannot easily remove enum values in PostgreSQL
    # Would need to recreate the enum type
    pass
