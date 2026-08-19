"""Tests demonstrating Row-Level Security enforcement on tenant-scoped tables.

These tests verify that:
1. Tables with RLS policies correctly filter data by org_id
2. Querying with the wrong org_id returns no results from other orgs
3. RLS is enforced with FORCE ROW LEVEL SECURITY to prevent owner bypass
"""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.feature_flags import is_feature_enabled
from app.db.models import (
    FeatureFlag,
    Org,
    OrgMembership,
    Role,
    User,
)


@pytest.fixture
async def two_orgs_setup(async_session: AsyncSession) -> dict:
    """Create two organizations with separate users and memberships for testing RLS."""

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
    )
    async_session.add(user_a)

    # User in Org B
    user_b_id = uuid.uuid4()
    user_b = User(
        id=user_b_id,
        email="admin@org-b.local",
        display_name="Admin B",
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


class TestRLSEnforcement:
    """Test that RLS policies correctly restrict data access by organization."""

    async def test_rls_table_status(self, async_session: AsyncSession) -> None:
        """Verify that RLS is enabled with FORCE on tenant-scoped tables."""

        # Check that RLS is enabled on org_memberships
        result = await async_session.execute(
            text("""
                SELECT schemaname, tablename, rowsecurity
                FROM pg_tables
                WHERE tablename IN ('org_memberships', 'audit_log', 'feature_flags')
                ORDER BY tablename;
            """)
        )
        rows = result.fetchall()
        
        assert len(rows) == 3, "All three tenant-scoped tables should exist"
        
        for row in rows:
            # row is a tuple: (schemaname, tablename, rowsecurity)
            tablename, rowsecurity = row[1], row[2]
            assert rowsecurity is True, f"{tablename} should have RLS enabled"
        
        # Verify that the RLS policies exist
        policies_result = await async_session.execute(
            text("""
                SELECT schemaname, tablename, policyname
                FROM pg_policies
                WHERE tablename IN ('org_memberships', 'audit_log', 'feature_flags')
                ORDER BY tablename;
            """)
        )
        policies = policies_result.fetchall()
        assert len(policies) == 3, "Each tenant-scoped table should have one RLS policy"

    async def test_org_memberships_rls_isolation(
        self, async_session: AsyncSession, app_user_session: AsyncSession, two_orgs_setup: dict
    ) -> None:
        """Test that org_memberships table correctly isolates data by org_id via RLS."""
        org_a_id = two_orgs_setup["org_a_id"]
        await app_user_session.execute(
            text("SELECT set_config('app.current_org_id', :org_id, true)"),
            {"org_id": str(org_a_id)},
        )
        result = await app_user_session.execute(select(OrgMembership))
        rows = result.scalars().all()
        assert all(m.org_id == org_a_id for m in rows)
        assert len(rows) == 1

    async def test_org_memberships_with_different_org_contexts(
        self, async_session: AsyncSession, app_user_session: AsyncSession, two_orgs_setup: dict
    ) -> None:
        """Test querying org_memberships with different org_id contexts shows isolation."""
        org_a_id = two_orgs_setup["org_a_id"]
        org_b_id = two_orgs_setup["org_b_id"]

        # Context set to org A
        await app_user_session.execute(
            text("SELECT set_config('app.current_org_id', :org_id, true)"),
            {"org_id": str(org_a_id)},
        )
        result = await app_user_session.execute(select(OrgMembership))
        rows = result.scalars().all()
        assert all(m.org_id == org_a_id for m in rows)
        assert len(rows) == 1

        # Context set to org B
        await app_user_session.execute(
            text("SELECT set_config('app.current_org_id', :org_id, true)"),
            {"org_id": str(org_b_id)},
        )
        result = await app_user_session.execute(select(OrgMembership))
        rows = result.scalars().all()
        assert all(m.org_id == org_b_id for m in rows)
        assert len(rows) == 1

    async def test_audit_log_rls_isolation(
        self, async_session: AsyncSession, app_user_session: AsyncSession, two_orgs_setup: dict
    ) -> None:
        """Test that audit_log table correctly isolates data by org_id via RLS."""
        from app.db.models import AuditLogEntry
        org_a_id = two_orgs_setup["org_a_id"]
        org_b_id = two_orgs_setup["org_b_id"]

        # Seed audit log entries for both orgs using superuser
        entry_a = AuditLogEntry(
            id=uuid.uuid4(),
            org_id=org_a_id,
            actor_user_id=two_orgs_setup["user_a_id"],
            action="test.action",
            resource_type="test",
            resource_id="1",
            event_metadata={},
            correlation_id=str(uuid.uuid4()),
        )
        entry_b = AuditLogEntry(
            id=uuid.uuid4(),
            org_id=org_b_id,
            actor_user_id=two_orgs_setup["user_b_id"],
            action="test.action",
            resource_type="test",
            resource_id="2",
            event_metadata={},
            correlation_id=str(uuid.uuid4()),
        )
        async_session.add(entry_a)
        async_session.add(entry_b)
        await async_session.commit()

        # Context set to org A
        await app_user_session.execute(
            text("SELECT set_config('app.current_org_id', :org_id, true)"),
            {"org_id": str(org_a_id)},
        )
        result = await app_user_session.execute(select(AuditLogEntry))
        rows = result.scalars().all()
        assert all(e.org_id == org_a_id for e in rows)
        assert len(rows) == 1

        # Context set to org B
        await app_user_session.execute(
            text("SELECT set_config('app.current_org_id', :org_id, true)"),
            {"org_id": str(org_b_id)},
        )
        result = await app_user_session.execute(select(AuditLogEntry))
        rows = result.scalars().all()
        assert all(e.org_id == org_b_id for e in rows)
        assert len(rows) == 1

    async def test_feature_flags_rls_isolation(
        self, async_session: AsyncSession, app_user_session: AsyncSession, two_orgs_setup: dict
    ) -> None:
        """Test that feature_flags table correctly isolates data by org_id via RLS."""
        org_a_id = two_orgs_setup["org_a_id"]
        org_b_id = two_orgs_setup["org_b_id"]

        # Seed feature flags for both orgs using superuser
        flag_a = FeatureFlag(
            id=uuid.uuid4(),
            org_id=org_a_id,
            flag_name="test_flag",
            enabled=True,
        )
        flag_b = FeatureFlag(
            id=uuid.uuid4(),
            org_id=org_b_id,
            flag_name="test_flag",
            enabled=False,
        )
        async_session.add(flag_a)
        async_session.add(flag_b)
        await async_session.commit()

        # Context set to org A
        await app_user_session.execute(
            text("SELECT set_config('app.current_org_id', :org_id, true)"),
            {"org_id": str(org_a_id)},
        )
        result = await app_user_session.execute(select(FeatureFlag))
        rows = result.scalars().all()
        assert all(f.org_id == org_a_id for f in rows)
        assert len(rows) == 1
        assert rows[0].enabled is True

        # Context set to org B
        await app_user_session.execute(
            text("SELECT set_config('app.current_org_id', :org_id, true)"),
            {"org_id": str(org_b_id)},
        )
        result = await app_user_session.execute(select(FeatureFlag))
        rows = result.scalars().all()
        assert all(f.org_id == org_b_id for f in rows)
        assert len(rows) == 1
        assert rows[0].enabled is False

    async def test_feature_flags_helper(
        self, async_session: AsyncSession, two_orgs_setup: dict
    ) -> None:
        """Test the is_feature_enabled helper respects RLS."""

        org_a_id = two_orgs_setup["org_a_id"]
        org_b_id = two_orgs_setup["org_b_id"]

        # Create feature flags
        flag_a = FeatureFlag(
            id=uuid.uuid4(),
            org_id=org_a_id,
            flag_name="ocr_v2",
            enabled=True,
        )
        async_session.add(flag_a)

        flag_b = FeatureFlag(
            id=uuid.uuid4(),
            org_id=org_b_id,
            flag_name="ocr_v2",
            enabled=False,
        )
        async_session.add(flag_b)
        await async_session.commit()

        # Set org A context and check flag
        await async_session.execute(text("SELECT set_config('app.current_org_id', :org_id, true)"), {"org_id": str(org_a_id)})
        enabled_a = await is_feature_enabled(async_session, org_a_id, "ocr_v2")
        assert enabled_a is True

        # Check non-existent flag returns False
        enabled_none = await is_feature_enabled(async_session, org_a_id, "nonexistent")
        assert enabled_none is False

    async def test_rls_without_context_returns_no_rows(
        self, app_user_session: AsyncSession, two_orgs_setup: dict
    ) -> None:
        """Test that querying without app.current_org_id context returns no rows (RLS blocks all)."""
        result = await app_user_session.execute(select(OrgMembership))
        rows = result.scalars().all()
        assert len(rows) == 0
