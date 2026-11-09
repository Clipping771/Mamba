from httpx import AsyncClient


async def test_ready_reports_database_ok(client: AsyncClient, db: None) -> None:
    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
