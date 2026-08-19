"""Async SQLAlchemy engine and per-request session dependency."""

import uuid
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.settings import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Yield one database session for the duration of a request."""

    async with async_session_factory() as session:
        yield session


async def get_db_session_with_org_id(org_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    """Yield a database session with RLS context set for the given org_id.

    This dependency sets the 'app.current_org_id' session variable that RLS
    policies use to filter data by organization.

    Args:
        org_id: The organization ID to set in the RLS context.

    Yields:
        An AsyncSession with org_id set in the session context.
    """

    async with async_session_factory() as session:
        # set_config() accepts bind parameters (unlike SET LOCAL) and with
        # is_local=true it reproduces SET LOCAL's transaction-scoped behavior.
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org_id, true)"),
            {"org_id": str(org_id)},
        )
        yield session

