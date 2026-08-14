"""FastAPI application factory and top-level wiring."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import router as v1_router
from app.core.errors import (
    http_exception_handler,
    request_validation_exception_handler,
    unhandled_exception_handler,
)
from app.core.logging import CorrelationIdMiddleware, configure_logging
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Release database connections when the application stops."""

    yield
    await engine.dispose()


def create_app() -> FastAPI:
    """Create the configured application used by Uvicorn and tests."""

    configure_logging()
    application = FastAPI(title="RFP Response Intelligence API", lifespan=lifespan)
    application.add_middleware(CorrelationIdMiddleware)
    application.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    application.add_exception_handler(StarletteHTTPException, http_exception_handler)
    application.add_exception_handler(Exception, unhandled_exception_handler)
    application.include_router(v1_router, prefix="/api/v1")
    return application


app = create_app()
