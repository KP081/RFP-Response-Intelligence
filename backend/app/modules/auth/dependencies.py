"""FastAPI dependencies for authentication and authorization."""

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OrgMembership, Role, User
from app.db.session import get_db_session
from app.modules.auth.schemas import TokenPayload
from app.modules.auth.service import AuthService

security = HTTPBearer(auto_error=False)


async def get_auth_service(session: AsyncSession = Depends(get_db_session)) -> AuthService:
    """Get the authentication service."""
    return AuthService(session)


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> User:
    """Validate the JWT access token and return the current user."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        token_payload: TokenPayload = auth_service.decode_token(credentials.credentials)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    if token_payload.type != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = uuid.UUID(token_payload.user_id)
    user = await auth_service.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Attach user to request state for potential use in other dependencies
    request.state.current_user = user
    return user


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


async def require_role_dependency(
    allowed_roles: set[str],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    org_id: uuid.UUID,
) -> OrgMembership:
    """Check if the current user has one of the allowed roles in the given org."""
    membership_data = await auth_service.get_membership(current_user.id, org_id)

    if membership_data is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )

    org, membership, role = membership_data

    if role.value not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires one of roles: {', '.join(allowed_roles)}",
        )

    # Set the RLS context variable for this session
    await session.execute(
        text("SET LOCAL app.current_org_id = :org_id"),
        {"org_id": str(org_id)},
    )

    return membership


def require_role(*roles: Role) -> Callable[..., Awaitable[OrgMembership]]:
    """Dependency factory for role-based access control.

    Usage:
        @router.get("/admin-only")
        async def admin_endpoint(
            membership: Annotated[OrgMembership, Depends(require_role(Role.ADMIN))]
        ):
            ...

    This dependency composes with current_org - the org_id is extracted from the path
    parameter named 'org_id' in the route.
    """
    allowed_role_values = {role.value for role in roles}

    async def role_dependency(
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[AsyncSession, Depends(get_db_session)],
        auth_service: Annotated[AuthService, Depends(get_auth_service)],
        request: Request,
    ) -> OrgMembership:
        # Extract org_id from path parameters
        org_id_str = request.path_params.get("org_id")
        if not org_id_str:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Organization ID is required",
            )

        try:
            org_id = uuid.UUID(org_id_str)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid organization ID",
            )

        return await require_role_dependency(
            allowed_role_values, current_user, session, auth_service, org_id
        )

    return role_dependency