"""Authentication module."""

from app.modules.auth.dependencies import (
    get_current_user,
    require_org_member,
    require_org_role,
)
from app.modules.auth.router import router as auth_router
from app.modules.auth.schemas import (
    MeResponse,
    OrgMembershipResponse,
    TokenResponse,
    UserResponse,
)
from app.modules.auth.service import AuthService

__all__ = [
    "auth_router",
    "AuthService",
    "get_current_user",
    "require_org_member",
    "require_org_role",
    "TokenResponse",
    "UserResponse",
    "OrgMembershipResponse",
    "MeResponse",
]