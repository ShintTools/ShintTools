# core/tests/conftest.py

import pytest
from api.main import app
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def async_client():
    """
    Provides an async HTTP client connected to the FastAPI app.
    Initializes app state before running tests.
    """
    # Initialize app state manually for tests
    app.state.modules = ["code_validator", "naming"]
    app.state.config_path = None

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
