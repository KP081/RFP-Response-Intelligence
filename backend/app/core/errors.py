"""Consistent JSON error responses for the API."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = structlog.get_logger(__name__)


def error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    """Build the error envelope shared by every API endpoint."""

    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or {}}},
    )


async def request_validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return validation failures without FastAPI's default response shape."""

    assert isinstance(exc, RequestValidationError)
    return error_response(
        status_code=422,
        code="validation_error",
        message="Request validation failed",
        details={"errors": exc.errors()},
    )


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return HTTP failures in the standard envelope."""

    assert isinstance(exc, StarletteHTTPException)
    detail = exc.detail
    message = detail if isinstance(detail, str) else "HTTP request failed"
    details: dict[str, Any] = detail if isinstance(detail, dict) else {}
    return error_response(
        status_code=exc.status_code,
        code=f"http_{exc.status_code}",
        message=message,
        details=details,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log unexpected errors while keeping implementation details private."""

    logger.exception("unhandled_exception", path=request.url.path)
    return error_response(
        status_code=500,
        code="internal_server_error",
        message="An unexpected error occurred",
    )
