# core/modules/lod_auditor/tests/test_performance.py
#
# Performance guard for the deterministic LOD Auditor engine. The audit runs
# synchronously inside the request, so a hidden O(n^2) rule would freeze the
# editor on a large project. These tests assert the engine stays ~linear.
#
# The PRIMARY assertion is a SCALING RATIO (per-asset cost at 8k vs 1k), which
# is hardware-independent: linear ~1x, quadratic ~8x. A loose absolute ceiling
# is a secondary smoke check only. For a richer report run the standalone
# scripts/benchmark_lod.py.

from __future__ import annotations

import time

from lod_auditor import audit_assets


def _make_assets(n: int) -> list[dict]:
    """A mixed batch where a deterministic fraction trips rules, so Finding
    construction (the real cost) is exercised — not just the routing fast-path."""
    assets: list[dict] = []
    for i in range(n):
        bucket = i % 10
        if bucket < 5:
            assets.append(
                {
                    "asset_path": f"/Game/Meshes/Mesh_{i}",
                    "asset_type": "StaticMesh",
                    "lod_count": 1,
                    "lods": [{"index": 0, "triangles": 90000, "screen_size": 1.0}],
                    "bounds_radius": 40.0,
                    "content_hash": f"hash_{i // 2}",  # pairs collide → LX003
                    "size_kb": 512.0,
                }
            )
        elif bucket < 8:
            assets.append(
                {
                    "asset_path": f"/Game/Textures/Tex_{i}",
                    "asset_type": "Texture2D",
                    "width": 4096,
                    "height": 4096,
                    "compression": "RGBA8",
                    "mips_enabled": True,
                    "referenced_by_materials": 0 if i % 5 == 0 else 3,
                }
            )
        else:
            assets.append(
                {
                    "asset_path": f"/Game/Materials/Mat_{i}",
                    "asset_type": "Material",
                    "used_by_primitives": 0 if i % 4 == 0 else 2,
                    "sampler_count": 6,
                    "instruction_count": 200,
                }
            )
    return assets


def _best_per_asset(n: int, repeat: int = 3) -> float:
    """Best-of-`repeat` wall time per asset for an n-asset batch."""
    assets = _make_assets(n)
    times = []
    for _ in range(repeat):
        start = time.perf_counter()
        audit_assets(assets, engine="unreal")
        times.append(time.perf_counter() - start)
    return min(times) / n


class TestLodPerformance:
    def test_engine_scales_linearly(self):
        small = _best_per_asset(1000)
        big = _best_per_asset(8000)
        # Linear ~1x; allow 4x slack for GC/jitter at small n. Quadratic
        # would be ~8x and trip this immediately.
        assert big < small * 4, (
            f"per-asset cost grew {big / small:.1f}x from 1k to 8k assets "
            "— suspect a super-linear (O(n^2)) rule"
        )

    def test_large_batch_completes_quickly(self):
        # Smoke ceiling: even a generous CI runner audits 8k assets well
        # under a second; 5s is a catastrophic-regression tripwire.
        assets = _make_assets(8000)
        start = time.perf_counter()
        resp = audit_assets(assets, engine="unreal")
        elapsed = time.perf_counter() - start
        assert resp.summary.assets_audited == 8000
        assert resp.summary.issues_found > 0
        assert elapsed < 5.0, f"8k-asset audit took {elapsed:.2f}s (>5s ceiling)"
