"""fix_enum_drift_and_remove_bogus_values

Revision ID: c0a2cbe338fc
Revises: 3d2953f0dbef
Create Date: 2026-08-27 13:10:57.499846

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c0a2cbe338fc'
down_revision: Union[str, Sequence[str], None] = '3d2953f0dbef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: convert native enums to VARCHAR + CHECK, remove bogus values."""
    
    # ============================================================
    # 1. role enum (org_memberships.role) - remove bogus 'USER' value
    # ============================================================
    # Valid roles from the model
    valid_roles = "('admin', 'proposal_manager', 'sales', 'presales_architect', 'legal', 'security', 'compliance', 'viewer')"
    
    # Update any bogus 'USER' values to a valid default (e.g., 'viewer')
    op.execute("UPDATE org_memberships SET role = 'viewer' WHERE role = 'USER'")
    # Also fix any other uppercase roles to lowercase
    op.execute("UPDATE org_memberships SET role = LOWER(role) WHERE role IN ('ADMIN', 'VIEWER')")
    
    # Convert org_memberships.role from native enum to VARCHAR + CHECK
    op.execute("ALTER TABLE org_memberships ALTER COLUMN role DROP DEFAULT")
    op.execute("ALTER TABLE org_memberships ALTER COLUMN role TYPE VARCHAR USING role::text")
    op.execute("ALTER TABLE org_memberships ALTER COLUMN role SET DEFAULT 'viewer'")
    op.execute(f"ALTER TABLE org_memberships ADD CONSTRAINT org_memberships_role_check CHECK (role IN {valid_roles})")
    
    # Drop the old native enum type
    op.execute("DROP TYPE IF EXISTS role")
    
    # ============================================================
    # 2. document_status enum (documents.status) - remove uppercase duplicates
    # ============================================================
    valid_doc_status = "('uploaded', 'processing', 'ready_for_chunking', 'ready', 'failed')"
    
    # Normalize to lowercase
    op.execute("UPDATE documents SET status = LOWER(status)")
    
    op.execute("ALTER TABLE documents ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE documents ALTER COLUMN status TYPE VARCHAR USING status::text")
    op.execute("ALTER TABLE documents ALTER COLUMN status SET DEFAULT 'uploaded'")
    op.execute(f"ALTER TABLE documents ADD CONSTRAINT documents_status_check CHECK (status IN {valid_doc_status})")
    
    op.execute("DROP TYPE IF EXISTS document_status")
    
    # ============================================================
    # 3. document_type enum (documents.document_type) - remove uppercase duplicates
    # ============================================================
    valid_doc_type = "('rfp', 'rfq', 'rfi', 'knowledge_base', 'other')"
    
    op.execute("UPDATE documents SET document_type = LOWER(document_type)")
    
    op.execute("ALTER TABLE documents ALTER COLUMN document_type DROP DEFAULT")
    op.execute("ALTER TABLE documents ALTER COLUMN document_type TYPE VARCHAR USING document_type::text")
    op.execute("ALTER TABLE documents ALTER COLUMN document_type SET DEFAULT 'other'")
    op.execute(f"ALTER TABLE documents ADD CONSTRAINT documents_document_type_check CHECK (document_type IN {valid_doc_type})")
    
    op.execute("DROP TYPE IF EXISTS document_type")
    
    # ============================================================
    # 4. invite_status enum (org_invites.status) - remove uppercase duplicates
    # ============================================================
    valid_invite_status = "('pending', 'accepted', 'revoked')"
    
    op.execute("UPDATE org_invites SET status = LOWER(status)")
    
    op.execute("ALTER TABLE org_invites ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE org_invites ALTER COLUMN status TYPE VARCHAR USING status::text")
    op.execute("ALTER TABLE org_invites ALTER COLUMN status SET DEFAULT 'pending'")
    op.execute(f"ALTER TABLE org_invites ADD CONSTRAINT org_invites_status_check CHECK (status IN {valid_invite_status})")
    
    op.execute("DROP TYPE IF EXISTS invite_status")
    
    # ============================================================
    # 5. job_status enum (pipeline_jobs.status) - remove uppercase duplicates
    # ============================================================
    valid_job_status = "('queued', 'running', 'succeeded', 'failed', 'retrying')"
    
    op.execute("UPDATE pipeline_jobs SET status = LOWER(status)")
    
    op.execute("ALTER TABLE pipeline_jobs ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE pipeline_jobs ALTER COLUMN status TYPE VARCHAR USING status::text")
    op.execute("ALTER TABLE pipeline_jobs ALTER COLUMN status SET DEFAULT 'queued'")
    op.execute(f"ALTER TABLE pipeline_jobs ADD CONSTRAINT pipeline_jobs_status_check CHECK (status IN {valid_job_status})")
    
    op.execute("DROP TYPE IF EXISTS job_status")
    
    # ============================================================
    # 6. llm_call_status enum (llm_calls.status) - remove uppercase duplicates
    # ============================================================
    valid_llm_call_status = "('success', 'failed', 'cache_hit')"
    
    op.execute("UPDATE llm_calls SET status = LOWER(status)")
    
    op.execute("ALTER TABLE llm_calls ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE llm_calls ALTER COLUMN status TYPE VARCHAR USING status::text")
    op.execute("ALTER TABLE llm_calls ALTER COLUMN status SET DEFAULT 'success'")
    op.execute(f"ALTER TABLE llm_calls ADD CONSTRAINT llm_calls_status_check CHECK (status IN {valid_llm_call_status})")
    
    op.execute("DROP TYPE IF EXISTS llm_call_status")
    
    # ============================================================
    # 7. pipeline_stage enum (pipeline_jobs.current_stage, documents.pipeline_stage)
    #    - remove uppercase duplicates
    # ============================================================
    valid_pipeline_stage = "('extraction', 'chunking', 'embedding', 'completed')"
    
    op.execute("UPDATE pipeline_jobs SET current_stage = LOWER(current_stage)")
    op.execute("UPDATE documents SET pipeline_stage = LOWER(pipeline_stage)")
    
    op.execute("ALTER TABLE pipeline_jobs ALTER COLUMN current_stage DROP DEFAULT")
    op.execute("ALTER TABLE pipeline_jobs ALTER COLUMN current_stage TYPE VARCHAR USING current_stage::text")
    
    op.execute("ALTER TABLE documents ALTER COLUMN pipeline_stage DROP DEFAULT")
    op.execute("ALTER TABLE documents ALTER COLUMN pipeline_stage TYPE VARCHAR USING pipeline_stage::text")
    
    op.execute(f"ALTER TABLE pipeline_jobs ADD CONSTRAINT pipeline_jobs_current_stage_check CHECK (current_stage IN {valid_pipeline_stage})")
    op.execute(f"ALTER TABLE documents ADD CONSTRAINT documents_pipeline_stage_check CHECK (pipeline_stage IN {valid_pipeline_stage})")
    
    op.execute("DROP TYPE IF EXISTS pipeline_stage")
    
    # ============================================================
    # 8. pipeline_stage_status enum (documents.pipeline_stage_status)
    #    - remove uppercase duplicates
    # ============================================================
    valid_pipeline_stage_status = "('queued', 'running', 'succeeded', 'failed', 'skipped')"
    
    op.execute("UPDATE documents SET pipeline_stage_status = LOWER(pipeline_stage_status)")
    
    op.execute("ALTER TABLE documents ALTER COLUMN pipeline_stage_status DROP DEFAULT")
    op.execute("ALTER TABLE documents ALTER COLUMN pipeline_stage_status TYPE VARCHAR USING pipeline_stage_status::text")
    op.execute("ALTER TABLE documents ALTER COLUMN pipeline_stage_status SET DEFAULT 'queued'")
    op.execute(f"ALTER TABLE documents ADD CONSTRAINT documents_pipeline_stage_status_check CHECK (pipeline_stage_status IN {valid_pipeline_stage_status})")
    
    op.execute("DROP TYPE IF EXISTS pipeline_stage_status")
    
    # ============================================================
    # 9. chunk_type enum (chunks.chunk_type) - remove uppercase duplicates
    # ============================================================
    valid_chunk_type = "('text', 'table', 'heading', 'figure', 'code')"
    
    op.execute("UPDATE chunks SET chunk_type = LOWER(chunk_type)")
    
    op.execute("ALTER TABLE chunks ALTER COLUMN chunk_type DROP DEFAULT")
    op.execute("ALTER TABLE chunks ALTER COLUMN chunk_type TYPE VARCHAR USING chunk_type::text")
    op.execute(f"ALTER TABLE chunks ADD CONSTRAINT chunks_chunk_type_check CHECK (chunk_type IN {valid_chunk_type})")
    
    op.execute("DROP TYPE IF EXISTS chunk_type_enum")
    
    # ============================================================
    # 10. audit_log.action and resource_type - these are VARCHAR already, no enum
    #     No action needed for these.
    
    # ============================================================
    # 11. feature_flags - no enum columns
    pass


def downgrade() -> None:
    """Downgrade schema: recreate native enums and restore columns."""
    
    # Recreate native enum types
    op.execute("CREATE TYPE role AS ENUM ('admin', 'proposal_manager', 'sales', 'presales_architect', 'legal', 'security', 'compliance', 'viewer')")
    op.execute("CREATE TYPE document_status AS ENUM ('uploaded', 'processing', 'ready_for_chunking', 'ready', 'failed')")
    op.execute("CREATE TYPE document_type AS ENUM ('rfp', 'rfq', 'rfi', 'knowledge_base', 'other')")
    op.execute("CREATE TYPE invite_status AS ENUM ('pending', 'accepted', 'revoked')")
    op.execute("CREATE TYPE job_status AS ENUM ('queued', 'running', 'succeeded', 'failed', 'retrying')")
    op.execute("CREATE TYPE llm_call_status AS ENUM ('success', 'failed', 'cache_hit')")
    op.execute("CREATE TYPE pipeline_stage AS ENUM ('extraction', 'chunking', 'embedding', 'completed')")
    op.execute("CREATE TYPE pipeline_stage_status AS ENUM ('queued', 'running', 'succeeded', 'failed', 'skipped')")
    op.execute("CREATE TYPE chunk_type_enum AS ENUM ('text', 'table', 'heading', 'figure', 'code')")
    
    # Drop CHECK constraints
    op.execute("ALTER TABLE org_memberships DROP CONSTRAINT IF EXISTS org_memberships_role_check")
    op.execute("ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_status_check")
    op.execute("ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_document_type_check")
    op.execute("ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_pipeline_stage_check")
    op.execute("ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_pipeline_stage_status_check")
    op.execute("ALTER TABLE org_invites DROP CONSTRAINT IF EXISTS org_invites_status_check")
    op.execute("ALTER TABLE pipeline_jobs DROP CONSTRAINT IF EXISTS pipeline_jobs_status_check")
    op.execute("ALTER TABLE pipeline_jobs DROP CONSTRAINT IF EXISTS pipeline_jobs_current_stage_check")
    op.execute("ALTER TABLE llm_calls DROP CONSTRAINT IF EXISTS llm_calls_status_check")
    op.execute("ALTER TABLE chunks DROP CONSTRAINT IF EXISTS chunks_chunk_type_check")
    
    # Convert columns back to native enum types
    # First drop defaults, then convert type, then re-add defaults
    op.execute("ALTER TABLE org_memberships ALTER COLUMN role DROP DEFAULT")
    op.execute("ALTER TABLE org_memberships ALTER COLUMN role TYPE role USING role::role")
    op.execute("ALTER TABLE org_memberships ALTER COLUMN role SET DEFAULT 'viewer'::role")
    
    op.execute("ALTER TABLE documents ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE documents ALTER COLUMN status TYPE document_status USING status::document_status")
    op.execute("ALTER TABLE documents ALTER COLUMN status SET DEFAULT 'uploaded'::document_status")
    
    op.execute("ALTER TABLE documents ALTER COLUMN document_type DROP DEFAULT")
    op.execute("ALTER TABLE documents ALTER COLUMN document_type TYPE document_type USING document_type::document_type")
    op.execute("ALTER TABLE documents ALTER COLUMN document_type SET DEFAULT 'other'::document_type")
    
    op.execute("ALTER TABLE documents ALTER COLUMN pipeline_stage DROP DEFAULT")
    op.execute("ALTER TABLE documents ALTER COLUMN pipeline_stage TYPE pipeline_stage USING pipeline_stage::pipeline_stage")
    
    op.execute("ALTER TABLE documents ALTER COLUMN pipeline_stage_status DROP DEFAULT")
    op.execute("ALTER TABLE documents ALTER COLUMN pipeline_stage_status TYPE pipeline_stage_status USING pipeline_stage_status::pipeline_stage_status")
    op.execute("ALTER TABLE documents ALTER COLUMN pipeline_stage_status SET DEFAULT 'queued'::pipeline_stage_status")
    
    op.execute("ALTER TABLE org_invites ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE org_invites ALTER COLUMN status TYPE invite_status USING status::invite_status")
    op.execute("ALTER TABLE org_invites ALTER COLUMN status SET DEFAULT 'pending'::invite_status")
    
    op.execute("ALTER TABLE pipeline_jobs ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE pipeline_jobs ALTER COLUMN status TYPE job_status USING status::job_status")
    op.execute("ALTER TABLE pipeline_jobs ALTER COLUMN status SET DEFAULT 'queued'::job_status")
    
    op.execute("ALTER TABLE pipeline_jobs ALTER COLUMN current_stage DROP DEFAULT")
    op.execute("ALTER TABLE pipeline_jobs ALTER COLUMN current_stage TYPE pipeline_stage USING current_stage::pipeline_stage")
    
    op.execute("ALTER TABLE llm_calls ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE llm_calls ALTER COLUMN status TYPE llm_call_status USING status::llm_call_status")
    op.execute("ALTER TABLE llm_calls ALTER COLUMN status SET DEFAULT 'success'::llm_call_status")
    
    op.execute("ALTER TABLE chunks ALTER COLUMN chunk_type DROP DEFAULT")
    op.execute("ALTER TABLE chunks ALTER COLUMN chunk_type TYPE chunk_type_enum USING chunk_type::chunk_type_enum")