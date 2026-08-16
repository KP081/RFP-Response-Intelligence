"""06_create_llm_calls_table

Revision ID: 06_create_llm_calls_table
Revises: 05_create_pipeline_jobs_table
Create Date: 2026-08-16

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.db.rls import enable_rls

# revision identifiers, used by Alembic.
revision: str = "06_create_llm_calls_table"
down_revision: Union[str, Sequence[str], None] = "05_create_pipeline_jobs_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # Create llm_call_status enum type
    llm_call_status_enum = postgresql.ENUM(
        "success",
        "failed",
        "cache_hit",
        name="llm_call_status",
        create_type=True,
    )
    llm_call_status_enum.create(op.get_bind(), checkfirst=True)

    # Create llm_calls table (RLS-scoped)
    op.create_table(
        "llm_calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_type", sa.String(100), nullable=False),
        sa.Column("model_tier", sa.String(50), nullable=False),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(50), nullable=True),
        sa.Column("correlation_id", sa.String(36), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_estimate", sa.Numeric(10, 6), nullable=False, server_default="0.0"),
        sa.Column(
            "status",
            sa.Enum("success", "failed", "cache_hit", name="llm_call_status", native_enum=False),
            nullable=False,
            server_default="success",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_calls_org_id", "llm_calls", ["org_id"])
    op.create_index("ix_llm_calls_task_type", "llm_calls", ["task_type"])
    op.create_index("ix_llm_calls_model_tier", "llm_calls", ["model_tier"])
    op.create_index("ix_llm_calls_correlation_id", "llm_calls", ["correlation_id"])
    op.create_index("ix_llm_calls_created_at", "llm_calls", ["created_at"])

    # Enable RLS on tenant-scoped table with FORCE to prevent owner bypass.
    for stmt in enable_rls("llm_calls"):
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade schema."""

    # Drop table (cascade will clean up RLS policies)
    op.drop_table("llm_calls")

    # Drop enum type
    op.execute("DROP TYPE IF EXISTS llm_call_status CASCADE;")