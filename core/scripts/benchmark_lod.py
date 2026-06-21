# core/scripts/benchmark_lod.py
#
# Throughput benchmark for the deterministic LOD Auditor engine
# (lod_auditor.audit_assets). Measures the ALWAYS-ON hot path: the ~27
# deterministic rules + the 3 cross-asset detectors over a realistic mixed
# batch. The optional LLM enrichment is deliberately excluded — it is
# bounded, opt-in, and CPU-bound (~30 s/finding), so it measures llama.cpp,
# not this engine.
#
# Run from the repo root:
#   python core/scripts/benchmark_lod.py
#   python core/scripts/benchmark_lod.py --sizes 1000 50000 --repeat 5
#
# What to look for: ms-per-1k-assets should stay roughly FLAT as the batch
# grows. A rising per-asset cost would betray an accidental O(n^2) rule.

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Make `lod_auditor` importable the same way the FastAPI app does.
_CORE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_CORE / "modules"))

from lod_auditor import audit_assets  # noqa: E402


def make_assets(n: int) -> list[dict]:
    """Build a realistic mixed batch of *n* assets.

    ~50% meshes, ~30% textures, ~20% materials. A deterministic fraction of
    each trips at least one rule (so Finding construction — the real cost — is
    exercised), and every 10th mesh shares a content hash to fire LX003.
    """
    assets: list[dict] = []
    for i in range(n):
        bucket = i % 10
        if bucket < 5:  # mesh
            over = i % 3 == 0  # a third are over tri budget → LD003
            assets.append(
                {
                    "asset_path": f"/Game/Meshes/Mesh_{i}",
                    "asset_type": "StaticMesh",
                    "lod_count": 1 if i % 4 else 3,  # some lack a LOD chain → LD001
                    "lods": [
                        {
                            "index": 0,
                            "triangles": 90000 if over else 4000,
                            "screen_size": 1.0,
                        }
                    ],
                    "bounds_radius": 40.0,
                    # Every 10th mesh duplicates the previous one's hash.
                    "content_hash": f"hash_{i // 2}",
                    "size_kb": 512.0,
                }
            )
        elif bucket < 8:  # texture
            assets.append(
                {
                    "asset_path": f"/Game/Textures/Tex_{i}",
                    "asset_type": "Texture2D",
                    "width": 4096,
                    "height": 4096,
                    "compression": "RGBA8",
                    "mips_enabled": i % 2 == 0,
                    # A fifth are never sampled → LX001.
                    "referenced_by_materials": 0 if i % 5 == 0 else 3,
                }
            )
        else:  # material
            assets.append(
                {
                    "asset_path": f"/Game/Materials/Mat_{i}",
                    "asset_type": "Material",
                    # A quarter are unused → LX002.
                    "used_by_primitives": 0 if i % 4 == 0 else 2,
                    "sampler_count": 6,
                    "instruction_count": 200,
                }
            )
    return assets


def _bench_once(assets: list[dict], engine: str) -> tuple[float, int]:
    start = time.perf_counter()
    resp = audit_assets(assets, engine=engine)
    elapsed = time.perf_counter() - start
    return elapsed, resp.summary.issues_found


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark the LOD Auditor engine.")
    parser.add_argument(
        "--sizes", type=int, nargs="+", default=[100, 1000, 5000, 20000],
        help="Asset-batch sizes to time.",
    )
    parser.add_argument("--repeat", type=int, default=3,
                        help="Runs per size; the best (min) time is reported.")
    parser.add_argument("--engine", type=str, default="unreal",
                        choices=["unreal", "unity"])
    args = parser.parse_args()

    print(f"LOD Auditor benchmark - engine={args.engine}, best of {args.repeat}\n")
    header = (
        f"{'assets':>8} {'findings':>9} {'time_ms':>10} "
        f"{'assets/s':>11} {'ms/1k':>8}"
    )
    print(header)
    print("-" * len(header))

    baseline_per_asset: float | None = None
    for n in args.sizes:
        assets = make_assets(n)
        best = min(_bench_once(assets, args.engine)[0] for _ in range(args.repeat))
        _, findings = _bench_once(assets, args.engine)
        per_asset_us = best / n * 1e6
        if baseline_per_asset is None:
            baseline_per_asset = per_asset_us
        print(
            f"{n:>8} {findings:>9} {best * 1e3:>10.2f} "
            f"{n / best:>11,.0f} {best / n * 1e6:>8.2f}"
        )

    # Linear-scaling check: per-asset cost at the largest size shouldn't be
    # wildly higher than at the smallest. >3x would suggest super-linear cost.
    assets_big = make_assets(args.sizes[-1])
    big = min(_bench_once(assets_big, args.engine)[0] for _ in range(args.repeat))
    big_per_asset = big / args.sizes[-1] * 1e6
    ratio = big_per_asset / baseline_per_asset if baseline_per_asset else 0.0
    verdict = "LINEAR (OK)" if ratio < 3.0 else "SUPER-LINEAR (investigate)"
    print(f"\nper-asset cost ratio (largest/smallest): {ratio:.2f}x -> {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
