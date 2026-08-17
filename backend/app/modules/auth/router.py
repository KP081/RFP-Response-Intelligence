"""Authentication router for OIDC login flow and session management."""

import secrets
import uuid
from datetime import datetime, timezone
from collections.abc import Callable, AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import settings
from app.db.models import OrgMembership, Role, User
from app.modules.auth.dependencies import (
    get_auth_service,
    get_current_user,
    require_role,
)
from app.modules.auth.schemas import (
    MeResponse,
    PKCEState,
    TokenResponse,
)
from app.modules.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["authentication"])

# In-memory PKCE state storage (in production, use Redis)
_pkce_states: dict[str, PKCEState] = {}


def _cleanup_expired_pkce_states() -> None:
    """Remove expired PKCE states (older than 10 minutes)."""
    now = datetime.now(timezone.utc)
    expired = [
        state for state, data in _pkce_states.items()
        if (now - data.state_created).total_seconds() > 600
    ]
    for state in expired:
        del _pkce_states[state]


@router.get("/login")
async def login(
    request: Request,
    redirect_uri: Annotated[str, Query(description="Redirect URI after login")] = "http://localhost:5173/auth/callback",
    auth_service: AuthService = Depends(get_auth_service),
) -> RedirectResponse:
    """Initiate OIDC login flow with PKCE."""
    _cleanup_expired_pkce_states()

    state = secrets.token_urlsafe(32)
    code_verifier, code_challenge = auth_service.generate_pkce_pair()

    # Store PKCE state
    _pkce_states[state] = PKCEState(
        code_verifier=code_verifier,
        state=state,
        redirect_uri=redirect_uri,
        state_created=datetime.now(timezone.utc),
    )

    authorization_url = auth_service.get_authorization_url(
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=code_challenge,
    )

    return RedirectResponse(url=authorization_url)


def get_db_session_dependency() -> Callable[..., AsyncIterator[AsyncSession]]:
    """Lazy dependency for database session to avoid circular imports."""
    from app.db.session import get_db_session
    return get_db_session


@router.get("/callback")
async def callback(
    request: Request,
    code: Annotated[str, Query()],
    state: Annotated[str, Query()],
    auth_service: AuthService = Depends(get_auth_service),
    session: AsyncSession = Depends(get_db_session_dependency),
) -> Response:
    """Handle OIDC callback, exchange code for tokens, and issue app tokens."""
    # Retrieve and validate PKCE state
    pkce_state = _pkce_states.pop(state, None)
    if pkce_state is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired state parameter",
        )

    if pkce_state.state != state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="State mismatch",
        )

    # Exchange code for tokens from IdP
    try:
        idp_tokens = await auth_service.exchange_code_for_tokens(
            code=code,
            redirect_uri=pkce_state.redirect_uri,
            code_verifier=pkce_state.code_verifier,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to exchange code for tokens: {str(e)}",
        ) from e

    # Get user info from IdP
    try:
        userinfo = await auth_service.get_userinfo(idp_tokens["access_token"])
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to get user info: {str(e)}",
        ) from e

    # Extract user details
    external_idp_subject = userinfo.get("sub")
    email = userinfo.get("email")
    given_name = userinfo.get("given_name", "")
    family_name = userinfo.get("family_name", "")
    display_name: str = userinfo.get("name") or f"{given_name} {family_name}".strip() or (email or "")

    if not external_idp_subject or not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required user info from IdP",
        )

    # Upsert user in our database
    user = await auth_service.upsert_user(
        external_idp_subject=external_idp_subject,
        email=EmailStr(email),
        display_name=display_name,
    )

    # Create our application tokens
    access_token = auth_service.create_access_token(user)
    refresh_token = auth_service.create_refresh_token(user)

    await session.commit()

    # Set tokens in httpOnly cookies
    response = RedirectResponse(url=pkce_state.redirect_uri.replace("/auth/callback", ""))

    # Access token cookie (short-lived)
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        max_age=settings.jwt_access_token_expire_minutes * 60,
        path="/",
    )

    # Refresh token cookie (long-lived)
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        max_age=settings.jwt_refresh_token_expire_days * 24 * 60 * 60,
        path="/api/v1/auth",
    )

    return response


@router.post("/refresh")
async def refresh(
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
    session: AsyncSession = Depends(get_db_session_dependency),
) -> TokenResponse:
    """Refresh the access token using the refresh token."""
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No refresh token",
        )

    try:
        token_payload = auth_service.decode_token(refresh_token)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        ) from e

    if token_payload.type != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )

    user_id = uuid.UUID(token_payload.user_id)
    user = await auth_service.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    # Create new tokens
    new_access_token = auth_service.create_access_token(user)
    new_refresh_token = auth_service.create_refresh_token(user)

    # Set new tokens in cookies
    response.set_cookie(
        key="access_token",
        value=new_access_token,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        max_age=settings.jwt_access_token_expire_minutes * 60,
        path="/",
    )

    response.set_cookie(
        key="refresh_token",
        value=new_refresh_token,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        max_age=settings.jwt_refresh_token_expire_days * 24 * 60 * 60,
        path="/api/v1/auth",
    )

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


@router.get("/me", response_model=MeResponse)
async def me(
    current_user: Annotated[User, Depends(get_current_user)],
    auth_service: AuthService = Depends(get_auth_service),
) -> MeResponse:
    """Get current user info and their org memberships."""
    return await auth_service.build_me_response(current_user)


@router.post("/logout")
async def logout(response: Response) -> dict[str, str]:
    """Logout by clearing auth cookies."""
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="refresh_token", path="/api/v1/auth")
    return {"message": "Successfully logged out"}


# Test endpoint to verify RBAC
@router.get("/test-rbac/{org_id}")
async def test_rbac(
    org_id: uuid.UUID,
    membership: Annotated[OrgMembership, Depends(require_role(Role.ADMIN, Role.PROPOSAL_MANAGER))],
) -> dict[str, str]:
    """Test endpoint that requires admin or proposal_manager role in the org."""
    return {
        "message": "Access granted",
        "org_id": str(org_id),
        "role": membership.role.value,
    }


@router.get("/test-org-access/{org_id}")
async def test_org_access(
    org_id: uuid.UUID,
    membership: Annotated[OrgMembership, Depends(require_role(Role.VIEWER))],
) -> dict[str, str]:
    """Test endpoint that requires at least viewer role in the org."""
    return {
        "message": "Org access granted",
        "org_id": str(org_id),
        "role": membership.role.value,
    }