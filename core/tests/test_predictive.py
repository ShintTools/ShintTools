# core/tests/test_predictive.py
#
# Predictive Profiler API surface (M0): tier gating, the profiles endpoint,
# and 501 milestone markers on the not-yet-shipped engines. The prediction
# engine itself is unit-tested in core/modules/predictive/tests/.

from unittest.mock import AsyncMock

import pytest


def _patch_tier(monkeypatch, tier: str, reason: str = ""):
    """The predictive routes gate through api.tier_guard's module global."""
    monkeypatch.setattr(
        "api.tier_guard.resolve_tier_detailed",
        AsyncMock(return_value=(tier, reason)),
    )


# ── Tier gating ──────────────────────────────────────────────────────────────


class TestTierGating:
    """The whole /predict/* surface is Studio-exclusive."""

    @pytest.mark.anyio
    async def test_free_tier_returns_403(self, async_client):
        resp = await async_client.get("/predict/profiles")
        assert resp.status_code == 403
        data = resp.json()
        assert data["detail"]["required_tier"] == "studio"
        assert data["detail"]["current_tier"] == "free"
        assert "Predictive Profiler" in data["detail"]["error"]

    @pytest.mark.anyio
    async def test_indie_tier_returns_403(self, async_client, monkeypatch):
        _patch_tier(monkeypatch, "indie")
        resp = await async_client.get("/predict/profiles?api_key=k")
        assert resp.status_code == 403
        assert resp.json()["detail"]["current_tier"] == "indie"

    @pytest.mark.anyio
    @pytest.mark.parametrize("tier", ["studio", "enterprise"])
    async def test_studio_and_enterprise_get_200(
        self, async_client, monkeypatch, tier
    ):
        # Enterprise is a superset of Studio (GH #37 regression).
        _patch_tier(monkeypatch, tier)
        resp = await async_client.get("/predict/profiles?api_key=k")
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_unresolved_key_403_carries_reason(self, async_client, monkeypatch):
        _patch_tier(monkeypatch, "free", "key_not_found")
        resp = await async_client.get("/predict/profiles?api_key=k")
        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert detail["reason"] == "key_not_found"
        assert detail["message"]  # human-readable hint attached


# ── Profiles ─────────────────────────────────────────────────────────────────


class TestProfiles:
    @pytest.mark.anyio
    async def test_profiles_shape(self, async_client, monkeypatch):
        _patch_tier(monkeypatch, "studio")
        resp = await async_client.get("/predict/profiles?api_key=k")
        assert resp.status_code == 200
        data = resp.json()
        assert data["schema_version"] == "1.0"
        names = {p["profile"] for p in data["profiles"]}
        assert "desktop_60" in names and "mobile_30" in names
        baseline = next(p for p in data["profiles"] if p["profile"] == "desktop_60")
        # Budgets are the score denominators — the client renders them raw.
        for field in ("frame_budget_ms", "cpu_budget_ms", "gpu_budget_ms",
                      "vram_budget_mb", "ram_budget_mb", "reference_hw"):
            assert field in baseline


# ── Analyze (M1: one-shot, assets layer) ─────────────────────────────────────

_ONESHOT = {
    "api_key": "k",
    "engine": "UE5",
    "project_name": "Demo",
    "platform_profile": "desktop_60",
    "assets": [
        {
            "asset_path": "/Game/T_Big",
            "asset_type": "Texture2D",
            "usage": "BaseColor",
            "width": 4096,
            "height": 4096,
            "compression": "BC7",
            "mips_enabled": True,
            "streaming": True,
            "lod_group": "World",
        }
    ],
}


class TestAnalyze:
    @pytest.mark.anyio
    async def test_analyze_gated_first(self, async_client):
        # Gate runs before anything else: free tier sees 403.
        resp = await async_client.post("/predict/analyze", json={"api_key": ""})
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_oneshot_returns_full_report(self, async_client, monkeypatch):
        _patch_tier(monkeypatch, "studio")
        resp = await async_client.post("/predict/analyze", json=_ONESHOT)
        assert resp.status_code == 200
        data = resp.json()
        assert data["schema_version"] == "1.0"
        assert data["report_id"].startswith("pr-")
        # 4096² BC7 + mips = 21.33 MB, exact.
        vram = data["memory"]["vram"]["predicted"]
        assert abs(vram["expected"] - 21.33) < 0.05
        assert vram["confidence"] == "high"
        # The oversized texture fires LT003 → a simulator-ready item.
        assert data["top_issues"]
        assert data["top_issues"][0]["remediation"]["recovery"]
        assert data["stats"]["assets_analyzed"] == 1

    @pytest.mark.anyio
    async def test_unknown_session_is_404(self, async_client, monkeypatch):
        _patch_tier(monkeypatch, "studio")
        resp = await async_client.post(
            "/predict/analyze", json={"api_key": "k", "session_id": "ps-nope"}
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_simulate_501_until_m4(self, async_client, monkeypatch):
        _patch_tier(monkeypatch, "studio")
        resp = await async_client.post(
            "/predict/simulate", json={"api_key": "k", "report_id": "x"}
        )
        assert resp.status_code == 501
        assert resp.json()["detail"]["milestone"] == "M4"


# ── Batched sessions (M3) ────────────────────────────────────────────────────


class TestSessions:
    """start → ingest (chunked) → analyze. Mongo is down in tests, so this
    exercises the in-process fallback path end to end."""

    @staticmethod
    def _assets_batch(n, offset=0):
        return {
            "assets": [
                {
                    "asset_path": f"/Game/T_{i}",
                    "asset_type": "Texture2D",
                    "usage": "BaseColor",
                    "width": 2048,
                    "height": 2048,
                    "compression": "BC7",
                    "mips_enabled": True,
                    "streaming": True,
                    "lod_group": "World",
                }
                for i in range(offset, offset + n)
            ]
        }

    @pytest.mark.anyio
    async def test_full_session_flow(self, async_client, monkeypatch):
        _patch_tier(monkeypatch, "studio")
        start = await async_client.post(
            "/predict/session/start",
            json={"api_key": "k", "engine": "UE5",
                  "project_name": "Big", "platform_profile": "desktop_60"},
        )
        assert start.status_code == 200
        session_id = start.json()["session_id"]
        assert session_id.startswith("ps-")

        # Two asset batches + a scene + code, like a real chunked client.
        for offset in (0, 150):
            ingest = await async_client.post(
                "/predict/session/ingest",
                json={"api_key": "k", "session_id": session_id,
                      "kind": "assets",
                      "payload": self._assets_batch(150, offset)},
            )
            assert ingest.status_code == 200
            assert ingest.json()["accepted"] == 150
        assert ingest.json()["total_ingested"]["assets"] == 300

        scene = await async_client.post(
            "/predict/session/ingest",
            json={"api_key": "k", "session_id": session_id, "kind": "scene",
                  "payload": {"scenes": [{
                      "scene_name": "L_Main", "actor_count": 4000,
                      "ticking_actors": 800,
                      "lights": [{"type": "Point", "mobility": "Movable",
                                  "casts_shadows": True}],
                  }]}},
        )
        assert scene.status_code == 200

        code = await async_client.post(
            "/predict/session/ingest",
            json={"api_key": "k", "session_id": session_id, "kind": "code",
                  "payload": {"issues": [{
                      "rule_id": "CP006",
                      "rule_name": "GetAllActorsOfClass in Tick",
                      "occurrence_context": {"in_tick": True},
                  }]}},
        )
        assert code.status_code == 200

        resp = await async_client.post(
            "/predict/analyze",
            json={"api_key": "k", "session_id": session_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["stats"]["assets_analyzed"] == 300
        assert data["stats"]["scenes_analyzed"] == 1
        assert data["stats"]["code_issues_costed"] == 1
        # All four axes scored: scene gives cpu+gpu, assets memory+build.
        assert data["scores"]["gpu_risk"]["drivers"] or (
            data["frame_budget"]["gpu"]["predicted"] is not None
        )
        assert data["scene_summaries"][0]["scene_name"] == "L_Main"

    @pytest.mark.anyio
    async def test_ingest_unknown_session_404(self, async_client, monkeypatch):
        _patch_tier(monkeypatch, "studio")
        resp = await async_client.post(
            "/predict/session/ingest",
            json={"api_key": "k", "session_id": "ps-nope", "kind": "assets",
                  "payload": {"assets": []}},
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_ingest_invalid_kind_422(self, async_client, monkeypatch):
        _patch_tier(monkeypatch, "studio")
        start = await async_client.post(
            "/predict/session/start", json={"api_key": "k"}
        )
        resp = await async_client.post(
            "/predict/session/ingest",
            json={"api_key": "k",
                  "session_id": start.json()["session_id"],
                  "kind": "textures", "payload": {}},
        )
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_session_routes_are_gated(self, async_client):
        resp = await async_client.post(
            "/predict/session/start", json={"api_key": ""}
        )
        assert resp.status_code == 403
