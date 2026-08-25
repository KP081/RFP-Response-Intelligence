"""Organizations router for org management and membership."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import settings
from app.db.models import OrgMembership, Role, User
from app.db.session import get_db_session
from app.modules.auth.dependencies import (
    get_current_user,
    require_org_role,
)
from app.modules.orgs.dependencies import (
    get_orgs_service,
    require_org_admin,
)
from app.modules.orgs.schemas import (
    AuditLogEntryResponse,
    AuditLogListResponse,
    InviteAcceptResponse,
    InviteCreate,
    InviteResponse,
    MemberRemoveResponse,
    MemberUpdate,
    OrgCreate,
    OrgMemberResponse,
    OrgResponse,
)
from app.modules.orgs.service import OrgsService

router = APIRouter(prefix="/orgs", tags=["organizations"])


@router.post("", response_model=OrgResponse, status_code=status.HTTP_201_CREATED)
async def create_org(
    org_data: OrgCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    orgs_service: Annotated[OrgsService, Depends(get_orgs_service)],
) -> OrgResponse:
    """Create a new organization. The creator becomes admin."""
    org = await orgs_service.create_org(org_data.name, current_user.id)
    return OrgResponse(
        id=org.id,
        name=org.name,
        settings=org.settings,
        created_at=org.created_at,
    )


@router.get("/{org_id}", response_model=OrgResponse)
async def get_org(
    org_id: uuid.UUID,
    membership: Annotated[OrgMembership, Depends(require_org_role(Role.VIEWER))],
    orgs_service: Annotated[OrgsService, Depends(get_orgs_service)],
) -> OrgResponse:
    """Get organization by ID."""
    org = await orgs_service.get_org(org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    return OrgResponse(
        id=org.id,
        name=org.name,
        settings=org.settings,
        created_at=org.created_at,
    )


@router.get("/{org_id}/members", response_model=list[OrgMemberResponse])
async def list_members(
    org_id: uuid.UUID,
    membership: Annotated[OrgMembership, Depends(require_org_role(Role.VIEWER))],
    orgs_service: Annotated[OrgsService, Depends(get_orgs_service)],
) -> list[OrgMemberResponse]:
    """List all members of an organization. Any member can view."""
    members_data = await orgs_service.get_org_members(org_id)
    return [
        OrgMemberResponse(
            user_id=user.id,
            display_name=user.display_name,
            email=user.email,
            role=membership.role.value,
            joined_at=membership.created_at,
        )
        for user, membership in members_data
    ]


@router.post("/{org_id}/invites", response_model=InviteResponse, status_code=status.HTTP_201_CREATED)
async def create_invite(
    org_id: uuid.UUID,
    invite_data: InviteCreate,
    membership: Annotated[OrgMembership, Depends(require_org_admin)],
    orgs_service: Annotated[OrgsService, Depends(get_orgs_service)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> InviteResponse:
    """Create an organization invite. Requires admin role."""
    # Validate role
    try:
        role = Role(invite_data.role)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role. Must be one of: {[r.value for r in Role]}",
        )

    invite = await orgs_service.create_invite(
        org_id=org_id,
        email=invite_data.email,
        role=role,
        invited_by_user_id=current_user.id,
    )

    invite_link = f"{settings.frontend_url}/invites/{invite.token}"

    return InviteResponse(
        id=invite.id,
        org_id=invite.org_id,
        email=invite.email,
        role=invite.role.value,
        token=invite.token,
        invited_by_user_id=invite.invited_by_user_id,
        status=invite.status.value,
        created_at=invite.created_at,
        expires_at=invite.expires_at,
        invite_link=invite_link,
    )


@router.post("/invites/{token}/accept", response_model=InviteAcceptResponse)
async def accept_invite(
    token: str,
    current_user: Annotated[User, Depends(get_current_user)],
    orgs_service: Annotated[OrgsService, Depends(get_orgs_service)],
) -> InviteAcceptResponse:
    """Accept an organization invite."""
    try:
        org, membership, role = await orgs_service.accept_invite(token, current_user.id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    return InviteAcceptResponse(
        org_id=org.id,
        org_name=org.name,
        role=role.value,
        message=f"Successfully joined {org.name} as {role.value}",
    )


@router.patch("/{org_id}/members/{user_id}", response_model=OrgMemberResponse)
async def update_member_role(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    member_update: MemberUpdate,
    membership: Annotated[OrgMembership, Depends(require_org_admin)],
    orgs_service: Annotated[OrgsService, Depends(get_orgs_service)],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrgMemberResponse:
    """Update a member's role. Requires admin role."""
    # Validate role
    try:
        new_role = Role(member_update.role)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role. Must be one of: {[r.value for r in Role]}",
        )

    # Prevent admin from removing their own admin role if they're the only admin
    if membership.user_id == user_id and new_role != Role.ADMIN:
        # Check if there are other admins
        stmt = (
            select(OrgMembership)
            .where(OrgMembership.org_id == org_id, OrgMembership.role == Role.ADMIN)
        )
        result = await session.execute(stmt)
        admins = result.scalars().all()
        if len(admins) == 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove the last admin from the organization",
            )

    updated_membership = await orgs_service.update_member_role(
        org_id, user_id, new_role, membership.user_id
    )
    if not updated_membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found",
        )

    # Get user info for response
    stmt = select(User).where(User.id == user_id)  # type: ignore[assignment]
    result = await session.execute(stmt)
    user = result.scalar_one()

    return OrgMemberResponse(
        user_id=user.id,
        display_name=user.display_name,  # type: ignore[attr-defined]
        email=user.email,  # type: ignore[attr-defined]
        role=updated_membership.role.value,
        joined_at=updated_membership.created_at,
    )


@router.delete("/{org_id}/members/{user_id}", response_model=MemberRemoveResponse)
async def remove_member(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    membership: Annotated[OrgMembership, Depends(require_org_admin)],
    orgs_service: Annotated[OrgsService, Depends(get_orgs_service)],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MemberRemoveResponse:
    """Remove a member from the organization. Requires admin role."""
    # Prevent admin from removing themselves if they're the only admin
    if membership.user_id == user_id:
        stmt = (
            select(OrgMembership)
            .where(OrgMembership.org_id == org_id, OrgMembership.role == Role.ADMIN)
        )
        result = await session.execute(stmt)
        admins = result.scalars().all()
        if len(admins) == 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove the last admin from the organization",
            )

    success = await orgs_service.remove_member(org_id, user_id, membership.user_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found",
        )

    return MemberRemoveResponse(message="Member removed successfully")


@router.get("/{org_id}/audit-log", response_model=AuditLogListResponse)
async def list_audit_log(
    org_id: uuid.UUID,
    membership: Annotated[OrgMembership, Depends(require_org_role(Role.ADMIN, Role.SECURITY, Role.COMPLIANCE))],
    page: int = 1,
    page_size: int = 50,
    resource_type: str | None = None,
    action: str | None = None,
    actor_user_id: uuid.UUID | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    session: Annotated[AsyncSession, Depends(get_db_session)] = None,  # type: ignore[assignment]
) -> AuditLogListResponse:
    """List audit log entries for an organization.

    Requires admin, security, or compliance role.
    Supports filtering by resource_type, action, actor_user_id, and date range.
    """
    from datetime import datetime

    from sqlalchemy import and_, func, select

    from app.db.models import AuditLogEntry

    stmt = select(AuditLogEntry).where(AuditLogEntry.org_id == org_id)

    filters = []
    if resource_type:
        filters.append(AuditLogEntry.resource_type == resource_type)
    if action:
        filters.append(AuditLogEntry.action == action)
    if actor_user_id:
        filters.append(AuditLogEntry.actor_user_id == actor_user_id)
    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            filters.append(AuditLogEntry.created_at >= start_dt)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid start_date format. Use ISO 8601.",
            )
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            filters.append(AuditLogEntry.created_at <= end_dt)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid end_date format. Use ISO 8601.",
            )

    if filters:
        stmt = stmt.where(and_(*filters))

    # Order by created_at desc
    stmt = stmt.order_by(AuditLogEntry.created_at.desc())

    # Count total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    # Apply pagination
    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)

    result = await session.execute(stmt)
    entries = result.scalars().all()

    return AuditLogListResponse(
        items=[
            AuditLogEntryResponse(
                id=entry.id,
                org_id=entry.org_id,
                actor_user_id=entry.actor_user_id,
                action=entry.action,
                resource_type=entry.resource_type,
                resource_id=entry.resource_id,
                event_metadata=entry.event_metadata,
                correlation_id=entry.correlation_id,
                created_at=entry.created_at,
            )
            for entry in entries
        ],
        total=total,
        page=page,
        page_size=page_size,
    )