import pytest


@pytest.mark.anyio
async def test_status_returns_ok(async_client):
    """
    Verifies that GET /status returns 200 with the expected fields.
    """
    response = await async_client.get("/status")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["version"] == "0.1.0"
    assert "modules" in response.json()


@pytest.mark.anyio
async def test_status_modules_are_listed(async_client):
    """
    Verifies that GET /status returns the available modules.
    """
    response = await async_client.get("/status")

    assert response.status_code == 200
    assert isinstance(response.json()["modules"], list)
