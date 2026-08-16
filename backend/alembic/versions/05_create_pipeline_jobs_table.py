"""05_create_pipeline_jobs_table

Revision ID: 05_create_pipeline_jobs_table
Revises: 04_add_is_deleted_to_documents
Create Date: 2026-08-16

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.db.rls import enable_rls

# revision identifiers, used by Alembic.
revision: str = "05_create_pipeline_jobs_table"
down_revision: Union[str, Sequence[str], None] = "04_add_is_deleted_to_documents"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # Create job_status enum type
    job_status_enum = postgresql.ENUM(
        "queued",
        "running",
        "succeeded",
        "failed",
        "retrying",
        name="job_status",
        create_type=True,
    )
    job_status_enum.create(op.get_bind(), checkfirst=True)

    # Create pipeline_jobs table (RLS-scoped)
    op.create_table(
        "pipeline_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("job_type", sa.String(100), nullable=False),
        sa.Column(
            "status",
            sa.Enum("queued", "running", "succeeded", "failed", "retrying", name="job_status", native_enum=False),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("current_stage", sa.String(100), nullable=True),
        sa.Column("progress_pct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.String(5000), nullable=True),
        sa.Column("correlation_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pipeline_jobs_org_id", "pipeline_jobs", ["org_id"])
    op.create_index("ix_pipeline_jobs_document_id", "pipeline_jobs", ["document_id"])
    op.create_index("ix_pipeline_jobs_job_type", "pipeline_jobs", ["job_type"])
    op.create_index("ix_pipeline_jobs_correlation_id", "pipeline_jobs", ["correlation_id"])

    # Enable RLS on tenant-scoped table with FORCE to prevent owner bypass.
    for stmt in enable_rls("pipeline_jobs"):
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade schema."""

    # Drop table (cascade will clean up RLS policies)
    op.drop_table("pipeline_jobs")

    # Drop enum type
    op.execute("DROP TYPE IF EXISTS job_status CASCADE;")