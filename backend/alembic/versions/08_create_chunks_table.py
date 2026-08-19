"""08_create_chunks_table

Revision ID: 08_create_chunks_table
Revises: 07_create_raw_extractions_table
Create Date: 2026-08-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.db.rls import enable_rls

# revision identifiers, used by Alembic.
revision: str = "08_create_chunks_table"
down_revision: Union[str, Sequence[str], None] = "07_create_raw_extractions_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # Create chunk_type enum using raw SQL to avoid SQLAlchemy enum event listener issues
    op.execute("CREATE TYPE chunk_type_enum AS ENUM ('text', 'table', 'heading')")

    # Create chunks table (RLS-scoped)
    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("chunk_type", postgresql.ENUM("text", "table", "heading", name="chunk_type_enum", create_type=False), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("section_path", sa.Text(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=False, default=0),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["document_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chunks_org_id", "chunks", ["org_id"])
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_index("ix_chunks_version_id", "chunks", ["version_id"])
    op.create_index("ix_chunks_chunk_index", "chunks", ["document_id", "chunk_index"])
    op.create_index("ix_chunks_chunk_type", "chunks", ["chunk_type"])
    op.create_index("ix_chunks_section_path", "chunks", ["section_path"])

    # Enable RLS on tenant-scoped table with FORCE to prevent owner bypass.
    for stmt in enable_rls("chunks"):
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade schema."""

    # Drop table (cascade will clean up RLS policies)
    op.drop_table("chunks")

    # Drop enum type
    op.execute("DROP TYPE IF EXISTS chunk_type_enum")