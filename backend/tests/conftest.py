"""pytest configuration and fixtures for backend tests."""

import os

# Set test environment variables BEFORE any other imports
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/rfp_response")
os.environ.setdefault("OIDC_ISSUER", "http://localhost:8081/realms/rfp-response-intelligence")
os.environ.setdefault("OIDC_CLIENT_ID", "rfp-response-intelligence-web")
os.environ.setdefault("OIDC_CLIENT_SECRET", "local-development-only")
os.environ.setdefault("OIDC_REDIRECT_URI", "http://localhost:8000/api/v1/auth/callback")
os.environ.setdefault("JWT_SECRET_KEY", "dev-secret-change-in-production")
os.environ.setdefault("FRONTEND_URL", "http://localhost:5173")

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.redis import close_redis_client
from app.db.models import Base

SUPERUSER_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/rfp_response"
APP_USER_DATABASE_URL = "postgresql+asyncpg://app_user:app_password@localhost:5432/rfp_response"


@pytest.fixture(autouse=True)
async def _close_redis_after_test() -> AsyncIterator[None]:
    """Close Redis client after each test to avoid event loop issues."""
    yield
    await close_redis_client()


@pytest.fixture
async def async_session() -> AsyncIterator[AsyncSession]:
    """Provide a superuser session used for setup and test-data seeding.

    RLS is enabled on the tenant-scoped tables here, but because the postgres role
    bypasses RLS by design, this session is only used for setup and initial data
    creation. The actual read checks are performed via the app_user_session fixture.
    """
    engine = create_async_engine(SUPERUSER_DATABASE_URL, pool_pre_ping=True)

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

            await conn.execute(text("ALTER TABLE org_memberships ENABLE ROW LEVEL SECURITY;"))
            await conn.execute(text("ALTER TABLE org_memberships FORCE ROW LEVEL SECURITY;"))
            await conn.execute(text("""
                CREATE POLICY org_memberships_rls_policy ON org_memberships
                USING (
                    org_id = NULLIF(current_setting('app.current_org_id', true), '')::UUID
                )
                WITH CHECK (
                    org_id = NULLIF(current_setting('app.current_org_id', true), '')::UUID
                );
            """))

            await conn.execute(text("ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;"))
            await conn.execute(text("ALTER TABLE audit_log FORCE ROW LEVEL SECURITY;"))
            await conn.execute(text("""
                CREATE POLICY audit_log_rls_policy ON audit_log
                USING (
                    org_id = NULLIF(current_setting('app.current_org_id', true), '')::UUID
                )
                WITH CHECK (
                    org_id = NULLIF(current_setting('app.current_org_id', true), '')::UUID
                );
            """))

            await conn.execute(text("ALTER TABLE feature_flags ENABLE ROW LEVEL SECURITY;"))
            await conn.execute(text("ALTER TABLE feature_flags FORCE ROW LEVEL SECURITY;"))
            await conn.execute(text("""
                CREATE POLICY feature_flags_rls_policy ON feature_flags
                USING (
                    org_id = NULLIF(current_setting('app.current_org_id', true), '')::UUID
                )
                WITH CHECK (
                    org_id = NULLIF(current_setting('app.current_org_id', true), '')::UUID
                );
            """))

        async_session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session_factory() as session:
            yield session
    finally:
        await engine.dispose()


@pytest.fixture
async def app_user_session() -> AsyncIterator[AsyncSession]:
    """Provide a non-superuser session used to verify RLS enforcement."""
    engine = create_async_engine(APP_USER_DATABASE_URL, pool_pre_ping=True)

    try:
        async_session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session_factory() as session:
            yield session
    finally:
        await engine.dispose()

