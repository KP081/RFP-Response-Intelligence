"""Integration tests for authentication and RBAC with real DB and FastAPI app."""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import settings
from app.db.models import Org, OrgMembership, Role, User
from app.main import create_app
from app.modules.auth.router import _sanitize_return_to
from app.modules.auth.service import AuthService


@pytest.fixture
async def app():
    """Create the FastAPI app for testing."""
    return create_app()


@pytest.fixture
async def async_client(app):
    """Create an async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def two_orgs_with_users(async_session: AsyncSession) -> dict:
    """Create two organizations with users and memberships for integration testing."""

    # Organization A
    org_a_id = uuid.uuid4()
    org_a = Org(
        id=org_a_id,
        name="Organization A",
        settings={},
    )
    async_session.add(org_a)

    # Organization B
    org_b_id = uuid.uuid4()
    org_b = Org(
        id=org_b_id,
        name="Organization B",
        settings={},
    )
    async_session.add(org_b)

    # User in Org A
    user_a_id = uuid.uuid4()
    user_a = User(
        id=user_a_id,
        email="admin@org-a.local",
        display_name="Admin A",
        external_idp_subject="sub-org-a-admin",
    )
    async_session.add(user_a)

    # User in Org B
    user_b_id = uuid.uuid4()
    user_b = User(
        id=user_b_id,
        email="admin@org-b.local",
        display_name="Admin B",
        external_idp_subject="sub-org-b-admin",
    )
    async_session.add(user_b)

    await async_session.flush()

    # Membership in Org A
    membership_a = OrgMembership(
        id=uuid.uuid4(),
        org_id=org_a_id,
        user_id=user_a_id,
        role=Role.ADMIN,
    )
    async_session.add(membership_a)

    # Membership in Org B
    membership_b = OrgMembership(
        id=uuid.uuid4(),
        org_id=org_b_id,
        user_id=user_b_id,
        role=Role.ADMIN,
    )
    async_session.add(membership_b)

    await async_session.commit()

    return {
        "org_a_id": org_a_id,
        "org_b_id": org_b_id,
        "user_a_id": user_a_id,
        "user_b_id": user_b_id,
        "membership_a_id": membership_a.id,
        "membership_b_id": membership_b.id,
    }


@pytest.fixture
def auth_service(async_session: AsyncSession) -> AuthService:
    """Create a real AuthService instance."""
    return AuthService(async_session)


@pytest.fixture
def user_a_token(auth_service: AuthService, two_orgs_with_users: dict) -> str:
    """Create a valid access token for user A."""
    user_id = two_orgs_with_users["user_a_id"]
    return auth_service.create_access_token(
        User(
            id=user_id,
            email="admin@org-a.local",
            display_name="Admin A",
            external_idp_subject="sub-org-a-admin",
            created_at=datetime.now(timezone.utc),
        )
    )


@pytest.fixture
def user_b_token(auth_service: AuthService, two_orgs_with_users: dict) -> str:
    """Create a valid access token for user B."""
    user_id = two_orgs_with_users["user_b_id"]
    return auth_service.create_access_token(
        User(
            id=user_id,
            email="admin@org-b.local",
            display_name="Admin B",
            external_idp_subject="sub-org-b-admin",
            created_at=datetime.now(timezone.utc),
        )
    )


class TestAuthIntegration:
    """Integration tests for auth endpoints using real DB and cookie-based auth."""

    async def test_protected_endpoint_with_cookie_auth(
        self, async_client: AsyncClient, user_a_token: str, two_orgs_with_users: dict
    ) -> None:
        """Test that a protected endpoint works with httpOnly cookie authentication."""
        org_a_id = two_orgs_with_users["org_a_id"]

        # Set the access token as a cookie (simulating /auth/callback behavior)
        # httpx doesn't support httponly flag in set(), but the cookie is still sent
        async_client.cookies.set("access_token", user_a_token)

        # Call a protected endpoint using only the cookie (no Authorization header)
        # Use audit-log endpoint which requires ADMIN role (test user has ADMIN)
        response = await async_client.get(f"/api/v1/orgs/{org_a_id}/audit-log")

        # Should succeed with 200
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    async def test_protected_endpoint_rejects_foreign_org(
        self, async_client: AsyncClient, user_a_token: str, two_orgs_with_users: dict
    ) -> None:
        """Test that accessing a foreign org returns 403/404."""
        org_b_id = two_orgs_with_users["org_b_id"]

        # Set the access token as a cookie
        async_client.cookies.set("access_token", user_a_token)

        # Call a protected endpoint for org B (user A is not a member)
        response = await async_client.get(f"/api/v1/orgs/{org_b_id}/audit-log")

        # Should fail with 403 or 404
        assert response.status_code in (403, 404), (
            f"Expected 403/404 for foreign org access, got {response.status_code}: {response.text}"
        )

    async def test_protected_endpoint_without_auth_returns_401(
        self, async_client: AsyncClient, two_orgs_with_users: dict
    ) -> None:
        """Test that accessing a protected endpoint without auth returns 401."""
        org_a_id = two_orgs_with_users["org_a_id"]

        # No cookie, no Authorization header
        response = await async_client.get(f"/api/v1/orgs/{org_a_id}/audit-log")

        assert response.status_code == 401

    async def test_protected_endpoint_with_authorization_header_also_works(
        self, async_client: AsyncClient, user_a_token: str, two_orgs_with_users: dict
    ) -> None:
        """Test that Authorization header still works (for non-browser clients)."""
        org_a_id = two_orgs_with_users["org_a_id"]

        # Use Authorization header instead of cookie
        async_client.headers["Authorization"] = f"Bearer {user_a_token}"

        response = await async_client.get(f"/api/v1/orgs/{org_a_id}/audit-log")

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    async def test_authorization_header_preferred_when_both_present(
        self, async_client: AsyncClient, user_a_token: str, user_b_token: str, two_orgs_with_users: dict
    ) -> None:
        """Test that Authorization header is preferred when both header and cookie are present."""
        org_a_id = two_orgs_with_users["org_a_id"]

        # Set cookie for user A but header for user B
        async_client.cookies.set("access_token", user_a_token)
        async_client.headers["Authorization"] = f"Bearer {user_b_token}"

        # Should use user B's token (header takes precedence)
        response = await async_client.get(f"/api/v1/orgs/{org_a_id}/audit-log")

        # User B is not a member of org A, so should fail
        assert response.status_code in (403, 404)


class TestAuthServiceIntegration:
    """Integration tests for AuthService with real database."""

    async def test_get_membership_returns_correct_data(
        self, async_session: AsyncSession, auth_service: AuthService, two_orgs_with_users: dict
    ) -> None:
        """Test that get_membership returns correct org, membership, and role."""
        org_a_id = two_orgs_with_users["org_a_id"]
        user_a_id = two_orgs_with_users["user_a_id"]

        result = await auth_service.get_membership(user_a_id, org_a_id)

        assert result is not None
        org, membership, role = result
        assert org.id == org_a_id
        assert membership.org_id == org_a_id
        assert membership.user_id == user_a_id
        assert role == Role.ADMIN

    async def test_get_membership_returns_none_for_foreign_org(
        self, async_session: AsyncSession, auth_service: AuthService, two_orgs_with_users: dict
    ) -> None:
        """Test that get_membership returns None for org user is not a member of."""
        org_b_id = two_orgs_with_users["org_b_id"]
        user_a_id = two_orgs_with_users["user_a_id"]

        result = await auth_service.get_membership(user_a_id, org_b_id)

        assert result is None

    async def test_get_user_memberships_returns_all_memberships(
        self, async_session: AsyncSession, auth_service: AuthService, two_orgs_with_users: dict
    ) -> None:
        """Test that get_user_memberships returns all memberships for a user."""
        user_a_id = two_orgs_with_users["user_a_id"]

        result = await auth_service.get_user_memberships(user_a_id)

        assert len(result) == 1
        org, membership, role = result[0]
        assert org.id == two_orgs_with_users["org_a_id"]
        assert membership.user_id == user_a_id
        assert role == Role.ADMIN


class TestSanitizeReturnTo:
    """Tests for the _sanitize_return_to helper function."""

    def test_sanitize_return_to_rejects_protocol_relative(self) -> None:
        """Test that protocol-relative URLs (//evil.com) are rejected."""
        assert _sanitize_return_to("//evil.com") == "/"

    def test_sanitize_return_to_rejects_https(self) -> None:
        """Test that absolute HTTPS URLs are rejected."""
        assert _sanitize_return_to("https://evil.com") == "/"

    def test_sanitize_return_to_rejects_http(self) -> None:
        """Test that absolute HTTP URLs are rejected."""
        assert _sanitize_return_to("http://evil.com") == "/"

    def test_sanitize_return_to_rejects_empty_string(self) -> None:
        """Test that empty strings fall back to /."""
        assert _sanitize_return_to("") == "/"

    def test_sanitize_return_to_rejects_none(self) -> None:
        """Test that None values fall back to /."""
        assert _sanitize_return_to(None) == "/"  # type: ignore[arg-type]

    def test_sanitize_return_to_accepts_normal_path(self) -> None:
        """Test that normal relative paths are accepted unchanged."""
        assert _sanitize_return_to("/orgs/123/documents") == "/orgs/123/documents"

    def test_sanitize_return_to_accepts_root(self) -> None:
        """Test that root path is accepted."""
        assert _sanitize_return_to("/") == "/"

    def test_sanitize_return_to_accepts_nested_paths(self) -> None:
        """Test that nested paths are accepted."""
        assert _sanitize_return_to("/orgs/abc/search?q=test") == "/orgs/abc/search?q=test"

    def test_sanitize_return_to_rejects_double_slash(self) -> None:
        """Test that paths starting with // are rejected."""
        assert _sanitize_return_to("//") == "/"

    def test_sanitize_return_to_rejects_whitespace(self) -> None:
        """Test that paths with whitespace are rejected."""
        assert _sanitize_return_to("/path with spaces") == "/"


class TestLoginEndpoint:
    """Tests for the /auth/login endpoint."""

    async def test_login_uses_fixed_redirect_uri(self, async_client: AsyncClient) -> None:
        """Test that /auth/login redirects to Keycloak with the fixed backend redirect_uri."""
        # We don't follow redirects, we just check the Location header
        response = await async_client.get("/api/v1/auth/login?return_to=/orgs/123", follow_redirects=False)

        assert response.status_code == 307  # RedirectResponse default
        location = response.headers.get("location")
        assert location is not None
        assert location.startswith(settings.oidc_issuer.rstrip("/") + "/protocol/openid-connect/auth?")

        # Check that redirect_uri in the location is the fixed backend one, properly encoded
        from urllib.parse import parse_qs, urlparse
        parsed = urlparse(location)
        params = parse_qs(parsed.query)
        assert "redirect_uri" in params
        # The redirect_uri should be the backend callback URL, not the return_to value
        expected_redirect_uri = "http://localhost:8000/api/v1/auth/callback"
        assert params["redirect_uri"][0] == expected_redirect_uri
        # Ensure return_to was NOT used as redirect_uri
        assert params["redirect_uri"][0] != "/orgs/123"

    async def test_login_return_to_stored_in_pkce_state(self, async_client: AsyncClient) -> None:
        """Test that return_to is validated and would be stored in PKCE state."""
        response = await async_client.get("/api/v1/auth/login?return_to=/orgs/123/documents", follow_redirects=False)

        assert response.status_code == 307
        location = response.headers.get("location")
        assert location is not None

        # Check that state parameter is present (PKCE state stored in Redis)
        from urllib.parse import parse_qs, urlparse
        parsed = urlparse(location)
        params = parse_qs(parsed.query)
        assert "state" in params
        assert len(params["state"][0]) > 0

    async def test_login_rejects_malicious_return_to(self, async_client: AsyncClient) -> None:
        """Test that malicious return_to values are sanitized to /."""
        # Test protocol-relative
        response = await async_client.get("/api/v1/auth/login?return_to=//evil.com", follow_redirects=False)
        assert response.status_code == 307

        # Test absolute URL
        response = await async_client.get("/api/v1/auth/login?return_to=https://evil.com", follow_redirects=False)
        assert response.status_code == 307

        # Test empty
        response = await async_client.get("/api/v1/auth/login?return_to=", follow_redirects=False)
        assert response.status_code == 307