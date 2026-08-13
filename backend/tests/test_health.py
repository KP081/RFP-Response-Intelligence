from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1 import router as v1_router
from app.main import create_app


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    async def database_is_available() -> bool:
        return True

    monkeypatch.setattr(v1_router, "check_database_connection", database_is_available)
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client


async def test_health_returns_service_and_database_status(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health", headers={"X-Correlation-ID": "request-123"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}
    assert response.headers["X-Correlation-ID"] == "request-123"


async def test_validation_errors_use_standard_error_envelope(
    app: FastAPI, client: AsyncClient
) -> None:
    @app.get("/validation-test")
    async def validation_test(value: int) -> dict[str, int]:
        return {"value": value}

    response = await client.get("/validation-test", params={"value": "not-an-int"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["message"] == "Request validation failed"
    assert error["details"]["errors"]


async def test_not_found_uses_standard_error_envelope(client: AsyncClient) -> None:
    response = await client.get("/api/v1/missing")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "http_404", "message": "Not Found", "details": {}}}
