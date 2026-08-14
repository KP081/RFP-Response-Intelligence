"""Development data seeding script for local development.

Idempotently creates one demo organization and one demo admin user.
Safe to re-run multiple times.
"""

import asyncio
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.sql import select

from app.core.settings import settings
from app.db.models import Org, User, OrgMembership, Role, Base


async def seed_dev_data() -> None:
    """Seed development database with demo org and admin user."""

    # Create async engine and session factory
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    async_session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session_factory() as session:
        # Create demo org (idempotently — check if it exists first)
        demo_org_id = uuid.uuid5(uuid.NAMESPACE_DNS, "demo.local")
        existing_org = await session.get(Org, demo_org_id)
        
        if existing_org is None:
            demo_org = Org(
                id=demo_org_id,
                name="Demo Organization",
                settings={"description": "Seeded demo organization for local development"},
            )
            session.add(demo_org)
            await session.flush()  # Ensure org is created before membership
        else:
            demo_org = existing_org

        # Create demo admin user (idempotently)
        demo_user_email = "admin@demo.local"
        admin_stmt = select(User).where(User.email == demo_user_email)
        existing_user = await session.scalar(admin_stmt)
        
        if existing_user is None:
            demo_user = User(
                id=uuid.uuid5(uuid.NAMESPACE_DNS, demo_user_email),
                email=demo_user_email,
                display_name="Demo Admin",
            )
            session.add(demo_user)
            await session.flush()  # Ensure user is created
        else:
            demo_user = existing_user

        # Create org membership (idempotently — check if it exists)
        membership_stmt = select(OrgMembership).where(
            (OrgMembership.org_id == demo_org.id)
            & (OrgMembership.user_id == demo_user.id)
        )
        existing_membership = await session.scalar(membership_stmt)
        
        if existing_membership is None:
            membership = OrgMembership(
                id=uuid.uuid4(),
                org_id=demo_org.id,
                user_id=demo_user.id,
                role=Role.ADMIN,
            )
            session.add(membership)

        # Commit all changes
        await session.commit()
        print(f"✓ Seeded demo organization: {demo_org.name} (id={demo_org.id})")
        print(f"✓ Seeded demo admin user: {demo_user.display_name} ({demo_user.email})")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed_dev_data())
