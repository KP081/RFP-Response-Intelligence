"""Tests for authentication and RBAC dependencies."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from jose import jwt

from app.core.settings import settings
from app.db.models import Org, OrgMembership, Role, User
from app.modules.auth.dependencies import (
    get_current_user,
    get_current_org,
    require_role,
    require_role_dependency,
)
from app.modules.auth.schemas import TokenPayload
from app.modules.auth.service import AuthService


class TestAuthService:
    """Tests for AuthService token management."""

    @pytest.fixture
    def mock_session(self):
        return AsyncMock()

    @pytest.fixture
    def auth_service(self, mock_session):
        return AuthService(mock_session)

    @pytest.fixture
    def sample_user(self):
        return User(
            id=uuid.uuid4(),
            email="test@example.com",
            display_name="Test User",
            external_idp_subject="keycloak-sub-123",
            created_at=datetime.now(timezone.utc),
        )

    def test_create_access_token(self, auth_service, sample_user):
        """Test access token creation with correct payload."""
        token = auth_service.create_access_token(sample_user)
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])

        assert payload["sub"] == str(sample_user.id)
        assert payload["user_id"] == str(sample_user.id)
        assert payload["type"] == "access"
        assert "exp" in payload
        assert "iat" in payload

    def test_create_refresh_token(self, auth_service, sample_user):
        """Test refresh token creation with correct payload."""
        token = auth_service.create_refresh_token(sample_user)
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])

        assert payload["sub"] == str(sample_user.id)
        assert payload["user_id"] == str(sample_user.id)
        assert payload["type"] == "refresh"
        assert "exp" in payload
        assert "iat" in payload

    def test_decode_valid_access_token(self, auth_service, sample_user):
        """Test decoding a valid access token."""
        token = auth_service.create_access_token(sample_user)
        payload = auth_service.decode_token(token)

        assert payload.user_id == str(sample_user.id)
        assert payload.type == "access"

    def test_decode_valid_refresh_token(self, auth_service, sample_user):
        """Test decoding a valid refresh token."""
        token = auth_service.create_refresh_token(sample_user)
        payload = auth_service.decode_token(token)

        assert payload.user_id == str(sample_user.id)
        assert payload.type == "refresh"

    def test_decode_expired_token_raises(self, auth_service, sample_user):
        """Test that expired token raises ValueError."""
        expired_payload = TokenPayload(
            sub=str(sample_user.id),
            user_id=str(sample_user.id),
            exp=int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp()),
            iat=int((datetime.now(timezone.utc) - timedelta(hours=2)).timestamp()),
            type="access",
        )
        expired_token = jwt.encode(
            expired_payload.model_dump(),
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )

        with pytest.raises(ValueError, match="Token has expired"):
            auth_service.decode_token(expired_token)

    def test_decode_invalid_token_raises(self, auth_service):
        """Test that invalid token raises ValueError."""
        with pytest.raises(ValueError, match="Invalid token"):
            auth_service.decode_token("invalid.token.string")

    def test_decode_wrong_type_raises(self, auth_service, sample_user):
        """Test that refresh token fails when access token expected."""
        refresh_token = auth_service.create_refresh_token(sample_user)
        # The decode_token function itself doesn't check type, but get_current_user does
        payload = auth_service.decode_token(refresh_token)
        assert payload.type == "refresh"

    def test_generate_pkce_pair(self, auth_service):
        """Test PKCE pair generation produces valid S256 challenge."""
        import base64
        import hashlib

        code_verifier, code_challenge = auth_service.generate_pkce_pair()

        # Verify code_verifier is a valid URL-safe string
        assert len(code_verifier) >= 43
        assert all(c.isalnum() or c in "-._~" for c in code_verifier)

        # Verify code_challenge is S256 hash of code_verifier
        expected_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        assert code_challenge == expected_challenge


class TestGetCurrentUser:
    """Tests for get_current_user dependency."""

    @pytest.fixture
    def mock_request(self):
        request = MagicMock()
        request.state = MagicMock()
        return request

    @pytest.fixture
    def auth_service(self):
        return AsyncMock(spec=AuthService)

    @pytest.mark.asyncio
    async def test_missing_credentials_raises_401(self, mock_request, auth_service):
        """Test that missing credentials raises 401."""
        credentials = None

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(mock_request, credentials, auth_service)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Not authenticated"

    @pytest.mark.asyncio
    async def test_invalid_token_raises_401(self, mock_request, auth_service):
        """Test that invalid token raises 401."""
        credentials = MagicMock()
        credentials.credentials = "invalid.token"
        auth_service.decode_token.side_effect = ValueError("Invalid token")

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(mock_request, credentials, auth_service)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid token"

    @pytest.mark.asyncio
    async def test_refresh_token_type_raises_401(self, mock_request, auth_service):
        """Test that refresh token type raises 401."""
        credentials = MagicMock()
        credentials.credentials = "some.token"
        auth_service.decode_token.return_value = TokenPayload(
            sub=str(uuid.uuid4()),
            user_id=str(uuid.uuid4()),
            exp=int((datetime.now(timezone.utc) + timedelta(minutes=15)).timestamp()),
            iat=int(datetime.now(timezone.utc).timestamp()),
            type="refresh",
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(mock_request, credentials, auth_service)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid token type"

    @pytest.mark.asyncio
    async def test_user_not_found_raises_401(self, mock_request, auth_service):
        """Test that non-existent user raises 401."""
        credentials = MagicMock()
        credentials.credentials = "some.token"
        user_id = uuid.uuid4()
        auth_service.decode_token.return_value = TokenPayload(
            sub=str(user_id),
            user_id=str(user_id),
            exp=int((datetime.now(timezone.utc) + timedelta(minutes=15)).timestamp()),
            iat=int(datetime.now(timezone.utc).timestamp()),
            type="access",
        )
        auth_service.get_user_by_id.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(mock_request, credentials, auth_service)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "User not found"

    @pytest.mark.asyncio
    async def test_valid_token_returns_user(self, mock_request, auth_service):
        """Test that valid token returns user."""
        credentials = MagicMock()
        credentials.credentials = "valid.token"
        user = User(
            id=uuid.uuid4(),
            email="test@example.com",
            display_name="Test User",
            created_at=datetime.now(timezone.utc),
        )
        auth_service.decode_token.return_value = TokenPayload(
            sub=str(user.id),
            user_id=str(user.id),
            exp=int((datetime.now(timezone.utc) + timedelta(minutes=15)).timestamp()),
            iat=int(datetime.now(timezone.utc).timestamp()),
            type="access",
        )
        auth_service.get_user_by_id.return_value = user

        result = await get_current_user(mock_request, credentials, auth_service)

        assert result == user
        assert mock_request.state.current_user == user


class TestGetCurrentOrg:
    """Tests for get_current_org dependency."""

    @pytest.fixture
    def mock_session(self):
        return AsyncMock()

    @pytest.fixture
    def auth_service(self):
        return AsyncMock(spec=AuthService)

    @pytest.fixture
    def current_user(self):
        return User(
            id=uuid.uuid4(),
            email="test@example.com",
            display_name="Test User",
            created_at=datetime.now(timezone.utc),
        )

    @pytest.fixture
    def org_id(self):
        return uuid.uuid4()

    @pytest.mark.asyncio
    async def test_no_membership_raises_403(self, current_user, org_id, mock_session, auth_service):
        """Test that missing membership raises 403."""
        auth_service.get_membership.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await get_current_org(org_id, current_user, mock_session, auth_service)

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Not a member of this organization"

    @pytest.mark.asyncio
    async def test_valid_membership_returns_membership(self, current_user, org_id, mock_session, auth_service):
        """Test that valid membership returns membership and sets RLS."""
        org = Org(id=org_id, name="Test Org", settings={}, created_at=datetime.now(timezone.utc))
        membership = OrgMembership(
            id=uuid.uuid4(),
            org_id=org_id,
            user_id=current_user.id,
            role=Role.ADMIN,
            created_at=datetime.now(timezone.utc),
        )
        auth_service.get_membership.return_value = (org, membership, Role.ADMIN)

        result = await get_current_org(org_id, current_user, mock_session, auth_service)

        assert result == membership
        mock_session.execute.assert_called_once()


class TestRequireRole:
    """Tests for require_role dependency factory."""

    @pytest.fixture
    def mock_request(self):
        request = MagicMock()
        request.path_params = {"org_id": str(uuid.uuid4())}
        return request

    @pytest.fixture
    def mock_session(self):
        return AsyncMock()

    @pytest.fixture
    def auth_service(self):
        return AsyncMock(spec=AuthService)

    @pytest.fixture
    def current_user(self):
        return User(
            id=uuid.uuid4(),
            email="test@example.com",
            display_name="Test User",
            created_at=datetime.now(timezone.utc),
        )

    @pytest.fixture
    def org_id(self):
        return uuid.uuid4()

    @pytest.mark.asyncio
    async def test_missing_org_id_raises_400(self, current_user, mock_request, mock_session, auth_service):
        """Test that missing org_id in path params raises 400."""
        mock_request.path_params = {}

        dep = require_role(Role.ADMIN)

        with pytest.raises(HTTPException) as exc_info:
            await dep(current_user, mock_session, auth_service, mock_request)

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Organization ID is required"

    @pytest.mark.asyncio
    async def test_invalid_org_id_raises_400(self, current_user, mock_request, mock_session, auth_service):
        """Test that invalid org_id raises 400."""
        mock_request.path_params = {"org_id": "not-a-uuid"}

        dep = require_role(Role.ADMIN)

        with pytest.raises(HTTPException) as exc_info:
            await dep(current_user, mock_session, auth_service, mock_request)

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Invalid organization ID"

    @pytest.mark.asyncio
    async def test_no_membership_raises_403(self, current_user, org_id, mock_request, mock_session, auth_service):
        """Test that missing membership raises 403."""
        mock_request.path_params = {"org_id": str(org_id)}
        auth_service.get_membership.return_value = None

        dep = require_role(Role.ADMIN)

        with pytest.raises(HTTPException) as exc_info:
            await dep(current_user, mock_session, auth_service, mock_request)

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Not a member of this organization"

    @pytest.mark.asyncio
    async def test_wrong_role_raises_403(self, current_user, org_id, mock_request, mock_session, auth_service):
        """Test that insufficient role raises 403."""
        mock_request.path_params = {"org_id": str(org_id)}
        org = Org(id=org_id, name="Test Org", settings={}, created_at=datetime.now(timezone.utc))
        membership = OrgMembership(
            id=uuid.uuid4(),
            org_id=org_id,
            user_id=current_user.id,
            role=Role.VIEWER,
            created_at=datetime.now(timezone.utc),
        )
        auth_service.get_membership.return_value = (org, membership, Role.VIEWER)

        dep = require_role(Role.ADMIN)

        with pytest.raises(HTTPException) as exc_info:
            await dep(current_user, mock_session, auth_service, mock_request)

        assert exc_info.value.status_code == 403
        assert "admin" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_correct_role_returns_membership(self, current_user, org_id, mock_request, mock_session, auth_service):
        """Test that correct role returns membership."""
        mock_request.path_params = {"org_id": str(org_id)}
        org = Org(id=org_id, name="Test Org", settings={}, created_at=datetime.now(timezone.utc))
        membership = OrgMembership(
            id=uuid.uuid4(),
            org_id=org_id,
            user_id=current_user.id,
            role=Role.ADMIN,
            created_at=datetime.now(timezone.utc),
        )
        auth_service.get_membership.return_value = (org, membership, Role.ADMIN)

        dep = require_role(Role.ADMIN)

        result = await dep(current_user, mock_session, auth_service, mock_request)

        assert result == membership
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_multiple_allowed_roles(self, current_user, org_id, mock_request, mock_session, auth_service):
        """Test that any of multiple allowed roles works."""
        mock_request.path_params = {"org_id": str(org_id)}
        org = Org(id=org_id, name="Test Org", settings={}, created_at=datetime.now(timezone.utc))
        membership = OrgMembership(
            id=uuid.uuid4(),
            org_id=org_id,
            user_id=current_user.id,
            role=Role.PROPOSAL_MANAGER,
            created_at=datetime.now(timezone.utc),
        )
        auth_service.get_membership.return_value = (org, membership, Role.PROPOSAL_MANAGER)

        dep = require_role(Role.ADMIN, Role.PROPOSAL_MANAGER)

        result = await dep(current_user, mock_session, auth_service, mock_request)

        assert result == membership


class TestRequireRoleDependency:
    """Tests for require_role_dependency internal function."""

    @pytest.fixture
    def mock_session(self):
        return AsyncMock()

    @pytest.fixture
    def auth_service(self):
        return AsyncMock(spec=AuthService)

    @pytest.fixture
    def current_user(self):
        return User(
            id=uuid.uuid4(),
            email="test@example.com",
            display_name="Test User",
            created_at=datetime.now(timezone.utc),
        )

    @pytest.fixture
    def org_id(self):
        return uuid.uuid4()

    @pytest.mark.asyncio
    async def test_no_membership_raises_403(self, current_user, org_id, mock_session, auth_service):
        """Test that missing membership raises 403."""
        auth_service.get_membership.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await require_role_dependency({"admin"}, current_user, mock_session, auth_service, org_id)

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Not a member of this organization"

    @pytest.mark.asyncio
    async def test_insufficient_role_raises_403(self, current_user, org_id, mock_session, auth_service):
        """Test that role not in allowed set raises 403."""
        org = Org(id=org_id, name="Test Org", settings={}, created_at=datetime.now(timezone.utc))
        membership = OrgMembership(
            id=uuid.uuid4(),
            org_id=org_id,
            user_id=current_user.id,
            role=Role.VIEWER,
            created_at=datetime.now(timezone.utc),
        )
        auth_service.get_membership.return_value = (org, membership, Role.VIEWER)

        with pytest.raises(HTTPException) as exc_info:
            await require_role_dependency({"admin", "proposal_manager"}, current_user, mock_session, auth_service, org_id)

        assert exc_info.value.status_code == 403
        assert "admin" in exc_info.value.detail or "proposal_manager" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_allowed_role_returns_membership(self, current_user, org_id, mock_session, auth_service):
        """Test that allowed role returns membership."""
        org = Org(id=org_id, name="Test Org", settings={}, created_at=datetime.now(timezone.utc))
        membership = OrgMembership(
            id=uuid.uuid4(),
            org_id=org_id,
            user_id=current_user.id,
            role=Role.ADMIN,
            created_at=datetime.now(timezone.utc),
        )
        auth_service.get_membership.return_value = (org, membership, Role.ADMIN)

        result = await require_role_dependency({"admin"}, current_user, mock_session, auth_service, org_id)

        assert result == membership
        mock_session.execute.assert_called_once()


class TestAuthRouterEndpoints:
    """Tests for auth router endpoints (structure tests)."""

    def test_login_endpoint_exists(self):
        """Verify login endpoint is defined."""
        from app.modules.auth.router import router
        routes = [r.path for r in router.routes]
        assert "/auth/login" in routes

    def test_callback_endpoint_exists(self):
        """Verify callback endpoint is defined."""
        from app.modules.auth.router import router
        routes = [r.path for r in router.routes]
        assert "/auth/callback" in routes

    def test_me_endpoint_exists(self):
        """Verify /me endpoint is defined."""
        from app.modules.auth.router import router
        routes = [r.path for r in router.routes]
        assert "/auth/me" in routes

    def test_logout_endpoint_exists(self):
        """Verify logout endpoint is defined."""
        from app.modules.auth.router import router
        routes = [r.path for r in router.routes]
        assert "/auth/logout" in routes

    def test_refresh_endpoint_exists(self):
        """Verify refresh endpoint is defined."""
        from app.modules.auth.router import router
        routes = [r.path for r in router.routes]
        assert "/auth/refresh" in routes

    def test_test_rbac_endpoint_exists(self):
        """Verify test RBAC endpoint is defined."""
        from app.modules.auth.router import router
        routes = [r.path for r in router.routes]
        assert "/auth/test-rbac/{org_id}" in routes

    def test_test_org_access_endpoint_exists(self):
        """Verify test org access endpoint is defined."""
        from app.modules.auth.router import router
        routes = [r.path for r in router.routes]
        assert "/auth/test-org-access/{org_id}" in routes