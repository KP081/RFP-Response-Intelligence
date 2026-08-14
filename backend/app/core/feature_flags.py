"""Feature flags helper for checking feature enablement per organization."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import select

from app.db.models import FeatureFlag


async def is_feature_enabled(
    session: AsyncSession, org_id: uuid.UUID, flag_name: str
) -> bool:
    """Check if a feature flag is enabled for an organization.

    Args:
        session: AsyncSession with RLS context already set.
        org_id: The organization ID (redundant with RLS context but explicit).
        flag_name: The name of the feature flag to check.

    Returns:
        True if the flag exists and is enabled, False otherwise.
    """

    stmt = select(FeatureFlag.enabled).where(
        (FeatureFlag.org_id == org_id) & (FeatureFlag.flag_name == flag_name)
    )
    result = await session.scalar(stmt)
    return result is True
