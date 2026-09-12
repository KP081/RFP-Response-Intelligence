"""FastAPI dependencies for organization module."""

import uuid

from fastapi import Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OrgMembership, Role, User
from app.db.session import get_db_session
from app.modules.auth.dependencies import (
    AuthService,
    get_current_org as get_current_org_auth,
    get_current_user,
    require_org_member,
    require_org_role,
)
from app.modules.orgs.service import OrgsService


async def get_orgs_service(session: AsyncSession = Depends(get_db_session)) -> OrgsService:
    """Get the organizations service."""
    return OrgsService(session)


get_current_org = get_current_org_auth


async def require_org_admin(
    org_id: uuid.UUID,
    current_user: User,
    session: AsyncSession,
    auth_service: AuthService,
) -> OrgMembership:
    """Direct helper used in unit tests to verify the org admin rule."""
    membership_data = await auth_service.get_membership(current_user.id, org_id)
    if membership_data is None:
        raise HTTPException(status_code=403, detail="Not a member of this organization")

    _, membership, role = membership_data
    if role.value != Role.ADMIN.value:
        raise HTTPException(status_code=403, detail="Requires admin role")

    await session.execute(
        text("SELECT set_config('app.current_org_id', :org_id, true)"),
        {"org_id": str(org_id)},
    )
    return membership


__all__ = [
    "get_orgs_service",
    "get_current_org",
    "require_org_member",
    "require_org_admin",
    "require_org_role",
    "get_current_user",
]
