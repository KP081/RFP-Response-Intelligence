"""Async SQLAlchemy engine and per-request session dependency."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.settings import settings


class LoopAwareEngine:
    """Create one SQLAlchemy AsyncEngine per event loop while preserving the old `engine` API."""

    def __init__(self, url: str) -> None:
        self.url = url
        self._engines: dict[asyncio.AbstractEventLoop, object] = {}

    def _get_engine(self) -> object:
        loop = asyncio.get_running_loop()
        if loop not in self._engines:
            self._engines[loop] = create_async_engine(self.url, pool_pre_ping=True)
        return self._engines[loop]

    def __getattr__(self, name: str):
        try:
            return getattr(self._get_engine(), name)
        except RuntimeError as exc:
            raise AttributeError(name) from exc

    async def dispose(self) -> None:
        for engine in list(self._engines.values()):
            await engine.dispose()
        self._engines.clear()


class LoopAwareSessionFactory:
    """Create SQLAlchemy session factories per active event loop."""

    def __init__(self, url: str) -> None:
        self.url = url
        self._factories: dict[asyncio.AbstractEventLoop, async_sessionmaker[AsyncSession]] = {}

    def _get_factory(self) -> async_sessionmaker[AsyncSession]:
        loop = asyncio.get_running_loop()
        if loop not in self._factories:
            engine = create_async_engine(self.url, pool_pre_ping=True)
            self._factories[loop] = async_sessionmaker(engine, expire_on_commit=False)
        return self._factories[loop]

    def __call__(self) -> AsyncSession:
        return self._get_factory()()

    def __getattr__(self, name: str):
        try:
            return getattr(self._get_factory(), name)
        except RuntimeError as exc:
            raise AttributeError(name) from exc


engine = LoopAwareEngine(settings.database_url)
async_session_factory = LoopAwareSessionFactory(settings.database_url)

# Migrations/superuser session factory for RLS bypass (e.g. invite token lookup before context is established)
# Created lazily per event loop since migrations_database_url may be None in test environments.
_migrations_engine = None
_migrations_session_factory = None


def _get_migrations_session_factory() -> async_sessionmaker[AsyncSession]:
    """Lazily create migrations session factory."""
    global _migrations_engine, _migrations_session_factory
    if _migrations_session_factory is None:
        if settings.migrations_database_url is None:
            raise RuntimeError("MIGRATIONS_DATABASE_URL is not configured")
        _migrations_engine = create_async_engine(settings.migrations_database_url, pool_pre_ping=True)
        _migrations_session_factory = async_sessionmaker(_migrations_engine, expire_on_commit=False)
    return _migrations_session_factory


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Yield one database session for the duration of a request."""

    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


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
        try:
            # set_config() accepts bind parameters (unlike SET LOCAL) and with
            # is_local=true it reproduces SET LOCAL's transaction-scoped behavior.
            await session.execute(
                text("SELECT set_config('app.current_org_id', :org_id, true)"),
                {"org_id": str(org_id)},
            )
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_migrations_session() -> AsyncIterator[AsyncSession]:
    """A session using the superuser/migrations connection — bypasses RLS.

    Use only for the narrow, documented cases where no RLS context can legitimately be
    established yet (e.g. resolving an invite token to its org before the accepting user
    has any membership). Do not use this as a general-purpose way to skip RLS.
    """
    factory = _get_migrations_session_factory()
    async with factory() as session:
        yield session

