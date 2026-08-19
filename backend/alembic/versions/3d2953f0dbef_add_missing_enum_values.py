"""add_missing_enum_values

Revision ID: 3d2953f0dbef
Revises: 6c84384abca1
Create Date: 2026-08-18 10:41:44.084328

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '3d2953f0dbef'
down_revision: Union[str, Sequence[str], None] = '6c84384abca1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add missing enum values for native PostgreSQL enums only
    # (pipelinestage, pipelinestagestatus are VARCHAR with CHECK constraint, not native enums)
    
    # ChunkType enum (native: chunk_type_enum)
    op.execute("ALTER TYPE chunk_type_enum ADD VALUE IF NOT EXISTS 'TEXT'")
    op.execute("ALTER TYPE chunk_type_enum ADD VALUE IF NOT EXISTS 'TABLE'")
    op.execute("ALTER TYPE chunk_type_enum ADD VALUE IF NOT EXISTS 'HEADING'")
    op.execute("ALTER TYPE chunk_type_enum ADD VALUE IF NOT EXISTS 'FIGURE'")
    op.execute("ALTER TYPE chunk_type_enum ADD VALUE IF NOT EXISTS 'CODE'")
    
    # JobStatus enum (native: job_status)
    op.execute("ALTER TYPE job_status ADD VALUE IF NOT EXISTS 'QUEUED'")
    op.execute("ALTER TYPE job_status ADD VALUE IF NOT EXISTS 'RUNNING'")
    op.execute("ALTER TYPE job_status ADD VALUE IF NOT EXISTS 'SUCCEEDED'")
    op.execute("ALTER TYPE job_status ADD VALUE IF NOT EXISTS 'FAILED'")
    op.execute("ALTER TYPE job_status ADD VALUE IF NOT EXISTS 'RETRYING'")
    
    # LLMCallStatus enum (native: llm_call_status)
    op.execute("ALTER TYPE llm_call_status ADD VALUE IF NOT EXISTS 'SUCCESS'")
    op.execute("ALTER TYPE llm_call_status ADD VALUE IF NOT EXISTS 'FAILED'")
    op.execute("ALTER TYPE llm_call_status ADD VALUE IF NOT EXISTS 'CACHE_HIT'")
    
    # InviteStatus enum (native: invite_status)
    op.execute("ALTER TYPE invite_status ADD VALUE IF NOT EXISTS 'PENDING'")
    op.execute("ALTER TYPE invite_status ADD VALUE IF NOT EXISTS 'ACCEPTED'")
    op.execute("ALTER TYPE invite_status ADD VALUE IF NOT EXISTS 'REVOKED'")
    
    # Role enum (native: role) - if needed
    op.execute("ALTER TYPE role ADD VALUE IF NOT EXISTS 'ADMIN'")
    op.execute("ALTER TYPE role ADD VALUE IF NOT EXISTS 'USER'")
    op.execute("ALTER TYPE role ADD VALUE IF NOT EXISTS 'VIEWER'")
    
    # DocumentType enum (native: document_type)
    op.execute("ALTER TYPE document_type ADD VALUE IF NOT EXISTS 'RFP'")
    op.execute("ALTER TYPE document_type ADD VALUE IF NOT EXISTS 'RFQ'")
    op.execute("ALTER TYPE document_type ADD VALUE IF NOT EXISTS 'RFI'")
    op.execute("ALTER TYPE document_type ADD VALUE IF NOT EXISTS 'KNOWLEDGE_BASE'")
    op.execute("ALTER TYPE document_type ADD VALUE IF NOT EXISTS 'OTHER'")


def downgrade() -> None:
    """Downgrade schema."""
    # Cannot easily remove enum values
    pass
