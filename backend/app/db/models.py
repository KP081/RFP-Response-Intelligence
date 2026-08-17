"""SQLAlchemy ORM models for the core data model."""

import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

if TYPE_CHECKING:
    pass


class DocumentType(str, Enum):
    """Enumeration of document types."""

    RFP = "rfp"
    RFQ = "rfq"
    RFI = "rfi"
    KNOWLEDGE_BASE = "knowledge_base"
    OTHER = "other"


class DocumentStatus(str, Enum):
    """Enumeration of document statuses."""

    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY_FOR_CHUNKING = "ready_for_chunking"
    READY = "ready"
    FAILED = "failed"


class PipelineStage(str, Enum):
    """Enumeration of pipeline stages."""

    EXTRACT = "extract"
    CHUNK = "chunk"
    EMBED = "embed"
    OCR = "ocr"
    CAPTION_FIGURES = "caption_figures"
    DEDUPE = "dedupe"


class PipelineStageStatus(str, Enum):
    """Enumeration of pipeline stage statuses."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class InviteStatus(str, Enum):
    """Enumeration of invite statuses."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"


class JobStatus(str, Enum):
    """Enumeration of pipeline job statuses."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRYING = "retrying"


class LLMCallStatus(str, Enum):
    """Enumeration of LLM call statuses."""

    SUCCESS = "success"
    FAILED = "failed"
    CACHE_HIT = "cache_hit"


class ChunkType(str, Enum):
    """Enumeration of chunk types."""

    TEXT = "text"
    TABLE = "table"
    HEADING = "heading"


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""

    pass


class Role(str, Enum):
    """Enumeration of all possible user roles in the system."""

    ADMIN = "admin"
    PROPOSAL_MANAGER = "proposal_manager"
    SALES = "sales"
    PRESALES_ARCHITECT = "presales_architect"
    LEGAL = "legal"
    SECURITY = "security"
    COMPLIANCE = "compliance"
    VIEWER = "viewer"


class TenantScopedMixin:
    """Mixin providing org_id column and RLS support for tenant-scoped tables."""

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    @classmethod
    def _get_rls_policy_name(cls, org_column: str = "org_id") -> str:
        """Generate the name of the RLS policy for this table."""
        return f"{cls.__tablename__}_rls_policy"  # type: ignore[attr-defined]


class Org(Base):
    """Organization tenant root — not itself RLS-scoped."""

    __tablename__ = "orgs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    memberships: Mapped[list["OrgMembership"]] = relationship(
        back_populates="org", cascade="all, delete-orphan"
    )
    audit_log_entries: Mapped[list["AuditLogEntry"]] = relationship(
        back_populates="org", cascade="all, delete-orphan"
    )
    feature_flags: Mapped[list["FeatureFlag"]] = relationship(
        back_populates="org", cascade="all, delete-orphan"
    )
    invites: Mapped[list["OrgInvite"]] = relationship(
        back_populates="org", cascade="all, delete-orphan"
    )


class User(Base):
    """User identity — global (not org-scoped)."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    external_idp_subject: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    memberships: Mapped[list["OrgMembership"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    audit_log_entries: Mapped[list["AuditLogEntry"]] = relationship(
        back_populates="actor", cascade="all, delete-orphan"
    )


class OrgMembership(Base, TenantScopedMixin):
    """Maps users to organizations with specific roles — RLS-scoped."""

    __tablename__ = "org_memberships"
    __table_args__ = (UniqueConstraint("org_id", "user_id", name="uq_org_user"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[Role] = mapped_column(
        SQLEnum(Role, native_enum=False), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    org: Mapped["Org"] = relationship(back_populates="memberships")
    user: Mapped["User"] = relationship(back_populates="memberships")


class AuditLogEntry(Base, TenantScopedMixin):
    """Immutable audit log for all state-changing operations — RLS-scoped."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    org: Mapped["Org"] = relationship(back_populates="audit_log_entries")
    actor: Mapped[Optional["User"]] = relationship(back_populates="audit_log_entries")


class FeatureFlag(Base, TenantScopedMixin):
    """DB-backed feature flags per org — RLS-scoped."""

    __tablename__ = "feature_flags"
    __table_args__ = (
        UniqueConstraint("org_id", "flag_name", name="uq_org_flag_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    flag_name: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    config: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSON, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    org: Mapped["Org"] = relationship(back_populates="feature_flags")


class OrgInvite(Base, TenantScopedMixin):
    """Organization invite — RLS-scoped."""

    __tablename__ = "org_invites"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(
        SQLEnum(Role, native_enum=False), nullable=False
    )
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    invited_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[InviteStatus] = mapped_column(
        SQLEnum(InviteStatus, native_enum=False), nullable=False, default=InviteStatus.PENDING
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # Relationships
    org: Mapped["Org"] = relationship(back_populates="invites")
    invited_by: Mapped["User"] = relationship(foreign_keys=[invited_by_user_id])


class Document(Base, TenantScopedMixin):
    """Document metadata — RLS-scoped."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    document_type: Mapped[DocumentType] = mapped_column(
        SQLEnum(DocumentType, native_enum=False), nullable=False, default=DocumentType.OTHER
    )
    status: Mapped[DocumentStatus] = mapped_column(
        SQLEnum(DocumentStatus, native_enum=False), nullable=False, default=DocumentStatus.UPLOADED
    )
    pipeline_stage: Mapped[PipelineStage | None] = mapped_column(
        SQLEnum(PipelineStage, native_enum=False), nullable=True
    )
    pipeline_stage_status: Mapped[PipelineStageStatus] = mapped_column(
        SQLEnum(PipelineStageStatus, native_enum=False), nullable=False, default=PipelineStageStatus.QUEUED
    )
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    uploaded_by: Mapped["User"] = relationship()
    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentVersion.created_at"
    )


class DocumentVersion(Base, TenantScopedMixin):
    """Document version history — RLS-scoped."""

    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "id", name="uq_document_version"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    document: Mapped["Document"] = relationship(back_populates="versions")


class RawExtraction(Base, TenantScopedMixin):
    """Raw extraction output from document ingestion — RLS-scoped."""

    __tablename__ = "raw_extractions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    blocks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    extractor_used: Mapped[str] = mapped_column(String(50), nullable=False)
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    document: Mapped["Document"] = relationship()
    version: Mapped["DocumentVersion"] = relationship()


class PipelineJob(Base, TenantScopedMixin):
    """Generic pipeline job status tracking — RLS-scoped."""

    __tablename__ = "pipeline_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[JobStatus] = mapped_column(
        SQLEnum(JobStatus, native_enum=False), nullable=False, default=JobStatus.QUEUED
    )
    current_stage: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    progress_pct: Mapped[int] = mapped_column(nullable=False, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(String(5000), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class LLMCall(Base, TenantScopedMixin):
    """LLM call logging for cost tracking and observability — RLS-scoped."""

    __tablename__ = "llm_calls"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    task_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model_tier: Mapped[str] = mapped_column(String(50), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    input_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(nullable=False, default=0)
    cost_estimate: Mapped[float] = mapped_column(nullable=False, default=0.0)
    status: Mapped[LLMCallStatus] = mapped_column(
        SQLEnum(LLMCallStatus, native_enum=False), nullable=False, default=LLMCallStatus.SUCCESS
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Chunk(Base, TenantScopedMixin):
    """Document chunk for retrieval — RLS-scoped."""

    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(nullable=False)
    chunk_type: Mapped[ChunkType] = mapped_column(
        SQLEnum(ChunkType, native_enum=False), nullable=False
    )
    page_start: Mapped[int] = mapped_column(nullable=False)
    page_end: Mapped[int] = mapped_column(nullable=False)
    section_path: Mapped[Optional[str]] = mapped_column(nullable=True)
    token_count: Mapped[int] = mapped_column(nullable=False, default=0)
    embedding: Mapped[Optional[list[float]]] = mapped_column(Vector(1536), nullable=True)
    search_vector: Mapped[str] = mapped_column(
        sa.dialects.postgresql.TSVECTOR,
        sa.Computed("to_tsvector('english', coalesce(content, ''))", persisted=True),
        nullable=False,
        insert_default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    document: Mapped["Document"] = relationship()
    version: Mapped["DocumentVersion"] = relationship()
