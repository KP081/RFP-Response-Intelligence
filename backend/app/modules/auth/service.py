"""Authentication service for OIDC flow and JWT token management."""

import base64
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from authlib.integrations.httpx_client import AsyncOAuth2Client
from jose import jwt
from pydantic import EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import settings
from app.db.models import Org, OrgMembership, Role, User
from app.modules.auth.schemas import (
    MeResponse,
    OrgMembershipResponse,
    TokenPayload,
    UserResponse,
)


class AuthService:
    """Service for handling authentication operations."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self._oauth_client: Optional[AsyncOAuth2Client] = None

    @property
    def oauth_client(self) -> AsyncOAuth2Client:
        """Get or create the OAuth2 client."""
        if self._oauth_client is None:
            self._oauth_client = AsyncOAuth2Client(
                client_id=settings.oidc_client_id,
                client_secret=settings.oidc_client_secret,
                redirect_uri=f"{settings.oidc_issuer.rstrip('/')}/protocol/openid-connect/auth",
                scope="openid email profile",
            )
        return self._oauth_client

    def generate_pkce_pair(self) -> tuple[str, str]:
        """Generate PKCE code verifier and challenge (S256 method)."""

        code_verifier = secrets.token_urlsafe(32)
        code_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        return code_verifier, code_challenge

    def get_authorization_url(
        self, redirect_uri: str, state: str, code_challenge: str
    ) -> str:
        """Generate the OIDC authorization URL."""
        return (
            f"{settings.oidc_issuer.rstrip('/')}/protocol/openid-connect/auth?"
            f"client_id={settings.oidc_client_id}&"
            f"redirect_uri={redirect_uri}&"
            f"response_type=code&"
            f"scope=openid%20email%20profile&"
            f"state={state}&"
            f"code_challenge={code_challenge}&"
            f"code_challenge_method=S256"
        )

    async def exchange_code_for_tokens(
        self, code: str, redirect_uri: str, code_verifier: str
    ) -> dict[str, Any]:
        """Exchange authorization code for tokens from the IdP."""
        token_url = f"{settings.oidc_issuer.rstrip('/')}/protocol/openid-connect/token"

        client = AsyncOAuth2Client(
            client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret,
        )

        token = await client.fetch_token(
            token_url,
            grant_type="authorization_code",
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
        )

        return dict(token)

    async def get_userinfo(self, access_token: str) -> dict[str, Any]:
        """Get user info from the IdP using the access token."""
        userinfo_url = f"{settings.oidc_issuer.rstrip('/')}/protocol/openid-connect/userinfo"

        client = AsyncOAuth2Client(
            client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret,
            token={"access_token": access_token, "token_type": "Bearer"},
        )

        response = await client.get(userinfo_url)  # type: ignore[attr-defined]
        response.raise_for_status()
        return dict(response.json())

    async def upsert_user(
        self,
        external_idp_subject: str,
        email: EmailStr,
        display_name: str,
    ) -> User:
        """Upsert user by external_idp_subject, falling back to email."""
        # Try to find by external_idp_subject first
        stmt = select(User).where(User.external_idp_subject == external_idp_subject)
        result = await self.session.execute(stmt)
        user = result.scalar_one_or_none()

        if user:
            # Update email and display_name if changed
            user.email = email
            user.display_name = display_name
            await self.session.flush()
            return user

        # Try to find by email as fallback
        stmt = select(User).where(User.email == email)
        result = await self.session.execute(stmt)
        user = result.scalar_one_or_none()

        if user:
            # Update external_idp_subject if not set
            if not user.external_idp_subject:
                user.external_idp_subject = external_idp_subject
            user.display_name = display_name
            await self.session.flush()
            return user

        # Create new user
        user = User(
            external_idp_subject=external_idp_subject,
            email=email,
            display_name=display_name,
        )
        self.session.add(user)
        await self.session.flush()
        return user

    def create_access_token(self, user: User) -> str:
        """Create a short-lived JWT access token."""
        now = datetime.now(timezone.utc)
        expire = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)

        payload = TokenPayload(
            sub=str(user.id),
            user_id=str(user.id),
            exp=int(expire.timestamp()),
            iat=int(now.timestamp()),
            type="access",
        )

        return str(
            jwt.encode(
                payload.model_dump(),
                settings.jwt_secret_key,
                algorithm=settings.jwt_algorithm,
            )
        )

    def create_refresh_token(self, user: User) -> str:
        """Create a long-lived JWT refresh token."""
        now = datetime.now(timezone.utc)
        expire = now + timedelta(days=settings.jwt_refresh_token_expire_days)

        payload = TokenPayload(
            sub=str(user.id),
            user_id=str(user.id),
            exp=int(expire.timestamp()),
            iat=int(now.timestamp()),
            type="refresh",
        )

        return str(
            jwt.encode(
                payload.model_dump(),
                settings.jwt_secret_key,
                algorithm=settings.jwt_algorithm,
            )
        )

    def decode_token(self, token: str) -> TokenPayload:
        """Decode and validate a JWT token."""
        try:
            payload = jwt.decode(
                token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm],
            )
            return TokenPayload(**payload)
        except jwt.ExpiredSignatureError as e:  # type: ignore[attr-defined]
            raise ValueError("Token has expired") from e
        except jwt.JWTError as e:  # type: ignore[attr-defined]
            raise ValueError("Invalid token") from e

    async def get_user_by_id(self, user_id: uuid.UUID) -> Optional[User]:
        """Get user by ID."""
        stmt = select(User).where(User.id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_memberships(self, user_id: uuid.UUID) -> list[tuple[Org, OrgMembership, Role]]:
        """Get all org memberships for a user with org details."""
        stmt = (
            select(Org, OrgMembership)
            .join(OrgMembership, Org.id == OrgMembership.org_id)
            .where(OrgMembership.user_id == user_id)
        )
        result = await self.session.execute(stmt)
        return [(org, membership, membership.role) for org, membership in result.all()]

    async def get_membership(
        self, user_id: uuid.UUID, org_id: uuid.UUID
    ) -> Optional[tuple[Org, OrgMembership, Role]]:
        """Get a specific org membership for a user."""
        stmt = (
            select(Org, OrgMembership)
            .join(OrgMembership, Org.id == OrgMembership.org_id)
            .where(OrgMembership.user_id == user_id, OrgMembership.org_id == org_id)
        )
        result = await self.session.execute(stmt)
        row = result.first()
        if row is None:
            return None
        org, membership = row
        return org, membership, membership.role

    async def build_me_response(self, user: User) -> MeResponse:
        """Build the /me response with user and memberships."""
        memberships_data = await self.get_user_memberships(user.id)

        memberships = [
            OrgMembershipResponse(
                org_id=org.id,
                org_name=org.name,
                role=membership.role.value,
                user_id=membership.user_id,
            )
            for org, membership, role in memberships_data
        ]

        return MeResponse(
            user=UserResponse(
                id=user.id,
                email=user.email,
                display_name=user.display_name,
                external_idp_subject=user.external_idp_subject,
                created_at=user.created_at,
            ),
            memberships=memberships,
        )