import json

import pytest
from api.main import app


async def _fake_resolve(tier: str, reason: str = ""):
    async def _inner(_api_key: str):
        return tier, reason

    return _inner


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


# ── POST /config auth (security audit 2026-08-25 — CSRF fix) ────────────────
#
# POST /config previously accepted an unauthenticated write from anyone who
# could reach the Core's fixed loopback address — including a malicious
# webpage's forged cross-origin request, since nothing stopped the request
# from being SENT (CORS only gates whether the response can be READ back).
# Now requires (1) a resolvable api_key and (2) no mismatched Origin header.


@pytest.mark.anyio
async def test_post_config_requires_api_key(async_client, tmp_path, monkeypatch):
    config_file = tmp_path / "shinttools.config.json"
    config_file.write_text('{"project_name": "TestGame"}')
    app.state.config_path = config_file

    monkeypatch.setattr(
        "api.tier_guard.resolve_tier_detailed",
        await _fake_resolve("free", "empty_key"),
    )

    response = await async_client.post("/config", json={"project_name": "Evil"})

    assert response.status_code == 401
    # The file must be untouched — the write never happened.
    assert json.loads(config_file.read_text())["project_name"] == "TestGame"


@pytest.mark.anyio
async def test_post_config_rejects_mismatched_origin(
    async_client, tmp_path, monkeypatch
):
    config_file = tmp_path / "shinttools.config.json"
    config_file.write_text('{"project_name": "TestGame"}')
    app.state.config_path = config_file

    # Valid key resolves fine — the Origin check must still block this.
    monkeypatch.setattr(
        "api.tier_guard.resolve_tier_detailed", await _fake_resolve("indie", "")
    )

    response = await async_client.post(
        "/config?api_key=valid-key",
        json={"project_name": "Evil", "core_host": "attacker.example.com"},
        headers={"Origin": "https://attacker.example.com"},
    )

    assert response.status_code == 403
    assert json.loads(config_file.read_text())["project_name"] == "TestGame"


@pytest.mark.anyio
async def test_post_config_succeeds_with_valid_key_and_no_origin(
    async_client, tmp_path, monkeypatch
):
    """Mirrors the real UE5/Unity plugin: a valid api_key, no Origin header
    at all (native HTTP clients never send one) — must still work."""
    config_file = tmp_path / "shinttools.config.json"
    config_file.write_text('{"project_name": "TestGame"}')
    app.state.config_path = config_file

    monkeypatch.setattr(
        "api.tier_guard.resolve_tier_detailed", await _fake_resolve("studio", "")
    )

    response = await async_client.post(
        "/config?api_key=valid-key", json={"project_name": "Updated"}
    )

    assert response.status_code == 200
    assert json.loads(config_file.read_text())["project_name"] == "Updated"


@pytest.mark.anyio
async def test_post_config_allows_whitelisted_origin(
    async_client, tmp_path, monkeypatch
):
    config_file = tmp_path / "shinttools.config.json"
    config_file.write_text('{"project_name": "TestGame"}')
    app.state.config_path = config_file

    monkeypatch.setattr(
        "api.tier_guard.resolve_tier_detailed", await _fake_resolve("studio", "")
    )

    response = await async_client.post(
        "/config?api_key=valid-key",
        json={"project_name": "Updated"},
        headers={"Origin": "http://127.0.0.1:18200"},
    )

    assert response.status_code == 200
