# core/tests/performance/bench_predictive.py
#
# Predictive Profiler — end-to-end benchmark over the real client request
# path, plus per-layer in-process isolation.
#
# Two measurement modes:
#
#   HTTP (default)   — POST /predict/analyze (one-shot) and the batched
#                       session flow (/predict/session/start → /ingest →
#                       /analyze) against a live Core, at several project
#                       scales. This is what the Unreal/Unity client
#                       actually experiences.
#
#   --layers          — direct import of layer1_assets.analyze_assets,
#                       layer2_scene.analyze_scenes, layer3_code.analyze_code
#                       (code_issues path) and the full orchestrator
#                       (analyze_oneshot), run in-process so each layer's own
#                       cost is isolated from HTTP/serialization overhead.
#                       Requires running from core/ with modules/ importable
#                       (same sys.path trick api/routes/predictive.py uses).
#
# Usage (from core/):
#   python tests/performance/bench_predictive.py
#   python tests/performance/bench_predictive.py --url http://localhost:18200
#   python tests/performance/bench_predictive.py --layers
#   python tests/performance/bench_predictive.py --repeat 5
#
# What to look for: p50 tells you the typical cost; p95 tells you the tail a
# real project will hit under load; the scale sweep tells you whether cost
# grows linearly (expected — every layer here is a single pass over its
# input) or worse (a bug). A single warm-up iteration per case is discarded
# before both are computed (module imports, lru_cache fills, and Python's
# import machinery skew the very first call).

from __future__ import annotations

import argparse
import statistics
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any

import httpx

DEFAULT_URL = "http://localhost:18200"
DEFAULT_KEY = "sk_bench_studio"

# Project scales to sweep — asset counts a real Unreal project's LOD-audit
# collector would report, from "small indie" to "AA scale". 10k+ is the
# regime session batching exists for.
SCALES: list[int] = [100, 1000, 10000]

# Client's session batch size (LOD-audit precedent, see session_store.py).
SESSION_BATCH = 150


# ---------------------------------------------------------------------------
# Synthetic data generators — same asset shape the LOD Auditor / plugin
# collector sends (asset_costs.py dispatches on asset_type + width/height or
# vertex_count).
# ---------------------------------------------------------------------------


def _make_assets(n: int, offset: int = 0) -> list[dict[str, Any]]:
    out = []
    for i in range(offset, offset + n):
        if i % 2 == 0:
            out.append({
                "asset_path": f"/Game/Textures/T_Rock_{i}",
                "asset_type": "Texture2D",
                "width": 2048,
                "height": 2048,
                "compression": "BC7",
                "mips_enabled": True,
                "streaming": True,
                "lod_group": "World",
            })
        else:
            out.append({
                "asset_path": f"/Game/Meshes/SM_Rock_{i}",
                "asset_type": "StaticMesh",
                "vertex_count": 15000,
            })
    return out


def _make_scenes(n: int) -> list[dict[str, Any]]:
    out = []
    for i in range(n):
        out.append({
            "scene_name": f"Level_{i}",
            "scene_path": f"/Game/Maps/Level_{i}",
            "actor_count": 500,
            "ticking_actors": 40,
            "ticking_blueprints": 15,
            "skeletal_meshes": 8,
            "lights": [
                {"type": "Point", "mobility": "Movable", "casts_shadows": True,
                 "radius": 1200},
                {"type": "Spot", "mobility": "Static", "casts_shadows": False,
                 "radius": 800},
            ],
            "particle_systems": [{"emitters": 3, "sim_target": "GPU"}],
        })
    return out


def _make_code_issues(n: int) -> list[dict[str, Any]]:
    out = []
    for i in range(n):
        out.append({
            "rule_id": "CP002",
            "rule_name": "GetComponent in Tick",
            "file": f"Source/Actor{i}.cpp",
            "line": (i % 400) + 1,
            "severity": "warning",
            "auto_fixable": False,
        })
    return out


# ---------------------------------------------------------------------------
# HTTP benchmarks
# ---------------------------------------------------------------------------


def _timed_post(
    client: httpx.Client, url: str, path: str, body: dict[str, Any]
) -> tuple[float, httpx.Response]:
    t0 = time.perf_counter()
    resp = client.post(url + path, json=body, timeout=120.0)
    return (time.perf_counter() - t0) * 1000, resp


def bench_http_oneshot(
    client: httpx.Client, url: str, api_key: str, repeat: int
) -> list[dict[str, Any]]:
    rows = []
    for n in SCALES:
        body = {
            "api_key": api_key, "engine": "UE5", "project_name": "bench",
            "platform_profile": "desktop_60", "assets": _make_assets(n),
        }
        _timed_post(client, url, "/predict/analyze", body)  # warm-up
        samples = []
        status = None
        payload_bytes = 0
        for _ in range(repeat):
            ms, resp = _timed_post(client, url, "/predict/analyze", body)
            status = resp.status_code
            payload_bytes = len(resp.content)
            if status == 200:
                samples.append(ms)
        rows.append({
            "case": f"POST /predict/analyze one-shot ({n} assets)",
            "n": n,
            "status": status,
            "p50_ms": statistics.median(samples) if samples else None,
            "p95_ms": (
                statistics.quantiles(samples, n=20)[18]
                if len(samples) >= 5
                else (max(samples) if samples else None)
            ),
            "resp_kb": round(payload_bytes / 1024, 1),
        })
    return rows


def bench_http_session(
    client: httpx.Client, url: str, api_key: str, n: int
) -> dict[str, Any]:
    """The real client flow for big projects: batched ingest then analyze."""
    r = client.post(url + "/predict/session/start", json={
        "api_key": api_key, "engine": "UE5", "project_name": "bench-session",
        "platform_profile": "desktop_60",
    })
    r.raise_for_status()
    session_id = r.json()["session_id"]

    assets = _make_assets(n)
    t0 = time.perf_counter()
    for i in range(0, n, SESSION_BATCH):
        batch = assets[i:i + SESSION_BATCH]
        r = client.post(url + "/predict/session/ingest", json={
            "api_key": api_key, "session_id": session_id, "kind": "assets",
            "payload": {"assets": batch},
        }, timeout=60.0)
        r.raise_for_status()
    ingest_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    r = client.post(url + "/predict/analyze", json={
        "api_key": api_key, "session_id": session_id,
    }, timeout=120.0)
    analyze_ms = (time.perf_counter() - t0) * 1000
    r.raise_for_status()
    stats = r.json().get("stats", {})

    return {
        "case": f"session flow ({n} assets, {SESSION_BATCH}/batch)",
        "n": n,
        "batches": (n + SESSION_BATCH - 1) // SESSION_BATCH,
        "ingest_total_ms": round(ingest_ms, 1),
        "analyze_ms": round(analyze_ms, 1),
        "assets_analyzed": stats.get("assets_analyzed"),
    }


def bench_http_profiles(client: httpx.Client, url: str, api_key: str,
                        repeat: int) -> dict[str, Any]:
    samples = []
    client.get(url + "/predict/profiles", params={"api_key": api_key})
    for _ in range(repeat):
        t0 = time.perf_counter()
        r = client.get(url + "/predict/profiles", params={"api_key": api_key})
        samples.append((time.perf_counter() - t0) * 1000)
        r.raise_for_status()
    return {
        "case": "GET /predict/profiles",
        "p50_ms": round(statistics.median(samples), 2),
        "p95_ms": round(max(samples), 2),
    }


def bench_event_loop_health(
    client: httpx.Client, url: str, api_key: str
) -> dict[str, Any]:
    """/health latency while a big analyze is in flight — the event-loop
    starvation check (see 2026-08-19 fix in api/routes/predictive.py)."""
    import concurrent.futures

    body = {"api_key": api_key, "assets": _make_assets(15000)}

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        analyze_future = pool.submit(
            lambda: client.post(url + "/predict/analyze", json=body, timeout=60.0)
        )
        pings = []
        while not analyze_future.done():
            t0 = time.perf_counter()
            try:
                client.get(url + "/health", timeout=5.0)
            except httpx.HTTPError:
                continue
            pings.append((time.perf_counter() - t0) * 1000)
            time.sleep(0.05)
        analyze_future.result()

    if not pings:
        return {"case": "/health during 15k-asset analyze", "p50_ms": None,
                "max_ms": None, "samples": 0}
    return {
        "case": "/health during 15k-asset analyze",
        "p50_ms": round(statistics.median(pings), 1),
        "max_ms": round(max(pings), 1),
        "samples": len(pings),
    }


# ---------------------------------------------------------------------------
# Direct-import layer isolation (no HTTP/serialization overhead)
# ---------------------------------------------------------------------------


def bench_layers(repeat: int) -> list[dict[str, Any]]:
    core_dir = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(core_dir))
    sys.path.insert(0, str(core_dir / "modules"))

    from predictive.layers import layer1_assets, layer2_scene, layer3_code
    from predictive.predictive_orchestrator import analyze_oneshot
    from predictive.schema import AnalyzeRequest

    rows: list[dict[str, Any]] = []

    # Warm-up: lru_cache (rule_costs.yaml, platform_*.yaml) + import cost.
    layer1_assets.analyze_assets(_make_assets(20), engine="UE5", profile="default")
    layer2_scene.analyze_scenes(_make_scenes(2))
    layer3_code.analyze_code(_make_code_issues(20))
    analyze_oneshot(AnalyzeRequest(assets=_make_assets(20)))

    for n in SCALES:
        assets = _make_assets(n)

        def _run_l1():
            return layer1_assets.analyze_assets(
                assets, engine="UE5", profile="default"
            )

        samples = [_time_ms(_run_l1) for _ in range(repeat)]
        rows.append({
            "case": f"layer1_assets.analyze_assets ({n} assets)",
            "p50_ms": round(statistics.median(samples), 2),
            "p95_ms": round(max(samples), 2),
        })

    for n in (10, 100, 500):
        scenes = _make_scenes(n)

        def _run_l2():
            return layer2_scene.analyze_scenes(scenes)

        samples = [_time_ms(_run_l2) for _ in range(repeat)]
        rows.append({
            "case": f"layer2_scene.analyze_scenes ({n} scenes)",
            "p50_ms": round(statistics.median(samples), 2),
            "p95_ms": round(max(samples), 2),
        })

    for n in SCALES:
        issues = _make_code_issues(n)

        def _run_l3():
            return layer3_code.analyze_code(issues)

        samples = [_time_ms(_run_l3) for _ in range(repeat)]
        rows.append({
            "case": f"layer3_code.analyze_code ({n} issues)",
            "p50_ms": round(statistics.median(samples), 2),
            "p95_ms": round(max(samples), 2),
        })

    for n in SCALES:
        assets = _make_assets(n)
        req = AnalyzeRequest(engine="UE5", assets=assets)

        def _run_orch():
            return analyze_oneshot(req)

        tracemalloc.start()
        samples = [_time_ms(_run_orch) for _ in range(repeat)]
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        rows.append({
            "case": f"analyze_oneshot full orchestrator ({n} assets)",
            "p50_ms": round(statistics.median(samples), 2),
            "p95_ms": round(max(samples), 2),
            "peak_mb": round(peak / 1e6, 1),
        })

    return rows


def _time_ms(fn) -> float:
    t0 = time.perf_counter()
    fn()
    return (time.perf_counter() - t0) * 1000


def _print_rows(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        case = row.pop("case")
        detail = "  ".join(
            f"{k}={v}" for k, v in row.items() if v is not None
        )
        print(f"  {case:<52} {detail}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ShintTools Predictive Profiler benchmark"
    )
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--api-key", default=DEFAULT_KEY)
    parser.add_argument("--repeat", type=int, default=5,
                        help="timed iterations per case (default 5, "
                        "+1 warm-up discarded)")
    parser.add_argument("--layers", action="store_true",
                        help="run the direct-import per-layer benchmark "
                        "instead of the HTTP end-to-end benchmark")
    parser.add_argument("--skip-event-loop-check", action="store_true")
    args = parser.parse_args()

    print("\nShintTools Predictive Profiler — benchmark")
    print("  Mode    : " + ("direct-import layers" if args.layers else "HTTP"))

    if args.layers:
        rows = bench_layers(args.repeat)
        print("-" * 74)
        _print_rows(rows)
        return 0

    with httpx.Client() as client:
        health = client.get(args.url + "/health", timeout=10.0).json()
        print("  URL     : " + args.url)
        print("  Version : {} ({})".format(
            health.get("version"), health.get("edition")))
        print("  Repeat  : {} timed iterations (+1 warm-up)".format(
            args.repeat))
        print("-" * 74)

        _print_rows(
            [bench_http_profiles(client, args.url, args.api_key, args.repeat)]
        )
        print()
        _print_rows(
            bench_http_oneshot(client, args.url, args.api_key, args.repeat)
        )
        print()
        for n in (1500,):
            _print_rows(
                [bench_http_session(client, args.url, args.api_key, n)]
            )
        print()

        if not args.skip_event_loop_check:
            _print_rows(
                [bench_event_loop_health(client, args.url, args.api_key)]
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
