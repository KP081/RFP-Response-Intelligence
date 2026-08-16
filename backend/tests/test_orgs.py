"""Tests for organizations module - service and router."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from app.db.models import InviteStatus, Org, OrgInvite, OrgMembership, Role, User
from app.modules.orgs.dependencies import get_current_org, require_org_admin
from app.modules.orgs.schemas import InviteCreate, MemberUpdate, OrgCreate
from app.modules.orgs.service import OrgsService


class TestOrgsService:
    """Tests for OrgsService."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture
    def orgs_service(self, mock_session: AsyncMock) -> OrgsService:
        return OrgsService(mock_session)

    @pytest.fixture
    def sample_user(self) -> User:
        return User(
            id=uuid.uuid4(),
            email="test@example.com",
            display_name="Test User",
            external_idp_subject="keycloak-sub-123",
            created_at=datetime.now(timezone.utc),
        )

    @pytest.fixture
    def sample_org(self, sample_user: User) -> Org:
        return Org(
            id=uuid.uuid4(),
            name="Test Org",
            settings={},
            created_at=datetime.now(timezone.utc),
        )

    @pytest.fixture
    def sample_membership(self, sample_org: Org, sample_user: User) -> OrgMembership:
        return OrgMembership(
            id=uuid.uuid4(),
            org_id=sample_org.id,
            user_id=sample_user.id,
            role=Role.ADMIN,
            created_at=datetime.now(timezone.utc),
        )

    @pytest.mark.asyncio
    async def test_create_org_creates_membership_with_admin_role(
        self, orgs_service: OrgsService, sample_user: User, mock_session: AsyncMock
    ) -> None:
        """Test that creating an org makes the creator an admin."""
        org = await orgs_service.create_org("New Org", sample_user.id)

        assert org.name == "New Org"
        assert org.settings == {}
        assert mock_session.add.call_count == 2
        assert mock_session.flush.call_count == 2

    @pytest.mark.asyncio
    async def test_create_org_logs_audit_entry(
        self, orgs_service: OrgsService, sample_user: User, mock_session: AsyncMock
    ) -> None:
        """Test that creating an org logs an audit entry."""
        await orgs_service.create_org("New Org", sample_user.id)

        audit_calls = [call for call in mock_session.add.call_args_list
                       if call[0][0].__class__.__name__ == "AuditLogEntry"]
        assert len(audit_calls) == 1

    @pytest.mark.asyncio
    async def test_get_org_returns_org(
        self, orgs_service: OrgsService, sample_org: Org, mock_session: AsyncMock
    ) -> None:
        """Test getting an org by ID."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_org
        mock_session.execute.return_value = mock_result

        org = await orgs_service.get_org(sample_org.id)

        assert org == sample_org
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_org_not_found_returns_none(
        self, orgs_service: OrgsService, mock_session: AsyncMock
    ) -> None:
        """Test getting non-existent org returns None."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        org = await orgs_service.get_org(uuid.uuid4())

        assert org is None

    @pytest.mark.asyncio
    async def test_get_org_members_returns_members_with_roles(
        self, orgs_service: OrgsService, sample_org: Org, sample_user: User,
        sample_membership: OrgMembership, mock_session: AsyncMock
    ) -> None:
        """Test getting org members returns users with memberships."""
        mock_result = MagicMock()
        mock_result.all.return_value = [(sample_user, sample_membership)]
        mock_session.execute.return_value = mock_result

        members = await orgs_service.get_org_members(sample_org.id)

        assert len(members) == 1
        assert members[0] == (sample_user, sample_membership)

    @pytest.mark.asyncio
    async def test_create_invite_creates_pending_invite(
        self, orgs_service: OrgsService, sample_org: Org, sample_user: User, mock_session: AsyncMock
    ) -> None:
        """Test creating an invite with cryptographically random token."""
        invite = await orgs_service.create_invite(
            org_id=sample_org.id,
            email="newuser@example.com",
            role=Role.VIEWER,
            invited_by_user_id=sample_user.id,
        )

        assert invite.email == "newuser@example.com"
        assert invite.role == Role.VIEWER
        assert invite.org_id == sample_org.id
        assert invite.invited_by_user_id == sample_user.id
        assert invite.status == InviteStatus.PENDING
        assert invite.token is not None
        assert len(invite.token) > 20
        assert invite.expires_at > datetime.now(timezone.utc)

    @pytest.mark.asyncio
    async def test_create_invite_logs_audit_entry(
        self, orgs_service: OrgsService, sample_org: Org, sample_user: User, mock_session: AsyncMock
    ) -> None:
        """Test that creating an invite logs an audit entry."""
        await orgs_service.create_invite(
            org_id=sample_org.id,
            email="newuser@example.com",
            role=Role.VIEWER,
            invited_by_user_id=sample_user.id,
        )

        audit_calls = [call for call in mock_session.add.call_args_list
                       if call[0][0].__class__.__name__ == "AuditLogEntry"]
        assert len(audit_calls) == 1

    @pytest.mark.asyncio
    async def test_get_invite_by_token_returns_invite(
        self, orgs_service: OrgsService, sample_org: Org, sample_user: User, mock_session: AsyncMock
    ) -> None:
        """Test getting invite by token."""
        invite = OrgInvite(
            id=uuid.uuid4(),
            org_id=sample_org.id,
            email="newuser@example.com",
            role=Role.VIEWER,
            token="test-token-123",
            invited_by_user_id=sample_user.id,
            status=InviteStatus.PENDING,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invite
        mock_session.execute.return_value = mock_result

        result = await orgs_service.get_invite_by_token("test-token-123")

        assert result == invite

    @pytest.mark.asyncio
    async def test_accept_invite_creates_membership(
        self, orgs_service: OrgsService, sample_org: Org, sample_user: User, mock_session: AsyncMock
    ) -> None:
        """Test accepting an invite creates membership with invited role."""
        invite = OrgInvite(
            id=uuid.uuid4(),
            org_id=sample_org.id,
            email="newuser@example.com",
            role=Role.PROPOSAL_MANAGER,
            token="test-token-123",
            invited_by_user_id=sample_user.id,
            status=InviteStatus.PENDING,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.side_effect = [invite, None]
        mock_session.execute.return_value = mock_result
        mock_session.get.return_value = User(
            id=uuid.uuid4(),
            email="newuser@example.com",
            display_name="New User",
            created_at=datetime.now(timezone.utc),
        )

        org, membership, role = await orgs_service.accept_invite("test-token-123", invite.id)

        assert membership.role == Role.PROPOSAL_MANAGER
        assert membership.org_id == sample_org.id

    @pytest.mark.asyncio
    async def test_accept_invite_rejects_invalid_token(
        self, orgs_service: OrgsService, mock_session: AsyncMock
    ) -> None:
        """Test accepting invalid token raises ValueError."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Invalid invite token"):
            await orgs_service.accept_invite("invalid-token", uuid.uuid4())

    @pytest.mark.asyncio
    async def test_accept_invite_rejects_expired_token(
        self, orgs_service: OrgsService, sample_org: Org, sample_user: User, mock_session: AsyncMock
    ) -> None:
        """Test accepting expired token raises ValueError."""
        invite = OrgInvite(
            id=uuid.uuid4(),
            org_id=sample_org.id,
            email="newuser@example.com",
            role=Role.VIEWER,
            token="test-token-123",
            invited_by_user_id=sample_user.id,
            status=InviteStatus.PENDING,
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invite
        mock_session.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Invite has expired"):
            await orgs_service.accept_invite("test-token-123", uuid.uuid4())

    @pytest.mark.asyncio
    async def test_accept_invite_rejects_already_accepted(
        self, orgs_service: OrgsService, sample_org: Org, sample_user: User, mock_session: AsyncMock
    ) -> None:
        """Test accepting already accepted invite raises ValueError."""
        invite = OrgInvite(
            id=uuid.uuid4(),
            org_id=sample_org.id,
            email="newuser@example.com",
            role=Role.VIEWER,
            token="test-token-123",
            invited_by_user_id=sample_user.id,
            status=InviteStatus.ACCEPTED,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invite
        mock_session.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Invite is accepted"):
            await orgs_service.accept_invite("test-token-123", uuid.uuid4())

    @pytest.mark.asyncio
    async def test_accept_invite_rejects_existing_member(
        self, orgs_service: OrgsService, sample_org: Org, sample_user: User,
        sample_membership: OrgMembership, mock_session: AsyncMock
    ) -> None:
        """Test accepting invite for existing member raises ValueError."""
        invite = OrgInvite(
            id=uuid.uuid4(),
            org_id=sample_org.id,
            email="newuser@example.com",
            role=Role.VIEWER,
            token="test-token-123",
            invited_by_user_id=sample_user.id,
            status=InviteStatus.PENDING,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.side_effect = [invite, sample_membership]
        mock_session.execute.return_value = mock_result

        with pytest.raises(ValueError, match="already a member"):
            await orgs_service.accept_invite("test-token-123", sample_user.id)

    @pytest.mark.asyncio
    async def test_accept_invite_logs_audit_with_email_mismatch(
        self, orgs_service: OrgsService, sample_org: Org, sample_user: User, mock_session: AsyncMock
    ) -> None:
        """Test that accepting invite logs audit with email mismatch flag."""
        invite = OrgInvite(
            id=uuid.uuid4(),
            org_id=sample_org.id,
            email="different@example.com",
            role=Role.VIEWER,
            token="test-token-123",
            invited_by_user_id=sample_user.id,
            status=InviteStatus.PENDING,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.side_effect = [invite, None]
        mock_session.execute.return_value = mock_result
        accepting_user = User(
            id=uuid.uuid4(),
            email="accepting@example.com",
            display_name="Accepting User",
            created_at=datetime.now(timezone.utc),
        )
        mock_session.get.return_value = accepting_user

        await orgs_service.accept_invite("test-token-123", accepting_user.id)

        audit_calls = [call for call in mock_session.add.call_args_list
                       if call[0][0].__class__.__name__ == "AuditLogEntry"]
        assert len(audit_calls) == 1
        audit_entry = audit_calls[0][0][0]
        assert audit_entry.action == "invite_accepted"
        assert audit_entry.event_metadata["email_mismatch"] is True
        assert audit_entry.event_metadata["invite_email"] == "different@example.com"
        assert audit_entry.event_metadata["user_email"] == "accepting@example.com"

    @pytest.mark.asyncio
    async def test_accept_invite_logs_audit_without_email_mismatch(
        self, orgs_service: OrgsService, sample_org: Org, sample_user: User, mock_session: AsyncMock
    ) -> None:
        """Test that accepting invite with matching email logs audit without mismatch flag."""
        invite = OrgInvite(
            id=uuid.uuid4(),
            org_id=sample_org.id,
            email="newuser@example.com",
            role=Role.VIEWER,
            token="test-token-123",
            invited_by_user_id=sample_user.id,
            status=InviteStatus.PENDING,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.side_effect = [invite, None]
        mock_session.execute.return_value = mock_result
        accepting_user = User(
            id=uuid.uuid4(),
            email="newuser@example.com",
            display_name="New User",
            created_at=datetime.now(timezone.utc),
        )
        mock_session.get.return_value = accepting_user

        await orgs_service.accept_invite("test-token-123", accepting_user.id)

        audit_calls = [call for call in mock_session.add.call_args_list
                       if call[0][0].__class__.__name__ == "AuditLogEntry"]
        assert len(audit_calls) == 1
        audit_entry = audit_calls[0][0][0]
        assert audit_entry.event_metadata["email_mismatch"] is False

    @pytest.mark.asyncio
    async def test_update_member_role_updates_role(
        self, orgs_service: OrgsService, sample_org: Org, sample_user: User,
        sample_membership: OrgMembership, mock_session: AsyncMock
    ) -> None:
        """Test updating member role."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_membership
        mock_session.execute.return_value = mock_result

        updated = await orgs_service.update_member_role(
            sample_org.id, sample_user.id, Role.VIEWER, sample_user.id
        )

        assert updated is not None
        assert updated.role == Role.VIEWER
        assert mock_session.flush.called

    @pytest.mark.asyncio
    async def test_update_member_role_logs_audit(
        self, orgs_service: OrgsService, sample_org: Org, sample_user: User,
        sample_membership: OrgMembership, mock_session: AsyncMock
    ) -> None:
        """Test that updating member role logs audit entry."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_membership
        mock_session.execute.return_value = mock_result

        await orgs_service.update_member_role(
            sample_org.id, sample_user.id, Role.VIEWER, sample_user.id
        )

        audit_calls = [call for call in mock_session.add.call_args_list
                       if call[0][0].__class__.__name__ == "AuditLogEntry"]
        assert len(audit_calls) == 1
        audit_entry = audit_calls[0][0][0]
        assert audit_entry.action == "member_role_changed"
        assert audit_entry.event_metadata["old_role"] == "admin"
        assert audit_entry.event_metadata["new_role"] == "viewer"

    @pytest.mark.asyncio
    async def test_update_member_role_not_found_returns_none(
        self, orgs_service: OrgsService, mock_session: AsyncMock
    ) -> None:
        """Test updating non-existent member returns None."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await orgs_service.update_member_role(
            uuid.uuid4(), uuid.uuid4(), Role.VIEWER, uuid.uuid4()
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_remove_member_removes_membership(
        self, orgs_service: OrgsService, sample_org: Org, sample_user: User,
        sample_membership: OrgMembership, mock_session: AsyncMock
    ) -> None:
        """Test removing a member."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_membership
        mock_session.execute.return_value = mock_result

        result = await orgs_service.remove_member(sample_org.id, sample_user.id, sample_user.id)

        assert result is True
        mock_session.delete.assert_called_once_with(sample_membership)

    @pytest.mark.asyncio
    async def test_remove_member_logs_audit(
        self, orgs_service: OrgsService, sample_org: Org, sample_user: User,
        sample_membership: OrgMembership, mock_session: AsyncMock
    ) -> None:
        """Test that removing member logs audit entry."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_membership
        mock_session.execute.return_value = mock_result

        await orgs_service.remove_member(sample_org.id, sample_user.id, sample_user.id)

        audit_calls = [call for call in mock_session.add.call_args_list
                       if call[0][0].__class__.__name__ == "AuditLogEntry"]
        assert len(audit_calls) == 1
        audit_entry = audit_calls[0][0][0]
        assert audit_entry.action == "member_removed"
        assert audit_entry.event_metadata["removed_role"] == "admin"

    @pytest.mark.asyncio
    async def test_remove_member_not_found_returns_false(
        self, orgs_service: OrgsService, mock_session: AsyncMock
    ) -> None:
        """Test removing non-existent member returns False."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await orgs_service.remove_member(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())

        assert result is False


class TestOrgsDependencies:
    """Tests for orgs dependencies (get_current_org, require_org_admin)."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture
    def auth_service(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture
    def current_user(self) -> User:
        return User(
            id=uuid.uuid4(),
            email="test@example.com",
            display_name="Test User",
            created_at=datetime.now(timezone.utc),
        )

    @pytest.fixture
    def org_id(self) -> uuid.UUID:
        return uuid.uuid4()

    @pytest.mark.asyncio
    async def test_get_current_org_no_membership_raises_403(
        self, current_user: User, org_id: uuid.UUID,
        mock_session: AsyncMock, auth_service: AsyncMock
    ) -> None:
        """Test that missing membership raises 403."""
        auth_service.get_membership.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await get_current_org(org_id, current_user, mock_session, auth_service)

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Not a member of this organization"

    @pytest.mark.asyncio
    async def test_get_current_org_valid_membership_returns_membership(
        self, current_user: User, org_id: uuid.UUID,
        mock_session: AsyncMock, auth_service: AsyncMock
    ) -> None:
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

    @pytest.mark.asyncio
    async def test_require_org_admin_no_membership_raises_403(
        self, current_user: User, org_id: uuid.UUID,
        mock_session: AsyncMock, auth_service: AsyncMock
    ) -> None:
        """Test that missing membership raises 403."""
        auth_service.get_membership.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await require_org_admin(org_id, current_user, mock_session, auth_service)

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Not a member of this organization"

    @pytest.mark.asyncio
    async def test_require_org_admin_non_admin_raises_403(
        self, current_user: User, org_id: uuid.UUID,
        mock_session: AsyncMock, auth_service: AsyncMock
    ) -> None:
        """Test that non-admin role raises 403."""
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
            await require_org_admin(org_id, current_user, mock_session, auth_service)

        assert exc_info.value.status_code == 403
        assert "admin" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_require_org_admin_valid_admin_returns_membership(
        self, current_user: User, org_id: uuid.UUID,
        mock_session: AsyncMock, auth_service: AsyncMock
    ) -> None:
        """Test that admin role returns membership."""
        org = Org(id=org_id, name="Test Org", settings={}, created_at=datetime.now(timezone.utc))
        membership = OrgMembership(
            id=uuid.uuid4(),
            org_id=org_id,
            user_id=current_user.id,
            role=Role.ADMIN,
            created_at=datetime.now(timezone.utc),
        )
        auth_service.get_membership.return_value = (org, membership, Role.ADMIN)

        result = await require_org_admin(org_id, current_user, mock_session, auth_service)

        assert result == membership
        mock_session.execute.assert_called_once()


class TestOrgsSchemas:
    """Tests for orgs Pydantic schemas."""

    def test_org_create_schema(self) -> None:
        """Test OrgCreate schema validation."""
        org = OrgCreate(name="Test Org")
        assert org.name == "Test Org"

    def test_invite_create_schema(self) -> None:
        """Test InviteCreate schema validation."""
        invite = InviteCreate(email="test@example.com", role="viewer")
        assert invite.email == "test@example.com"
        assert invite.role == "viewer"

    def test_member_update_schema(self) -> None:
        """Test MemberUpdate schema validation."""
        update = MemberUpdate(role="admin")
        assert update.role == "admin"


class TestOrgsRouterEndpoints:
    """Tests for orgs router endpoints (structure tests)."""

    def test_create_org_endpoint_exists(self) -> None:
        """Verify create org endpoint is defined."""
        from app.modules.orgs.router import router
        routes = [r.path for r in router.routes if isinstance(r, APIRoute)]
        assert "/orgs" in routes

    def test_get_org_endpoint_exists(self) -> None:
        """Verify get org endpoint is defined."""
        from app.modules.orgs.router import router
        routes = [r.path for r in router.routes if isinstance(r, APIRoute)]
        assert "/orgs/{org_id}" in routes

    def test_list_members_endpoint_exists(self) -> None:
        """Verify list members endpoint is defined."""
        from app.modules.orgs.router import router
        routes = [r.path for r in router.routes if isinstance(r, APIRoute)]
        assert "/orgs/{org_id}/members" in routes

    def test_create_invite_endpoint_exists(self) -> None:
        """Verify create invite endpoint is defined."""
        from app.modules.orgs.router import router
        routes = [r.path for r in router.routes if isinstance(r, APIRoute)]
        assert "/orgs/{org_id}/invites" in routes

    def test_accept_invite_endpoint_exists(self) -> None:
        """Verify accept invite endpoint is defined."""
        from app.modules.orgs.router import router
        routes = [r.path for r in router.routes if isinstance(r, APIRoute)]
        assert "/orgs/invites/{token}/accept" in routes

    def test_update_member_endpoint_exists(self) -> None:
        """Verify update member endpoint is defined."""
        from app.modules.orgs.router import router
        routes = [r.path for r in router.routes if isinstance(r, APIRoute)]
        assert "/orgs/{org_id}/members/{user_id}" in routes

    def test_remove_member_endpoint_exists(self) -> None:
        """Verify remove member endpoint is defined."""
        from app.modules.orgs.router import router
        routes = [r.path for r in router.routes if isinstance(r, APIRoute)]
        assert "/orgs/{org_id}/members/{user_id}" in routes