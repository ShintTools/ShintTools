import pytest
from api.main import app


@pytest.mark.anyio
async def test_config_returns_200_when_config_exists(async_client, tmp_path):
    """
    Verifies that GET /config returns 200 when a valid config file exists.
    """
    config_file = tmp_path / "shinttools.config.json"
    config_file.write_text('{"version": "1.0", "project_name": "TestGame"}')

    app.state.config_path = config_file

    response = await async_client.get("/config")

    assert response.status_code == 200
    assert response.json()["project_name"] == "TestGame"


@pytest.mark.anyio
async def test_config_returns_400_when_no_config_path(async_client):
    """
    Verifies that GET /config returns 400 when no config path was detected.
    """
    app.state.config_path = None

    response = await async_client.get("/config")

    assert response.status_code == 400
