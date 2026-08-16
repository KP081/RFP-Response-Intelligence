"""FastAPI dependencies for organization module."""

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OrgMembership, Role, User
from app.db.session import get_db_session
from app.modules.auth.dependencies import get_auth_service, get_current_user
from app.modules.auth.service import AuthService
from app.modules.orgs.service import OrgsService


async def get_orgs_service(session: AsyncSession = Depends(get_db_session)) -> OrgsService:
    """Get the organizations service."""
    return OrgsService(session)


async def get_current_org(
    org_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> OrgMembership:
    """Validate that the current user has membership in the requested org.

    Also sets the RLS context variable `app.current_org_id` on the database session.
    """

    membership_data = await auth_service.get_membership(current_user.id, org_id)

    if membership_data is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )

    org, membership, role = membership_data

    # Set the RLS context variable for this session
    await session.execute(
        text("SET LOCAL app.current_org_id = :org_id"),
        {"org_id": str(org_id)},
    )

    return membership


async def require_org_admin(
    org_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> OrgMembership:
    """Check if the current user is an admin in the given org."""
    membership_data = await auth_service.get_membership(current_user.id, org_id)

    if membership_data is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )

    org, membership, role = membership_data

    if role != Role.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires admin role",
        )

    # Set the RLS context variable for this session
    await session.execute(
        text("SET LOCAL app.current_org_id = :org_id"),
        {"org_id": str(org_id)},
    )

    return membership


async def require_org_member(
    org_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> OrgMembership:
    """Check if the current user is a member of the given org (any role)."""
    membership_data = await auth_service.get_membership(current_user.id, org_id)

    if membership_data is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )

    org, membership, role = membership_data

    # Set the RLS context variable for this session
    await session.execute(
        text("SET LOCAL app.current_org_id = :org_id"),
        {"org_id": str(org_id)},
    )

    return membership
