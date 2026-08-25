"""FastAPI dependencies for organization module."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Role
from app.db.session import get_db_session
from app.modules.auth.dependencies import require_org_member, require_org_role
from app.modules.orgs.service import OrgsService


async def get_orgs_service(session: AsyncSession = Depends(get_db_session)) -> OrgsService:
    """Get the organizations service."""
    return OrgsService(session)


# Thin aliases for OpenAPI clarity
get_current_org = require_org_member
require_org_admin = require_org_role(Role.ADMIN)

__all__ = ["get_orgs_service", "get_current_org", "require_org_member", "require_org_admin", "require_org_role"]
