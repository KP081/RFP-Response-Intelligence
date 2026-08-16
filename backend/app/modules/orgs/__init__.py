"""Organizations module."""

from app.modules.orgs.dependencies import require_org_member
from app.modules.orgs.router import router as orgs_router

__all__ = ["orgs_router", "require_org_member"]