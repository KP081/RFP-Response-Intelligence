"""Service for organization operations."""

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from pydantic import EmailStr
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit_event
from app.db.models import InviteStatus, Org, OrgInvite, OrgMembership, Role, User
from app.db.session import get_migrations_session


class OrgsService:
    """Service for handling organization operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _log_audit(
        self,
        org_id: uuid.UUID,
        actor_user_id: Optional[uuid.UUID],
        action: str,
        resource_type: str,
        resource_id: str,
        metadata: dict[str, object],
    ) -> None:
        """Write an audit log entry via centralized audit function."""
        await record_audit_event(
            session=self.session,
            org_id=org_id,
            actor_user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata=metadata,
        )

    async def create_org(self, name: str, user_id: uuid.UUID) -> Org:
        """Create a new organization and make the creator an admin."""
        org = Org(name=name, settings={})
        self.session.add(org)
        await self.session.flush()

        # The org didn't exist until the line above, so no RLS context could have been set for it
        # yet. Establish it now, for the rest of this transaction, before inserting anything into
        # RLS-scoped tables (org_memberships, audit_log) that reference this org_id — the caller is
        # legitimately entitled to this context, since they are this org's own creator.
        await self.session.execute(
            text("SELECT set_config('app.current_org_id', :org_id, true)"),
            {"org_id": str(org.id)},
        )

        membership = OrgMembership(
            org_id=org.id,
            user_id=user_id,
            role=Role.ADMIN,
        )
        self.session.add(membership)
        await self.session.flush()

        await self._log_audit(
            org_id=org.id,
            actor_user_id=user_id,
            action="org_created",
            resource_type="org",
            resource_id=str(org.id),
            metadata={"creator_user_id": str(user_id)},
        )

        return org

    async def get_org(self, org_id: uuid.UUID) -> Optional[Org]:
        """Get organization by ID."""
        stmt = select(Org).where(Org.id == org_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_org_members(self, org_id: uuid.UUID) -> list[tuple[User, OrgMembership]]:
        """Get all members of an organization with their roles."""
        stmt = (
            select(User, OrgMembership)
            .join(OrgMembership, User.id == OrgMembership.user_id)
            .where(OrgMembership.org_id == org_id)
            .order_by(OrgMembership.created_at)
        )
        result = await self.session.execute(stmt)
        return [tuple(row) for row in result.all()]

    async def create_invite(
        self,
        org_id: uuid.UUID,
        email: EmailStr,
        role: Role,
        invited_by_user_id: uuid.UUID,
    ) -> OrgInvite:
        """Create a new organization invite."""
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)

        invite = OrgInvite(
            org_id=org_id,
            email=email,
            role=role,
            token=token,
            invited_by_user_id=invited_by_user_id,
            status=InviteStatus.PENDING,
            expires_at=expires_at,
        )
        self.session.add(invite)
        await self.session.flush()

        await self._log_audit(
            org_id=org_id,
            actor_user_id=invited_by_user_id,
            action="invite_created",
            resource_type="org_invite",
            resource_id=str(invite.id),
            metadata={
                "email": email,
                "role": role.value,
                "invited_by": str(invited_by_user_id),
            },
        )

        return invite

    async def get_invite_by_token(self, token: str) -> Optional[OrgInvite]:
        """Get invite by token (RLS-scoped — caller must already have org context)."""
        stmt = select(OrgInvite).where(OrgInvite.token == token)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_invite_by_token_unscoped(self, token: str) -> Optional[OrgInvite]:
        """Look up an invite by its token, bypassing per-org RLS context.

        This is intentionally unscoped: the caller does not yet belong to the invite's org (that's
        the entire point of accepting an invite), so there is no RLS context to set before this
        lookup. The random, unguessable token itself is the authorization for this one read — this
        mirrors how a password-reset token grants access by possession, not by pre-existing
        membership. Only used to resolve which org_id to establish context for; all subsequent
        reads/writes in accept_invite() go through the normal, RLS-scoped path once that's known.
        """
        async with get_migrations_session() as bypass_session:
            stmt = select(OrgInvite).where(OrgInvite.token == token)
            result = await bypass_session.execute(stmt)
            return result.scalar_one_or_none()


    async def accept_invite(self, token: str, user_id: uuid.UUID) -> tuple[Org, OrgMembership, Role]:
        """Accept an invite and create membership for the user."""
        invite = await self.get_invite_by_token_unscoped(token)
        if not invite:
            raise ValueError("Invalid invite token")

        if invite.status != InviteStatus.PENDING:
            raise ValueError(f"Invite is {invite.status.value}")

        if invite.expires_at < datetime.now(timezone.utc):
            raise ValueError("Invite has expired")

        # Now that we know the target org, establish RLS context on the *main* session for the
        # remainder of this transaction, before any further reads/writes against RLS-scoped tables.
        await self.session.execute(
            text("SELECT set_config('app.current_org_id', :org_id, true)"),
            {"org_id": str(invite.org_id)},
        )

        # Check if user is already a member — now correctly scoped.
        stmt = select(OrgMembership).where(
            OrgMembership.org_id == invite.org_id,
            OrgMembership.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            raise ValueError("User is already a member of this organization")

        # Create membership
        membership = OrgMembership(
            org_id=invite.org_id,
            user_id=user_id,
            role=invite.role,
        )
        self.session.add(membership)

        # Re-fetch the invite through the now-scoped main session (not the bypass session) before
        # updating its status, so the update itself goes through the normal RLS-scoped path.
        invite_stmt = select(OrgInvite).where(OrgInvite.id == invite.id)
        invite_result = await self.session.execute(invite_stmt)
        scoped_invite: OrgInvite = invite_result.scalar_one()
        scoped_invite.status = InviteStatus.ACCEPTED

        # Get the accepting user to check email mismatch
        user = await self.session.get(User, user_id)
        email_mismatch = False
        if user:
            email_mismatch = user.email.lower() != invite.email.lower()

        # Log invite acceptance with email mismatch flag
        await self._log_audit(
            org_id=invite.org_id,
            actor_user_id=user_id,
            action="invite_accepted",
            resource_type="org_invite",
            resource_id=str(invite.id),
            metadata={
                "email_mismatch": email_mismatch,
                "invite_email": invite.email,
                "user_email": user.email if user else None,
                "invited_role": invite.role.value,
            },
        )

        await self.session.flush()

        # Get org for response using org_id from invite (since invite from migrations session is detached)
        org_stmt = select(Org).where(Org.id == invite.org_id)
        org_result = await self.session.execute(org_stmt)
        org = org_result.scalar_one()

        return org, membership, invite.role

    async def update_member_role(
        self, org_id: uuid.UUID, user_id: uuid.UUID, new_role: Role, actor_user_id: uuid.UUID
    ) -> Optional[OrgMembership]:
        """Update a member's role."""
        stmt = select(OrgMembership).where(
            OrgMembership.org_id == org_id,
            OrgMembership.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        membership = result.scalar_one_or_none()

        if not membership:
            return None

        old_role = membership.role
        membership.role = new_role
        await self.session.flush()

        await self._log_audit(
            org_id=org_id,
            actor_user_id=actor_user_id,
            action="member_role_changed",
            resource_type="org_membership",
            resource_id=str(membership.id),
            metadata={
                "target_user_id": str(user_id),
                "old_role": old_role.value,
                "new_role": new_role.value,
            },
        )

        return membership

    async def remove_member(self, org_id: uuid.UUID, user_id: uuid.UUID, actor_user_id: uuid.UUID) -> bool:
        """Remove a member from the organization."""
        stmt = select(OrgMembership).where(
            OrgMembership.org_id == org_id,
            OrgMembership.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        membership = result.scalar_one_or_none()

        if not membership:
            return False

        membership_id = str(membership.id)
        removed_role = membership.role.value

        await self.session.delete(membership)
        await self.session.flush()

        await self._log_audit(
            org_id=org_id,
            actor_user_id=actor_user_id,
            action="member_removed",
            resource_type="org_membership",
            resource_id=membership_id,
            metadata={
                "target_user_id": str(user_id),
                "removed_role": removed_role,
            },
        )

        return True

    async def get_membership(self, org_id: uuid.UUID, user_id: uuid.UUID) -> Optional[OrgMembership]:
        """Get a specific membership."""
        stmt = select(OrgMembership).where(
            OrgMembership.org_id == org_id,
            OrgMembership.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()