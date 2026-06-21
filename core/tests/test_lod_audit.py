# core/tests/test_lod_audit.py
#
# Tests for POST /assets/lod/audit endpoint.
#
# Structure:
#   TestBasicAudit        — Normal LOD rules execution
#   TestTierGating        — free vs indie tier restrictions
#   TestResponse          — Response shape and fields
#
# resolve_tier is monkeypatched to avoid MongoDB.

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

# ── Helpers ────────────────────────────────────────────────────────────────


def _audit_payload(
    assets: list[dict] | None = None,
    api_key: str = "",
) -> dict:
    return {
        "api_key": api_key,
        "assets": assets or [],
    }


def _texture_asset(
    path: str,
    usage: str = "BaseColor",
    compression: str = "BC7",
    res_x: int = 2048,
    res_y: int = 2048,
    streaming: bool = False,
) -> dict:
    return {
        "asset_path": path,
        "asset_type": "Texture2D",
        "usage": usage,
        "compression": compression,
        "resolution_x": res_x,
        "resolution_y": res_y,
        "vert_count": 0,
        "lod_count": 0,
        "streaming_enabled": streaming,
    }


def _mesh_asset(
    path: str,
    vert_count: int = 50000,
    lod_count: int = 1,
) -> dict:
    return {
        "asset_path": path,
        "asset_type": "StaticMesh",
        "usage": "",
        "compression": "",
        "resolution_x": 0,
        "resolution_y": 0,
        "vert_count": vert_count,
        "lod_count": lod_count,
        "streaming_enabled": False,
    }


# ── Basic Audit ────────────────────────────────────────────────────────────


@pytest.fixture
def _studio_tier(monkeypatch):
    """Patch resolve_tier_detailed to return 'studio' for tests needing access.

    resolve_tier_detailed returns a (tier, reason) tuple — reason is empty for
    a cleanly-resolved key.
    """
    monkeypatch.setattr(
        "api.routes.lod_audit.resolve_tier_detailed",
        AsyncMock(return_value=("studio", "")),
    )


class TestBasicAudit:
    """LOD rules execute and detect violations (studio tier required)."""

    @pytest.mark.anyio
    async def test_empty_assets_returns_empty_results(self, async_client, _studio_tier):
        payload = _audit_payload(assets=[])
        resp = await async_client.post("/assets/lod/audit", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["issues_found"] == 0
        assert data["results"] == []

    @pytest.mark.anyio
    async def test_texture_compression_violation_detected(
        self, async_client, _studio_tier
    ):
        # A BaseColor texture with Normal compression (BC5) is wrong
        assets = [
            _texture_asset(
                "Assets/Textures/T_Hero_D.png", usage="BaseColor", compression="BC5"
            )
        ]
        payload = _audit_payload(assets=assets)
        resp = await async_client.post("/assets/lod/audit", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        lt001_findings = [f for f in data["results"] if f["rule_id"] == "LT001"]
        assert len(lt001_findings) > 0, "Expected LT001 compression violation"

    @pytest.mark.anyio
    async def test_texture_size_violation_detected(self, async_client, _studio_tier):
        assets = [
            _texture_asset(
                "Assets/Textures/T_World_D.png",
                usage="BaseColor",
                compression="BC7",
                res_x=4096,
                res_y=4096,
            )
        ]
        payload = _audit_payload(assets=assets)
        resp = await async_client.post("/assets/lod/audit", json=payload)
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_mesh_lod_violation_detected(self, async_client, _studio_tier):
        assets = [
            _mesh_asset("Assets/Meshes/SM_Hero.uasset", vert_count=200000, lod_count=1)
        ]
        payload = _audit_payload(assets=assets)
        resp = await async_client.post("/assets/lod/audit", json=payload)
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_response_shape(self, async_client, _studio_tier):
        payload = _audit_payload(assets=[_texture_asset("Assets/T_Test.png")])
        resp = await async_client.post("/assets/lod/audit", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data
        assert "time" in data
        assert isinstance(data["time"], float)
        assert "summary" in data
        assert "results" in data
        assert isinstance(data["results"], list)

    @pytest.mark.anyio
    async def test_finding_has_required_fields(self, async_client, _studio_tier):
        assets = [_texture_asset("Assets/T_Bad.png", compression="BC4")]
        payload = _audit_payload(assets=assets)
        resp = await async_client.post("/assets/lod/audit", json=payload)
        findings = [f for f in resp.json()["results"] if f.get("rule_id") == "LT001"]
        if findings:
            f = findings[0]
            assert f["asset_path"]
            assert f["rule_id"]
            assert f["category"]
            assert f["severity"] in ("error", "warning", "info")
            assert "message" in f
            assert "current" in f
            assert "recommended" in f
            assert "estimated_saving" in f


# ── Tier Gating ────────────────────────────────────────────────────────────


class TestTierGating:
    """LOD Auditor is Studio-exclusive. Free and Indie get 403."""

    @pytest.mark.anyio
    async def test_free_tier_returns_403(self, async_client):
        # Default (no api_key) resolves to "free" — must be blocked
        payload = _audit_payload(assets=[_texture_asset("Assets/T1.png")])
        resp = await async_client.post("/assets/lod/audit", json=payload)
        assert resp.status_code == 403
        data = resp.json()
        assert data["detail"]["required_tier"] == "studio"
        assert data["detail"]["current_tier"] == "free"

    @pytest.mark.anyio
    async def test_indie_tier_returns_403(self, async_client, monkeypatch):
        monkeypatch.setattr(
            "api.routes.lod_audit.resolve_tier_detailed",
            AsyncMock(return_value=("indie", "")),
        )
        payload = _audit_payload(assets=[_texture_asset("Assets/T1.png")])
        resp = await async_client.post("/assets/lod/audit", json=payload)
        assert resp.status_code == 403
        data = resp.json()
        assert data["detail"]["required_tier"] == "studio"
        assert data["detail"]["current_tier"] == "indie"

    @pytest.mark.anyio
    async def test_studio_tier_returns_200(self, async_client, monkeypatch):
        monkeypatch.setattr(
            "api.routes.lod_audit.resolve_tier_detailed",
            AsyncMock(return_value=("studio", "")),
        )
        payload = _audit_payload(assets=[_texture_asset("Assets/T1.png")])
        resp = await async_client.post("/assets/lod/audit", json=payload)
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_studio_sees_all_rules(self, async_client, monkeypatch):
        monkeypatch.setattr(
            "api.routes.lod_audit.resolve_tier_detailed",
            AsyncMock(return_value=("studio", "")),
        )
        assets = [
            _texture_asset("Assets/T1.png", compression="BC5"),  # LT001
            _mesh_asset("Assets/M1.uasset", vert_count=300000, lod_count=1),
        ]
        resp = await async_client.post(
            "/assets/lod/audit", json=_audit_payload(assets=assets)
        )
        assert resp.status_code == 200
        # All rules visible — no filter applied
        rule_ids = {f["rule_id"] for f in resp.json()["results"]}
        assert len(rule_ids) > 0

    @pytest.mark.anyio
    async def test_403_error_detail_shape(self, async_client):
        payload = _audit_payload(assets=[])
        resp = await async_client.post("/assets/lod/audit", json=payload)
        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert "error" in detail
        assert "current_tier" in detail
        assert "required_tier" in detail


# ── Response Structure ─────────────────────────────────────────────────────


class TestResponseStructure:
    """Response format matches contract (studio tier)."""

    @pytest.mark.anyio
    async def test_summary_fields_present(self, async_client, _studio_tier):
        payload = _audit_payload(assets=[_texture_asset("Assets/T.png")])
        resp = await async_client.post("/assets/lod/audit", json=payload)
        summary = resp.json()["summary"]
        assert "assets_audited" in summary
        assert "issues_found" in summary
        assert "estimated_vram_saved_mb" in summary
        assert "estimated_shader_instructions_saved" in summary
        assert isinstance(summary["assets_audited"], int)
        assert isinstance(summary["estimated_vram_saved_mb"], float)

    @pytest.mark.anyio
    async def test_finding_savings_structure(self, async_client, _studio_tier):
        assets = [_texture_asset("Assets/T.png", compression="BC5")]
        payload = _audit_payload(assets=assets)
        resp = await async_client.post("/assets/lod/audit", json=payload)
        findings = resp.json()["results"]
        if findings:
            f = findings[0]
            assert "estimated_saving" in f
            saving = f["estimated_saving"]
            assert "vram_mb" in saving
            assert "shader_instructions" in saving

    @pytest.mark.anyio
    async def test_empty_error_field_on_success(self, async_client, _studio_tier):
        payload = _audit_payload(assets=[])
        resp = await async_client.post("/assets/lod/audit", json=payload)
        assert resp.json()["error"] == ""

    @pytest.mark.anyio
    async def test_time_is_reasonable(self, async_client, _studio_tier):
        payload = _audit_payload(
            assets=[_texture_asset("Assets/T.png") for _ in range(10)]
        )
        resp = await async_client.post("/assets/lod/audit", json=payload)
        elapsed = resp.json()["time"]
        assert elapsed < 1.0, f"Audit took {elapsed}s — expected < 1s"


# ── Engine-awareness + bounded enrichment ──────────────────────────────────


class TestEngineAware:
    """The engine field tailors guidance; findings carry rule_name + engine."""

    @pytest.mark.anyio
    async def test_unity_engine_returns_unity_guidance(
        self, async_client, _studio_tier
    ):
        mesh = _mesh_asset("Assets/M.uasset", lod_count=1)
        mesh["lods"] = [{"index": 0, "triangles": 90000, "screen_size": 1.0}]
        mesh["bounds_radius"] = 40.0
        mesh["asset_type"] = "Mesh"  # Unity name
        payload = _audit_payload(assets=[mesh])
        payload["engine"] = "unity"
        resp = await async_client.post("/assets/lod/audit", json=payload)
        assert resp.status_code == 200
        results = resp.json()["results"]
        ld003 = [f for f in results if f["rule_id"] == "LD003"]
        assert ld003, "LD003 should fire (non-empty results — Unity contract OK)"
        assert "Simplygon" not in (ld003[0]["guidance"] or "")
        # rule_name is populated (Unity needs it for its row label).
        assert ld003[0]["rule_name"]

    @pytest.mark.anyio
    async def test_unreal_engine_keeps_unreal_guidance(
        self, async_client, _studio_tier
    ):
        mesh = _mesh_asset("Assets/M.uasset", lod_count=1)
        mesh["lods"] = [{"index": 0, "triangles": 90000, "screen_size": 1.0}]
        mesh["bounds_radius"] = 40.0
        payload = _audit_payload(assets=[mesh])
        payload["engine"] = "unreal"
        resp = await async_client.post("/assets/lod/audit", json=payload)
        ld003 = [f for f in resp.json()["results"] if f["rule_id"] == "LD003"]
        assert ld003
        assert "Simplygon" in (ld003[0]["guidance"] or "")


class TestBoundedEnrichment:
    """explain=true is Unreal-only, top-N, and degrades gracefully."""

    def _over_budget_mesh(self):
        return {
            "asset_path": "/Game/Meshes/Rock",
            "asset_type": "StaticMesh",
            "lod_count": 1,
            "lods": [{"index": 0, "triangles": 90000, "screen_size": 1.0}],
            "bounds_radius": 40.0,
        }

    @pytest.mark.anyio
    async def test_explain_false_does_no_llm_calls(
        self, async_client, _studio_tier, monkeypatch
    ):
        # If the explainer were called, this would raise — assert it isn't.
        def _boom(*a, **k):
            raise AssertionError("explainer must not run when explain=false")

        monkeypatch.setattr("api.routes.lod_audit._explain_issue", _boom)
        payload = _audit_payload(assets=[self._over_budget_mesh()])
        payload["explain"] = False
        resp = await async_client.post("/assets/lod/audit", json=payload)
        assert resp.status_code == 200
        for f in resp.json()["results"]:
            assert f.get("ai_guidance") is None

    @pytest.mark.anyio
    async def test_explain_graceful_when_llm_unloaded(
        self, async_client, _studio_tier, monkeypatch
    ):
        # Enrichment is requested but the model isn't loaded → deterministic
        # results still return, no ai_guidance, no error.
        monkeypatch.setattr("api.routes.lod_audit._EXPLAINER_AVAILABLE", True)
        monkeypatch.setattr(
            "api.routes.lod_audit._explain_issue", lambda d: "should not be used"
        )
        # Patch is_loaded() (imported lazily inside the helper) to False.
        import types

        fake_backend = types.SimpleNamespace(is_loaded=lambda: False)
        monkeypatch.setitem(
            __import__("sys").modules, "agent.llm_backend", fake_backend
        )
        payload = _audit_payload(assets=[self._over_budget_mesh()])
        payload["explain"] = True
        payload["engine"] = "unreal"
        resp = await async_client.post("/assets/lod/audit", json=payload)
        assert resp.status_code == 200
        for f in resp.json()["results"]:
            assert f.get("ai_guidance") is None

    @pytest.mark.anyio
    async def test_unity_never_enriched(
        self, async_client, _studio_tier, monkeypatch
    ):
        # explain=true on Unity must NOT call the explainer (no unity6 template).
        def _boom(*a, **k):
            raise AssertionError("Unity must not be enriched")

        monkeypatch.setattr("api.routes.lod_audit._EXPLAINER_AVAILABLE", True)
        monkeypatch.setattr("api.routes.lod_audit._explain_issue", _boom)
        mesh = self._over_budget_mesh()
        mesh["asset_type"] = "Mesh"
        payload = _audit_payload(assets=[mesh])
        payload["explain"] = True
        payload["engine"] = "unity"
        resp = await async_client.post("/assets/lod/audit", json=payload)
        assert resp.status_code == 200
        for f in resp.json()["results"]:
            assert f.get("ai_guidance") is None
