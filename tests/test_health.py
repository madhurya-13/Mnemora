import asyncio

import httpx

from app.main import app



async def request(method: str, path: str, **kwargs: object) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


def test_root_returns_application_information() -> None:
    response = asyncio.run(request("GET", "/"))
    assert response.status_code == 200
    assert response.json() == {
        "application": "MNEMORA",
        "version": "1.0.0",
        "message": "MNEMORA API is running.",
    }


def test_health_returns_healthy_status() -> None:
    response = asyncio.run(request("GET", "/api/v1/health"))
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "application": "MNEMORA", "version": "1.0.0"}


def test_cors_allows_local_frontend() -> None:
    response = asyncio.run(request(
        "OPTIONS",
        "/api/v1/health",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    ))
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
