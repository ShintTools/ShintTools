# core/tests/performance/bench_core.py
#
# ShintTools Core Engine — Performance Benchmark
#
# Measures response time and throughput for the three
# main endpoints against the MVP acceptance criterion:
#
#   "A full analysis of 500 assets + 10,000 lines of code
#    must complete in under 3 minutes."
#   — ShintTools Tech Doc, Section 15, Criterion 4
#
# Usage (from core/ directory):
#   python tests/performance/bench_core.py
#   python tests/performance/bench_core.py --url http://localhost:18200
#   python tests/performance/bench_core.py --scale large
#
# Scales:
#   small  — 50 assets, 500 lines  (quick sanity check)
#   medium — 200 assets, 5000 lines (default)
#   large  — 500 assets, 10000 lines (MVP acceptance target)

import argparse
import statistics
import time
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_URL = "http://localhost:18200"

SCALES: dict[str, dict[str, int]] = {
    "small": {"assets": 50, "cpp_lines": 500, "blueprints": 5},
    "medium": {"assets": 200, "cpp_lines": 5000, "blueprints": 20},
    "large": {"assets": 500, "cpp_lines": 10000, "blueprints": 50},
}

# MVP acceptance threshold — 3 minutes total
MVP_THRESHOLD_SECONDS: float = 180.0

# Single-request latency warning threshold
LATENCY_WARNING_MS: float = 5000.0

# ---------------------------------------------------------------------------
# Synthetic data generators
# ---------------------------------------------------------------------------


def _generate_asset_paths(count: int) -> list[dict[str, str]]:
    """Generate synthetic asset entries matching the plugin payload."""
    asset_types = [
        ("Textures", "HeroTexture", "Texture2D"),
        ("Meshes", "RockMesh", "StaticMesh"),
        ("Materials", "StoneMaterial", "Material"),
        ("Blueprints", "PlayerActor", "Blueprint"),
        ("Sounds", "ExplosionSound", "SoundCue"),
        ("Animations", "RunAnimation", "AnimSequence"),
        ("Widgets", "MainMenu", "WidgetBlueprint"),
        ("DataTables", "ItemTable", "DataTable"),
    ]
    assets = []
    for idx in range(count):
        folder, name, asset_type = asset_types[idx % len(asset_types)]
        # Alternate between correct and incorrect names
        # to generate a realistic mix of issues
        asset_name = name if idx % 3 == 0 else name.lower()
        assets.append(
            {
                "asset_path": f"/Game/{folder}/{asset_name}_{idx}",
                "name": f"{asset_name}_{idx}",
                "type": asset_type,
                "category": "",
            }
        )
    return assets


def _generate_cpp_content(total_lines: int) -> str:
    """Generate synthetic C++ content with intentional issues."""
    lines_per_block = 20
    blocks_needed = total_lines // lines_per_block

    cpp_blocks = []
    cpp_blocks.append("#include <iostream>")
    cpp_blocks.append('#include "MyActor.h"')
    cpp_blocks.append("")

    for block_idx in range(blocks_needed):
        cpp_blocks += [
            f"void AMyActor::Function{block_idx}(float DeltaTime)",
            "{",
            "    Super::Tick(DeltaTime);",
            "    UStaticMeshComponent* Mesh = "
            "GetComponentByClass<UStaticMeshComponent>();",
            "    GEngine->AddOnScreenDebugMessage("
            '-1, 5.f, FColor::Red, TEXT("debug"));',
            f"    float Speed = 3.14f * {200 + block_idx};",
            f"    int32 RawArr[{10 + block_idx % 5}];",
            "    AActor* Other = nullptr;",
            "    Other->GetName();",
            f"    // TODO: fix this function {block_idx}",
            '    printf("hello");',
            f"    int32* Ptr = new int32({block_idx});",
            "    if (Health > 0)",
            "    {",
            "    }",
            "    FPlatformProcess::Sleep(0.1f);",
            f"    float Ratio = Health / {block_idx + 1}.0f;",
            "    auto Val = GetActorLocation();",
            "    delete Ptr;",
            "}",
            "",
        ]

    return "\n".join(cpp_blocks[:total_lines])


def _generate_blueprint_files(count: int) -> list[dict[str, Any]]:
    """Generate synthetic Blueprint export dicts."""
    blueprints = []
    for bp_idx in range(count):
        blueprints.append(
            {
                "name": f"BP_Actor_{bp_idx}" if bp_idx % 2 == 0 else f"Actor_{bp_idx}",
                "path": f"/Game/Blueprints/BP_Actor_{bp_idx}",
                "type": "blueprint",
                "graphs": [
                    {
                        "name": "EventGraph",
                        "type": "event_graph",
                        "nodes_count": 120 + bp_idx % 50,
                        "nodes": [
                            {
                                "type": "CastTo",
                                "target": "BP_Enemy",
                                "count": 12 + bp_idx % 5,
                            }
                        ],
                    }
                ],
                "variables": [
                    {
                        "name": f"UnusedVar_{bp_idx}",
                        "type": "Float",
                        "used": bp_idx % 3 != 0,
                    }
                ],
                "functions": [
                    {
                        "name": "HandleLogic",
                        "complexity": 15 + bp_idx % 8,
                    }
                ],
                "stats": {
                    "total_nodes": 220 + bp_idx % 80,
                    "cast_nodes": 12,
                    "tick_enabled": bp_idx % 2 == 0,
                    "disconnected_nodes": bp_idx % 4,
                },
            }
        )
    return blueprints


# ---------------------------------------------------------------------------
# Benchmark runners
# ---------------------------------------------------------------------------


def _run_assets_benchmark(
    client: httpx.Client,
    base_url: str,
    asset_count: int,
) -> dict[str, Any]:
    """Benchmark POST /assets/scan."""
    payload = {
        "project_id": "bench",
        "project_name": "BenchmarkProject",
        "engine": "unreal",
        "asset_paths": _generate_asset_paths(asset_count),
    }

    start = time.perf_counter()
    response = client.post(f"{base_url}/assets/scan", json=payload)
    elapsed_ms = (time.perf_counter() - start) * 1000

    response.raise_for_status()
    data = response.json()

    return {
        "endpoint": "/assets/scan",
        "assets_sent": asset_count,
        "issues_found": data["summary"]["invalid_assets"],
        "elapsed_ms": round(elapsed_ms, 2),
    }


def _run_code_benchmark(
    client: httpx.Client,
    base_url: str,
    total_lines: int,
    chunk_size: int = 500,
) -> dict[str, Any]:
    """
    Benchmark POST /validate/code by sending the full content
    in chunks of chunk_size lines — simulates project scan
    where each file is sent individually.
    """
    cpp_content = _generate_cpp_content(total_lines)
    all_lines = cpp_content.splitlines()
    chunks = [
        "\n".join(all_lines[i : i + chunk_size])
        for i in range(0, len(all_lines), chunk_size)
    ]

    total_issues = 0
    elapsed_times: list[float] = []

    for chunk_idx, chunk_content in enumerate(chunks):
        payload = {
            "file_path": f"Benchmark/Actor_{chunk_idx}.cpp",
            "engine": "unreal",
            "content": chunk_content,
        }
        start = time.perf_counter()
        response = client.post(f"{base_url}/validate/code", json=payload)
        elapsed_ms = (time.perf_counter() - start) * 1000
        response.raise_for_status()
        data = response.json()
        total_issues += data["summary"]["total"]
        elapsed_times.append(elapsed_ms)

    return {
        "endpoint": "/validate/code",
        "total_lines": total_lines,
        "files_sent": len(chunks),
        "issues_found": total_issues,
        "total_elapsed_ms": round(sum(elapsed_times), 2),
        "avg_ms_per_file": round(statistics.mean(elapsed_times), 2),
        "max_ms_per_file": round(max(elapsed_times), 2),
    }


def _run_blueprints_benchmark(
    client: httpx.Client,
    base_url: str,
    blueprint_count: int,
) -> dict[str, Any]:
    """Benchmark POST /validate/blueprints."""
    payload = {
        "project_id": "bench",
        "project_name": "BenchmarkProject",
        "engine": "unreal",
        "files": _generate_blueprint_files(blueprint_count),
    }

    start = time.perf_counter()
    response = client.post(f"{base_url}/validate/blueprints", json=payload)
    elapsed_ms = (time.perf_counter() - start) * 1000

    response.raise_for_status()
    data = response.json()

    return {
        "endpoint": "/validate/blueprints",
        "blueprints_sent": blueprint_count,
        "issues_found": data["summary"]["total"],
        "elapsed_ms": round(elapsed_ms, 2),
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _print_result(result: dict[str, Any]) -> None:
    endpoint = result["endpoint"]
    elapsed = result.get("elapsed_ms") or result.get("total_elapsed_ms", 0)
    issues = result["issues_found"]
    warning = " ⚠️  SLOW" if elapsed > LATENCY_WARNING_MS else ""

    print(f"\n  {endpoint}")
    print(f"    Issues found : {issues}")

    if "assets_sent" in result:
        print(f"    Assets sent  : {result['assets_sent']}")
    if "total_lines" in result:
        print(f"    Lines sent   : {result['total_lines']}")
        print(f"    Files sent   : {result['files_sent']}")
        print(f"    Avg/file     : {result['avg_ms_per_file']} ms")
        print(f"    Max/file     : {result['max_ms_per_file']} ms")
    if "blueprints_sent" in result:
        print(f"    Blueprints   : {result['blueprints_sent']}")

    print(f"    Total time   : {elapsed} ms{warning}")


def _print_summary(
    results: list[dict[str, Any]],
    scale: str,
    total_elapsed_s: float,
) -> None:
    print("\n" + "=" * 55)
    print(f"  BENCHMARK SUMMARY — scale: {scale.upper()}")
    print("=" * 55)

    passed = total_elapsed_s <= MVP_THRESHOLD_SECONDS
    status = "✅ PASS" if passed else "❌ FAIL"

    print(
        f"  Total elapsed : {total_elapsed_s:.2f}s "
        f"(threshold: {MVP_THRESHOLD_SECONDS:.0f}s)"
    )
    print(f"  MVP criterion : {status}")
    print("=" * 55)

    if not passed:
        over = total_elapsed_s - MVP_THRESHOLD_SECONDS
        print(
            f"\n  ⚠️  {over:.1f}s over threshold. "
            "Consider optimising regex patterns or "
            "adding async file processing."
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="ShintTools Core Engine benchmark")
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help="Base URL of the Core Engine",
    )
    parser.add_argument(
        "--scale",
        choices=["small", "medium", "large"],
        default="medium",
        help="Test scale (default: medium)",
    )
    args = parser.parse_args()

    scale_cfg = SCALES[args.scale]
    asset_count = scale_cfg["assets"]
    cpp_lines = scale_cfg["cpp_lines"]
    blueprint_count = scale_cfg["blueprints"]

    print("\nShintTools Performance Benchmark")
    print(f"  URL   : {args.url}")
    print(f"  Scale : {args.scale.upper()}")
    print(
        f"  Load  : {asset_count} assets | "
        f"{cpp_lines} C++ lines | "
        f"{blueprint_count} blueprints"
    )
    print("-" * 55)

    results: list[dict[str, Any]] = []
    total_start = time.perf_counter()

    with httpx.Client(timeout=120.0) as client:
        # Check server is up
        try:
            client.get(f"{args.url}/status")
        except httpx.ConnectError:
            print(f"\n  ❌ Cannot connect to {args.url}. " "Is the server running?")
            return

        print("\nRunning benchmarks...")

        assets_result = _run_assets_benchmark(client, args.url, asset_count)
        results.append(assets_result)
        _print_result(assets_result)

        code_result = _run_code_benchmark(client, args.url, cpp_lines)
        results.append(code_result)
        _print_result(code_result)

        bp_result = _run_blueprints_benchmark(client, args.url, blueprint_count)
        results.append(bp_result)
        _print_result(bp_result)

    total_elapsed_s = time.perf_counter() - total_start
    _print_summary(results, args.scale, total_elapsed_s)


if __name__ == "__main__":
    main()
