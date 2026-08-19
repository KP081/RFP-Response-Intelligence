"""fix_document_status_column_type

Revision ID: 427eb70ef348
Revises: 2e5988b95c3c
Create Date: 2026-08-18 10:36:19.937903

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '427eb70ef348'
down_revision: Union[str, Sequence[str], None] = '2e5988b95c3c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # The document_status enum was created as a native PostgreSQL enum
    # but the column was created as VARCHAR with CHECK constraint.
    # First, normalize existing data to lowercase to match enum values
    op.execute("UPDATE documents SET status = LOWER(status)")
    # Then drop the default, alter column to use the native enum type, re-add default
    op.execute("ALTER TABLE documents ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE documents ALTER COLUMN status TYPE document_status USING status::document_status")
    op.execute("ALTER TABLE documents ALTER COLUMN status SET DEFAULT 'uploaded'::document_status")


def downgrade() -> None:
    """Downgrade schema."""
    # Cannot easily downgrade enum column
    pass
