"""09_add_embedding_and_search_vector

Revision ID: 09_add_embedding_and_search_vector
Revises: 08_create_chunks_table
Create Date: 2026-08-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "09_add_embedding_search_vector"
down_revision: Union[str, Sequence[str], None] = "08_create_chunks_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Add embedding column (1536 dimensions for text-embedding-3-small)
    op.add_column(
        "chunks",
        sa.Column("embedding", Vector(1536), nullable=True),
    )

    # Add search_vector generated column for full-text search
    op.add_column(
        "chunks",
        sa.Column(
            "search_vector",
            sa.dialects.postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('english', coalesce(content, ''))",
                persisted=True,
            ),
            nullable=False,
        ),
    )

    # Create HNSW index on embedding for fast vector similarity search
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )

    # Create GIN index on search_vector for full-text search
    op.create_index(
        "ix_chunks_search_vector_gin",
        "chunks",
        ["search_vector"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    """Downgrade schema."""

    # Drop indexes
    op.drop_index("ix_chunks_search_vector_gin", table_name="chunks")
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw")

    # Drop columns
    op.drop_column("chunks", "search_vector")
    op.drop_column("chunks", "embedding")

    # Drop pgvector extension (only if no other tables use it)
    op.execute("DROP EXTENSION IF EXISTS vector")