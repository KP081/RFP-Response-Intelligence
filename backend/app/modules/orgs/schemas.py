"""Pydantic schemas for organizations module."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr


class OrgCreate(BaseModel):
    """Schema for creating an organization."""

    name: str


class OrgResponse(BaseModel):
    """Schema for organization response."""

    id: UUID
    name: str
    settings: dict[str, object]
    created_at: datetime


class OrgMemberResponse(BaseModel):
    """Schema for organization member response."""

    user_id: UUID
    display_name: str
    email: str
    role: str
    joined_at: datetime


class InviteCreate(BaseModel):
    """Schema for creating an invite."""

    email: EmailStr
    role: str


class InviteResponse(BaseModel):
    """Schema for invite response."""

    id: UUID
    org_id: UUID
    email: str
    role: str
    token: str
    invited_by_user_id: UUID
    status: str
    created_at: datetime
    expires_at: datetime
    invite_link: str


class InviteAcceptResponse(BaseModel):
    """Schema for invite acceptance response."""

    org_id: UUID
    org_name: str
    role: str
    message: str


class MemberUpdate(BaseModel):
    """Schema for updating a member's role."""

    role: str


class MemberRemoveResponse(BaseModel):
    """Schema for member removal response."""

    message: str


class AuditLogEntryResponse(BaseModel):
    """Schema for audit log entry response."""

    id: UUID
    org_id: UUID
    actor_user_id: UUID | None
    action: str
    resource_type: str
    resource_id: str
    event_metadata: dict[str, object]
    correlation_id: str
    created_at: datetime


class AuditLogListResponse(BaseModel):
    """Schema for paginated audit log list response."""

    items: list[AuditLogEntryResponse]
    total: int
    page: int
    page_size: int