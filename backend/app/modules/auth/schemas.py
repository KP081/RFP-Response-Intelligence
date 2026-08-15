"""Pydantic schemas for authentication module."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr


class TokenResponse(BaseModel):
    """OAuth2 token response."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenPayload(BaseModel):
    """JWT token payload."""

    sub: str
    user_id: str
    exp: int
    iat: int
    type: str


class UserResponse(BaseModel):
    """User information response."""

    id: UUID
    email: EmailStr
    display_name: str
    external_idp_subject: Optional[str] = None
    created_at: datetime


class OrgMembershipResponse(BaseModel):
    """Organization membership response."""

    org_id: UUID
    org_name: str
    role: str


class MeResponse(BaseModel):
    """Current user response with memberships."""

    user: UserResponse
    memberships: list[OrgMembershipResponse]


class LogoutResponse(BaseModel):
    """Logout response."""

    message: str = "Successfully logged out"


class AuthErrorResponse(BaseModel):
    """Authentication error response."""

    error: str
    error_description: Optional[str] = None


class CallbackRequest(BaseModel):
    """OIDC callback request parameters."""

    code: str
    state: str


class PKCEState(BaseModel):
    """PKCE state stored in session/cookie."""

    code_verifier: str
    state: str
    redirect_uri: str
    state_created: datetime