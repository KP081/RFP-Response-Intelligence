"""Jobs module for async task queue management."""

from app.modules.jobs.router import router as jobs_router

__all__ = ["jobs_router"]