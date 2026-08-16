"""Version 1 API router and shared operational endpoints."""

import structlog
from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import engine
from app.modules.auth import auth_router
from app.modules.documents import documents_router
from app.modules.orgs import orgs_router

logger = structlog.get_logger(__name__)
router = APIRouter()

router.include_router(auth_router)
router.include_router(orgs_router)
router.include_router(documents_router)


async def check_database_connection() -> bool:
    """Return whether the database accepts a trivial query."""

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.warning("database_health_check_failed", exc_info=True)
        return False
    return True


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Report service reachability and database connectivity."""

    database_status = "ok" if await check_database_connection() else "error"
    return {"status": "ok", "db": database_status}
