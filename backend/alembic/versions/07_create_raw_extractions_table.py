"""07_create_raw_extractions_table

Revision ID: 07_create_raw_extractions_table
Revises: 06_create_llm_calls_table
Create Date: 2026-08-16

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.db.rls import enable_rls

# revision identifiers, used by Alembic.
revision: str = "07_create_raw_extractions_table"
down_revision: Union[str, Sequence[str], None] = "06_create_llm_calls_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # Create raw_extractions table (RLS-scoped)
    op.create_table(
        "raw_extractions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("blocks", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("extractor_used", sa.String(50), nullable=False),
        sa.Column("extracted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["document_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_raw_extractions_org_id", "raw_extractions", ["org_id"])
    op.create_index("ix_raw_extractions_document_id", "raw_extractions", ["document_id"])
    op.create_index("ix_raw_extractions_version_id", "raw_extractions", ["version_id"])
    op.create_index("ix_raw_extractions_extracted_at", "raw_extractions", ["extracted_at"])

    # Enable RLS on tenant-scoped table with FORCE to prevent owner bypass.
    for stmt in enable_rls("raw_extractions"):
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade schema."""

    # Drop table (cascade will clean up RLS policies)
    op.drop_table("raw_extractions")