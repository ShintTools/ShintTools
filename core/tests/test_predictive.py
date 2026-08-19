# core/tests/test_predictive.py
#
# Predictive Profiler API surface (M0): tier gating, the profiles endpoint,
# and 501 milestone markers on the not-yet-shipped engines. The prediction
# engine itself is unit-tested in core/modules/predictive/tests/.

import asyncio
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
        # Every asset gets a cost item (name + cost), flagged or not — find
        # the flagged one by title rather than assuming position [0].
        assert data["top_issues"]
        flagged = next(
            i for i in data["top_issues"] if i["title"] == "/Game/T_Big"
        )
        assert flagged["remediation"]["recovery"]
        assert flagged["title"] == "/Game/T_Big"  # name, not a rule sentence
        assert data["stats"]["assets_analyzed"] == 1

    @pytest.mark.anyio
    async def test_unflagged_expensive_asset_outranks_small_flagged_issue(
        self, async_client, monkeypatch
    ):
        # Ranking is budget-normalized cost magnitude, not "has a rule
        # fired" — a huge clean texture should still surface above a code
        # issue that barely dents the CPU budget.
        _patch_tier(monkeypatch, "studio")
        payload = {
            "api_key": "k",
            "engine": "UE5",
            # mobile_30's tight VRAM budget (2048 MB) vs desktop's CPU
            # budget (18 ms) makes the texture the bigger budget fraction —
            # 21.33/2048 > 0.05/18.
            "platform_profile": "mobile_30",
            "assets": [
                {
                    "asset_path": "/Game/T_Huge_Clean",
                    "asset_type": "Texture2D",
                    "usage": "BaseColor",
                    "width": 4096,
                    "height": 4096,
                    "compression": "BC7",
                    "mips_enabled": True,
                    "streaming": True,
                    "lod_group": "Cinematic",  # high budget: no LT003 finding
                }
            ],
            "code_issues": [
                {"rule_id": "CP002", "rule_name": "GetComponent in Tick",
                 "file": "Source/Enemy.cpp", "line": 10, "severity": "warning"}
            ],
        }
        resp = await async_client.post("/predict/analyze", json=payload)
        assert resp.status_code == 200
        titles = [i["title"] for i in resp.json()["top_issues"]]
        assert titles.index("/Game/T_Huge_Clean") < titles.index(
            "Source/Enemy.cpp:10"
        )

    @pytest.mark.anyio
    async def test_analyze_does_not_block_the_event_loop(
        self, async_client, monkeypatch
    ):
        """A large analyze is synchronous CPU work — it must run in a worker
        thread (asyncio.to_thread), not inline in the async handler, or every
        other in-flight request (starting with /health) stalls behind it.

        Regression for the measured bug: a 20k-asset one-shot analyze on a
        live Core spiked /health latency from ~3 ms to 1.6+ s because the
        route awaited analyze_oneshot() directly on the event loop.
        """
        import time

        from predictive.predictive_orchestrator import (
            analyze_oneshot as _real_analyze_oneshot,
        )

        _patch_tier(monkeypatch, "studio")

        window: dict[str, float] = {}

        def _slow_analyze_oneshot(request):
            window["start"] = time.perf_counter()
            time.sleep(0.3)  # simulates a large project's CPU-bound cost
            window["end"] = time.perf_counter()
            return _real_analyze_oneshot(request)

        monkeypatch.setattr(
            "predictive.predictive_orchestrator.analyze_oneshot",
            _slow_analyze_oneshot,
        )

        tick_times: list[float] = []

        async def _tick_counter():
            for _ in range(20):
                await asyncio.sleep(0.02)
                tick_times.append(time.perf_counter())

        analyze_task = asyncio.ensure_future(
            async_client.post("/predict/analyze", json=_ONESHOT)
        )
        tick_task = asyncio.ensure_future(_tick_counter())
        resp = await analyze_task
        await tick_task

        assert resp.status_code == 200
        assert "start" in window and "end" in window
        # If analyze ran inline on the event loop, no tick could land while
        # the 0.3 s blocking sleep was in flight — they would all queue up
        # and fire back-to-back only after it released the loop. Offloaded
        # to a worker thread (the fix), several ticks land strictly inside
        # that window because the loop stays free to run them.
        ticks_during_block = [
            t for t in tick_times if window["start"] < t < window["end"]
        ]
        assert len(ticks_during_block) >= 5, (
            f"only {len(ticks_during_block)} ticks ran while analyze was "
            "blocking — the event loop looks stalled"
        )

    @pytest.mark.anyio
    async def test_unknown_session_is_404(self, async_client, monkeypatch):
        _patch_tier(monkeypatch, "studio")
        resp = await async_client.post(
            "/predict/analyze", json={"api_key": "k", "session_id": "ps-nope"}
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_simulate_unknown_report_404(self, async_client, monkeypatch):
        _patch_tier(monkeypatch, "studio")
        resp = await async_client.post(
            "/predict/simulate", json={"api_key": "k", "report_id": "pr-nope"}
        )
        assert resp.status_code == 404


# ── Impact Simulator (M4) ────────────────────────────────────────────────────


class TestSimulate:
    """analyze → cached report → simulate: the full simulator round trip."""

    _PAYLOAD = {
        "api_key": "k",
        "engine": "UE5",
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
        "scenes": [
            {
                "scene_name": "L_Main",
                "actor_count": 4000,
                "lights": [
                    {"type": "Point", "mobility": "Movable",
                     "casts_shadows": True}
                ],
            }
        ],
    }

    @pytest.mark.anyio
    async def test_round_trip(self, async_client, monkeypatch):
        _patch_tier(monkeypatch, "studio")
        report = (
            await async_client.post("/predict/analyze", json=self._PAYLOAD)
        ).json()
        ids = [i["item_id"] for i in report["cost_items"]]
        assert ids, "fixture must produce simulatable items"

        resp = await async_client.post(
            "/predict/simulate",
            json={"api_key": "k", "report_id": report["report_id"],
                  "selected_item_ids": ids},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["selected_count"] == len(ids)
        assert data["deltas"]["vram_mb"]["expected"] < 0
        assert data["deltas"]["gpu_ms_frame"]["expected"] < 0
        assert (
            data["scores_after"]["overall_project_health"]
            >= data["scores_before"]["overall_project_health"]
        )

    @pytest.mark.anyio
    async def test_stateless_fallback(self, async_client, monkeypatch):
        _patch_tier(monkeypatch, "studio")
        report = (
            await async_client.post("/predict/analyze", json=self._PAYLOAD)
        ).json()
        item = report["cost_items"][0]
        # Expired report_id but inline items → deltas still work.
        resp = await async_client.post(
            "/predict/simulate",
            json={"api_key": "k", "report_id": "pr-expired",
                  "selected_item_ids": [item["item_id"]],
                  "cost_items": report["cost_items"]},
        )
        assert resp.status_code == 200
        assert resp.json()["selected_count"] == 1

    @pytest.mark.anyio
    async def test_simulate_is_gated(self, async_client):
        resp = await async_client.post(
            "/predict/simulate", json={"api_key": ""}
        )
        assert resp.status_code == 403


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
    async def test_code_files_ingest_scans_in_process(self, async_client, monkeypatch):
        # No client pre-scan required — raw source in, costed items out.
        _patch_tier(monkeypatch, "studio")
        start = await async_client.post(
            "/predict/session/start",
            json={"api_key": "k", "engine": "UE5",
                  "project_name": "Scanned", "platform_profile": "desktop_60"},
        )
        session_id = start.json()["session_id"]

        cpp_tick_body = (
            "void AMyActor::Tick(float DeltaTime)\n"
            "{\n"
            "    Super::Tick(DeltaTime);\n"
            "    if (bShouldSearch)\n"
            "    {\n"
            "        for (int i = 0; i < 10; i++)\n"
            "        {\n"
            "            if (i > 0)\n"
            "            {\n"
            "                GetAllActorsOfClass<AActor>(this, Out);\n"
            "            }\n"
            "        }\n"
            "    }\n"
            "}\n"
        )
        ingest = await async_client.post(
            "/predict/session/ingest",
            json={"api_key": "k", "session_id": session_id, "kind": "code_files",
                  "payload": {"files": [
                      {"path": "Source/MyActor.cpp", "content": cpp_tick_body}
                  ]}},
        )
        assert ingest.status_code == 200
        assert ingest.json()["total_ingested"]["code_files"] == 1

        resp = await async_client.post(
            "/predict/analyze", json={"api_key": "k", "session_id": session_id}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["stats"]["code_issues_costed"] >= 1
        assert any(i["rule_id"] == "CP006" for i in data["cost_items"])

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
