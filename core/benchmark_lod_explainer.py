#!/usr/bin/env python3
"""
Benchmark: LOD Auditor + LLM Explainer integration.

Measures:
  - Time to load model
  - Time per explanation (with cache hits)
  - Quality of explanations (visual inspection)
  - MongoDB cache hit rate (if available)

Run with: SHINTTOOLS_AGENT_ENABLED=1 python benchmark_lod_explainer.py
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "modules"))

from agent.explainer import explain_issue
from agent.llm_backend import load_model
from lod_auditor.schema import Finding, Saving

# Synthetic LOD audit findings
FINDINGS = [
    Finding(
        asset_path="Assets/Textures/T_Hero_Diffuse.png",
        rule_id="LT001",
        category="Texture",
        severity="warning",
        message="Compression format BC4 not optimal for BaseColor usage (expected BC7)",
        current={"compression": "BC4"},
        recommended={"compression": "BC7"},
        estimated_saving=Saving(vram_mb=0.25),
        auto_fixable=True,
    ),
    Finding(
        asset_path="Assets/Textures/T_World_Diffuse.png",
        rule_id="LT003",
        category="Texture",
        severity="warning",
        message="Texture resolution 4096x4096 exceeds LOD group maximum 2048",
        current={"resolution": [4096, 4096], "lod_group": "World"},
        recommended={"resolution": [2048, 2048]},
        estimated_saving=Saving(vram_mb=6.0),
        auto_fixable=True,
    ),
    Finding(
        asset_path="Assets/Textures/T_Normal_Map.png",
        rule_id="LT001",
        category="Texture",
        severity="warning",
        message="Compression format BC7 not optimal for Normal usage (expected BC5)",
        current={"compression": "BC7"},
        recommended={"compression": "BC5"},
        estimated_saving=Saving(vram_mb=0.5),
        auto_fixable=True,
    ),
]


def build_issue_dict(finding: Finding, rule_explanation: str) -> dict:
    """Convert Finding to issue_dict format expected by explainer."""
    return {
        "rule_id": finding.rule_id,
        "rule_name": f"{finding.rule_id} — {finding.message[:60]}",
        "rule_explanation": rule_explanation,
        "asset_path": finding.asset_path,
        "message": finding.message,
        "severity": finding.severity,
        "is_auto_fixable": finding.auto_fixable,
        "snippet": f"Asset: {finding.asset_path}\nCurrent: {finding.current}\nRecommended: {finding.recommended}",
    }


def main():
    print("\n" + "=" * 80)
    print("LOD AUDITOR + LLM EXPLAINER BENCHMARK")
    print("=" * 80)

    if os.getenv("SHINTTOOLS_AGENT_ENABLED") != "1":
        print("\nERROR: Set SHINTTOOLS_AGENT_ENABLED=1")
        return

    print("\n[1/3] Loading model...")
    t_load_start = time.perf_counter()
    try:
        load_model()
    except RuntimeError as e:
        print(f"ERROR: {e}\n")
        return
    t_load = time.perf_counter() - t_load_start
    print(f"[OK] Model loaded in {t_load:.2f}s\n")

    # Explanations for each rule
    RULE_EXPLANATIONS = {
        "LT001": (
            "Textures must use compression formats matched to their perceptual role. "
            "BaseColor and HDR require BC7 (10bpc) for quality; Normal requires BC5 (RG only); "
            "Mask/Data require BC4 (single channel). Wrong format wastes VRAM and/or image quality."
        ),
        "LT003": (
            "Each LOD group has a maximum resolution to keep memory budgets and streaming stable. "
            "Character textures cap at 2048; World at 2048; Terrain and Cinematic at 4096; "
            "Effects and UI at 1024. Oversized textures waste VRAM and don't improve visuals."
        ),
    }

    print("[2/3] Generating explanations...\n")
    explanations = []
    times = []

    for i, finding in enumerate(FINDINGS, 1):
        issue_dict = build_issue_dict(
            finding, RULE_EXPLANATIONS.get(finding.rule_id, "Unknown rule")
        )

        print(f"[{i}/{len(FINDINGS)}] {finding.asset_path}")
        print(f"     Rule: {finding.rule_id}")
        print(f"     Issue: {finding.message}")

        t0 = time.perf_counter()
        try:
            explanation = explain_issue(issue_dict)
            elapsed = time.perf_counter() - t0
            times.append(elapsed)

            print(f"     Time: {elapsed:.2f}s")
            print(f"     Explanation:\n     {explanation}\n")
            explanations.append(explanation)

        except Exception as e:
            print(f"     ERROR: {e}\n")
            explanations.append(None)

    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)

    successful = sum(1 for e in explanations if e is not None)
    print(f"\nGenerated: {successful}/{len(FINDINGS)} explanations")
    print(f"Success rate: {successful / len(FINDINGS) * 100:.0f}%")

    if times:
        print(f"\nTiming (successful explanations only):")
        print(f"  Min: {min(times):.2f}s")
        print(f"  Max: {max(times):.2f}s")
        print(f"  Avg: {sum(times) / len(times):.2f}s")
        print(f"  Total: {sum(times):.2f}s")

    print(f"\nModel load time: {t_load:.2f}s")
    print(f"Total time (including model load): {t_load + sum(times):.2f}s")

    print("\n" + "=" * 80)
    print("QUALITY ASSESSMENT")
    print("=" * 80)

    print("\nExplanations generated (visual inspection):\n")
    for i, (finding, explanation) in enumerate(zip(FINDINGS, explanations), 1):
        print(f"[{i}] {finding.rule_id} — {finding.asset_path}")
        if explanation:
            print(f"    {explanation}\n")
        else:
            print(f"    (Failed to generate)\n")

    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
