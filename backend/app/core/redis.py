"""Shared Redis client factory for application-wide use."""

import redis.asyncio as redis

from app.core.settings import settings

_redis_client: redis.Redis | None = None


def get_redis_client() -> redis.Redis:
    """Return a shared Redis client for caching and state storage."""
    global _redis_client
    if _redis_client is None:
        if not settings.redis_url:
            raise RuntimeError("REDIS_URL not configured")
        _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


async def close_redis_client() -> None:
    """Close the shared Redis client connection."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None