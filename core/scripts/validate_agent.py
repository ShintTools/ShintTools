#!/usr/bin/env python3
"""
core/scripts/validate_agent.py

Sprint C end-to-end validation: tests /agent/plan and /agent/review
against a live Core engine running in Docker.

Standalone script — requires: httpx, requests (pip install httpx requests)

Usage:
  python validate_agent.py [--docker-compose-file <path>] [--timeout 60]

Output: JSON report to stdout with timing, issues found, and pass/fail.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:
    print(
        "ERROR: httpx not installed. Run: pip install httpx requests",
        file=sys.stderr,
    )
    sys.exit(1)


# ── Test Code: C++ with Known Issues ──────────────────────────────────────

TEST_CPP_CODE = """
// MyActor.cpp — intentional issues for testing

#include "MyActor.h"

void AMyActor::BeginPlay()
{
    Super::BeginPlay();

    // CS001: GetWorld() can return nullptr
    UWorld* World = GetWorld();
    AActor* Result = World->SpawnActor<AActor>();

    // CP005: Sleep in game thread blocks rendering
    FPlatformProcess::Sleep(0.1f);

    // CS004: Division by zero (will crash if value is 0)
    int32 Divisor = 0;
    int32 Result = 100 / Divisor;
}

void AMyActor::Tick(float DeltaTime)
{
    Super::Tick(DeltaTime);

    // CP003: Large Tick body — should extract to sub-function
    for (int32 i = 0; i < 10000; ++i)
    {
        FVector Pos = GetActorLocation();
        Pos.Z += DeltaTime * 100.0f;
        SetActorLocation(Pos);

        // Nested operations
        if (Pos.Z > 1000.0f)
        {
            Pos.Z = 0.0f;
            SetActorLocation(Pos);
        }
    }
}
"""

KNOWN_ISSUES = {
    "CS001": "GetWorld() nullptr",
    "CP005": "Sleep in game thread",
    "CS004": "Division by zero",
    "CP003": "Large Tick body",
}

CORE_BASE_URL = "http://127.0.0.1:18200"
HEALTH_CHECK_ENDPOINT = f"{CORE_BASE_URL}/health"
PLAN_ENDPOINT = f"{CORE_BASE_URL}/agent/plan"
REVIEW_ENDPOINT = f"{CORE_BASE_URL}/agent/review"


def run_command(cmd: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Run shell command, return (exit_code, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", f"Timeout after {timeout}s"
    except Exception as e:
        return 1, "", str(e)


def wait_for_health(timeout: int = 60) -> bool:
    """Poll /health until Core is ready."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = httpx.get(HEALTH_CHECK_ENDPOINT, timeout=5)
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def validate_plan() -> dict[str, Any]:
    """Test POST /agent/plan with known issues."""
    issues_found: list[str] = []
    result = {
        "name": "agent_plan",
        "passed": False,
        "elapsed_ms": 0.0,
        "issues_found": issues_found,
        "error": None,
    }

    start = time.time()
    try:
        # First, validate the code to get issues
        validate_resp = httpx.post(
            f"{CORE_BASE_URL}/validate/code",
            json={
                "file_path": "MyActor.cpp",
                "content": TEST_CPP_CODE,
                "engine": "ue5",
            },
            timeout=30,
        )

        if validate_resp.status_code != 200:
            result["error"] = f"Validate failed: {validate_resp.status_code}"
            return result

        validate_data = validate_resp.json()
        issues = validate_data.get("issues", [])

        # Now call /agent/plan with detected issues
        plan_payload = {
            "api_key": "",
            "issues": issues,
            "max_steps": 10,
        }

        plan_resp = httpx.post(PLAN_ENDPOINT, json=plan_payload, timeout=30)
        elapsed = (time.time() - start) * 1000

        if plan_resp.status_code != 200:
            result["error"] = f"Plan returned {plan_resp.status_code}"
            return result

        plan_data = plan_resp.json()
        result["passed"] = plan_data.get("success", False)
        result["elapsed_ms"] = elapsed

        # Extract found issue rule IDs
        for step in plan_data.get("steps", []):
            rule_id = step.get("rule_id", "")
            if rule_id:
                issues_found.append(rule_id)

    except Exception as e:
        result["error"] = str(e)

    return result


def validate_review() -> dict[str, Any]:
    """Test POST /agent/review (SSE stream) with same code."""
    result = {
        "name": "agent_review",
        "passed": False,
        "elapsed_ms": 0.0,
        "events_received": 0,
        "event_kinds": {},
        "final_answer_preview": "",
        "error": None,
    }

    start = time.time()
    try:
        # Validate first to get issues
        validate_resp = httpx.post(
            f"{CORE_BASE_URL}/validate/code",
            json={
                "file_path": "MyActor.cpp",
                "content": TEST_CPP_CODE,
                "engine": "ue5",
            },
            timeout=30,
        )

        if validate_resp.status_code != 200:
            result["error"] = f"Validate failed: {validate_resp.status_code}"
            return result

        validate_data = validate_resp.json()
        issues = validate_data.get("issues", [])

        # Call /agent/review with SSE streaming
        review_payload = {
            "api_key": "",
            "file_path": "MyActor.cpp",
            "file_content": TEST_CPP_CODE,
            "issues": issues,
            "max_iterations": 8,
        }

        event_count = 0
        event_kinds_count: dict[str, int] = {}
        final_answer = ""

        with httpx.stream(
            "POST", REVIEW_ENDPOINT, json=review_payload, timeout=60
        ) as resp:
            if resp.status_code != 200:
                result["error"] = f"Review returned {resp.status_code}"
                return result

            # Parse SSE stream
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    try:
                        event_json = json.loads(line[6:])  # Strip "data: "
                        event_count += 1
                        kind = event_json.get("kind", "unknown")
                        event_kinds_count[kind] = event_kinds_count.get(kind, 0) + 1

                        if kind == "done":
                            final_answer = event_json.get("payload", "")[:200]

                    except json.JSONDecodeError:
                        pass

        elapsed = (time.time() - start) * 1000

        result["passed"] = event_count > 0 and "done" in event_kinds_count
        result["elapsed_ms"] = elapsed
        result["events_received"] = event_count
        result["event_kinds"] = event_kinds_count
        result["final_answer_preview"] = final_answer

    except Exception as e:
        result["error"] = str(e)

    return result


def validate_latencies(
    plan_result: dict[str, Any], review_result: dict[str, Any]
) -> dict[str, Any]:
    """Check latencies against baselines."""
    measurements: dict[str, float] = {}
    warnings: list[str] = []
    result = {
        "name": "latency_check",
        "passed": True,
        "baselines": {
            "plan_ms": 100,
            "review_s": 10,
        },
        "measurements": measurements,
        "warnings": warnings,
    }

    plan_ms = plan_result.get("elapsed_ms", float("inf"))
    review_ms = review_result.get("elapsed_ms", float("inf"))

    measurements["plan_ms"] = round(plan_ms, 2)
    measurements["review_ms"] = round(review_ms, 2)

    if plan_ms > 100:
        warnings.append(f"Plan slower than baseline: {plan_ms:.0f}ms > 100ms")

    if review_ms > 10000:  # 10 seconds
        warnings.append(f"Review slower than baseline: {review_ms:.0f}ms > 10000ms")

    result["passed"] = len(warnings) == 0

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Sprint C end-to-end validation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python validate_agent.py
  python validate_agent.py --docker-compose-file docker-compose.yml
  python validate_agent.py --timeout 120
        """,
    )
    parser.add_argument(
        "--docker-compose-file",
        default="docker-compose.yml",
        help="Path to docker-compose file (default: docker-compose.yml)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Timeout waiting for Core to be ready (seconds)",
    )
    args = parser.parse_args()

    print("=== Sprint C End-to-End Validation ===\n")

    # Check if Core is already running
    print("[1/5] Checking if Core is running...", end=" ", flush=True)
    if wait_for_health(timeout=5):
        print("OK (already running)")
    else:
        print("\nCore not ready. Attempting to start with docker-compose...")
        compose_file = Path(args.docker_compose_file)
        if not compose_file.exists():
            msg = (
                f"ERROR: {compose_file} not found. "
                "Please start Core manually or provide --docker-compose-file"
            )
            print(msg, file=sys.stderr)
            sys.exit(1)

        print("[1/5] Starting docker-compose...", end=" ", flush=True)
        exit_code, stdout, stderr = run_command(
            ["docker-compose", "-f", str(compose_file), "up", "-d"],
            timeout=30,
        )
        if exit_code != 0:
            print(f"FAILED\nError: {stderr}", file=sys.stderr)
            sys.exit(1)
        print("OK")

        print("[2/5] Waiting for Core to be ready...", end=" ", flush=True)
        if not wait_for_health(timeout=args.timeout):
            print(f"TIMEOUT (waited {args.timeout}s)", file=sys.stderr)
            sys.exit(1)
        print("OK")

    # Run tests
    print("[3/5] Testing /agent/plan...", end=" ", flush=True)
    plan_result = validate_plan()
    status = "PASS" if plan_result["passed"] else "FAIL"
    print(f"{status} ({plan_result['elapsed_ms']:.0f}ms)")
    if plan_result["error"]:
        print(f"      Error: {plan_result['error']}")

    print("[4/5] Testing /agent/review (SSE)...", end=" ", flush=True)
    review_result = validate_review()
    status = "PASS" if review_result["passed"] else "FAIL"
    elapsed_ms = review_result["elapsed_ms"]
    events_count = review_result["events_received"]
    print(f"{status} ({elapsed_ms:.0f}ms, {events_count} events)")
    if review_result["error"]:
        print(f"      Error: {review_result['error']}")

    print("[5/5] Checking latencies...", end=" ", flush=True)
    latency_result = validate_latencies(plan_result, review_result)
    status = "PASS" if latency_result["passed"] else "WARN"
    print(status)
    for warning in latency_result["warnings"]:
        print(f"      Warning: {warning}")

    # Generate report
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {
            "plan": "PASS" if plan_result["passed"] else "FAIL",
            "review": "PASS" if review_result["passed"] else "FAIL",
            "latencies": "PASS" if latency_result["passed"] else "WARN",
            "overall": (
                "PASS"
                if (
                    plan_result["passed"]
                    and review_result["passed"]
                    and latency_result["passed"]
                )
                else "FAIL"
            ),
        },
        "plan": plan_result,
        "review": review_result,
        "latencies": latency_result,
        "known_issues": KNOWN_ISSUES,
    }

    print("\n=== Report (JSON) ===\n")
    print(json.dumps(report, indent=2))

    sys.exit(0 if report["summary"]["overall"] == "PASS" else 1)


if __name__ == "__main__":
    main()
