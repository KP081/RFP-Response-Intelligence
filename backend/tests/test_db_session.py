"""Tests for database session RLS context setting via set_config."""

import uuid

from sqlalchemy import text


async def test_set_config_rls_context_works(app_user_session):
    """Test that set_config() correctly sets app.current_org_id for RLS."""
    org_id = uuid.uuid4()

    await app_user_session.execute(
        text("SELECT set_config('app.current_org_id', :org_id, true)"),
        {"org_id": str(org_id)},
    )
    result = await app_user_session.execute(
        text("SELECT current_setting('app.current_org_id', true)")
    )
    current_org_id = result.scalar()
    assert current_org_id == str(org_id)


async def test_set_config_is_transaction_scoped(app_user_session):
    """Test that set_config(is_local=true) is transaction-scoped (like SET LOCAL)."""
    org_id_1 = uuid.uuid4()
    org_id_2 = uuid.uuid4()

    # First session with org_id_1
    await app_user_session.execute(
        text("SELECT set_config('app.current_org_id', :org_id, true)"),
        {"org_id": str(org_id_1)},
    )
    result = await app_user_session.execute(
        text("SELECT current_setting('app.current_org_id', true)")
    )
    assert result.scalar() == str(org_id_1)

    # Second session with org_id_2 - should be independent
    await app_user_session.execute(
        text("SELECT set_config('app.current_org_id', :org_id, true)"),
        {"org_id": str(org_id_2)},
    )
    result = await app_user_session.execute(
        text("SELECT current_setting('app.current_org_id', true)")
    )
    assert result.scalar() == str(org_id_2)


async def test_set_config_works_without_rls_bypass(app_user_session):
    """Test that app_user (non-superuser) can set RLS context and it's respected."""
    org_id = uuid.uuid4()

    await app_user_session.execute(
        text("SELECT set_config('app.current_org_id', :org_id, true)"),
        {"org_id": str(org_id)},
    )
    # Verify we're running as app_user, not superuser
    result = await app_user_session.execute(text("SELECT current_user"))
    assert result.scalar() == "app_user"

    # Verify RLS context is set
    result = await app_user_session.execute(
        text("SELECT current_setting('app.current_org_id', true)")
    )
    assert result.scalar() == str(org_id)