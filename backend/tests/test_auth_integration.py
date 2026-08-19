"""Integration tests for authentication and RBAC with real DB and FastAPI app."""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Org, OrgMembership, Role, User
from app.main import create_app
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