"""SQLAlchemy ORM models for the core data model."""

import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

if TYPE_CHECKING:
    pass


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
        return f"{cls.__tablename__}_rls_policy"


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
