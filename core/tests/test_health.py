import pytest
from api.version import CORE_VERSION


@pytest.mark.anyio
async def test_status_returns_ok(async_client):
    """
    Verifies that GET /status returns 200 with the expected fields.
    """
    response = await async_client.get("/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == CORE_VERSION
    assert "modules" in body
    assert "commit" in body
    # LLM status surfaces the background-load state machine.
    assert "llm" in body and "status" in body["llm"]


@pytest.mark.anyio
async def test_status_modules_are_listed(async_client):
    """
    Verifies that GET /status returns the available modules.
    """
    response = await async_client.get("/status")

    assert response.status_code == 200
    assert isinstance(response.json()["modules"], list)


@pytest.mark.anyio
async def test_health_returns_ok(async_client):
    """
    Verifies that GET /health returns 200 with status, version, and commit.
    """
    response = await async_client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == CORE_VERSION
    assert "commit" in body
    assert (
        body["commit"] in ("unknown",) or len(body["commit"]) == 7
    )  # short SHA is 7 chars
    # llm_status MUST be present so the wizard can render it without a
    # KeyError fallback path.
    assert "llm_status" in body
