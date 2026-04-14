import pytest


@pytest.mark.anyio
async def test_validate_assets_returns_200(async_client):
    """
    Verifies that POST /validate/assets returns 200 with mock response.
    """
    payload = {"paths": ["Content/Characters/Mesh/hero_body.uasset"]}

    response = await async_client.post("/validate/assets", json=payload)

    assert response.status_code == 200
    assert response.json()["summary"]["total"] == 0
    assert response.json()["issues"] == []


@pytest.mark.anyio
async def test_validate_code_returns_200(async_client):
    """
    Verifies that POST /validate/code returns 200 with mock response.
    """
    payload = {"file_path": "Content/Characters/Code/hero.cpp"}

    response = await async_client.post("/validate/code", json=payload)

    assert response.status_code == 200
    assert response.json()["summary"]["total"] == 0
    assert response.json()["issues"] == []
