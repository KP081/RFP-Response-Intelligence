"""add_uppercase_document_status_values

Revision ID: 6c84384abca1
Revises: 427eb70ef348
Create Date: 2026-08-18 10:39:17.988717

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '6c84384abca1'
down_revision: Union[str, Sequence[str], None] = '427eb70ef348'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add uppercase enum values to match the Python DocumentStatus enum
    op.execute("ALTER TYPE document_status ADD VALUE IF NOT EXISTS 'UPLOADED'")
    op.execute("ALTER TYPE document_status ADD VALUE IF NOT EXISTS 'PROCESSING'")
    op.execute("ALTER TYPE document_status ADD VALUE IF NOT EXISTS 'READY_FOR_CHUNKING'")
    op.execute("ALTER TYPE document_status ADD VALUE IF NOT EXISTS 'READY'")
    op.execute("ALTER TYPE document_status ADD VALUE IF NOT EXISTS 'FAILED'")


def downgrade() -> None:
    """Downgrade schema."""
    # Cannot easily remove enum values
    pass
