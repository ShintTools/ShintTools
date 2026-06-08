# core/modules/lod_auditor/lod_report.py
#
# Aggregated reporting helpers for the LOD Auditor.
#
# Two top-level functions consumed by the /assets/lod/report endpoint:
#   * build_folder_summary  — total VRAM/instructions per top-level folder
#   * top_offenders         — N worst assets ranked by potential VRAM saving
#
# Both work off the raw findings list returned by audit_assets() so the
# scan only runs once per request.

from __future__ import annotations

from collections import defaultdict
from typing import Any

from lod_auditor.schema import Finding

_DEFAULT_TOP_N = 10

# Asset paths share a project-root prefix (/Game/ on UE5, Assets/ on
# Unity). We bucket by the segment immediately after that prefix so the
# folder summary stays useful instead of collapsing everything into one.
_PROJECT_PREFIXES: tuple[str, ...] = ("/Game/", "Assets/", "/Content/")


def _bucket_for(asset_path: str) -> str:
    """Return the top-level folder under the engine's project prefix.

    /Game/Characters/Hero/SK_Hero -> Characters
    Assets/Props/Crate.prefab     -> Props
    /Game/T_Sky                   -> <root>  (asset directly under project root)
    """
    for prefix in _PROJECT_PREFIXES:
        if asset_path.startswith(prefix):
            tail = asset_path[len(prefix) :]
            head, sep, _ = tail.partition("/")
            return head if sep else "<root>"
    head, sep, _ = asset_path.lstrip("/").partition("/")
    return head if sep else "<unknown>"


def build_folder_summary(findings: list[Finding]) -> list[dict[str, Any]]:
    """Aggregate findings into per-folder rows sorted by VRAM saving.

    Returned shape:
        [
          {
            "folder": "Characters",
            "issues": 42,
            "auto_fixable": 31,
            "estimated_vram_saved_mb": 124.5,
            "estimated_shader_instructions_saved": 0,
          },
          ...
        ]
    """
    rows: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "issues": 0,
            "auto_fixable": 0,
            "estimated_vram_saved_mb": 0.0,
            "estimated_shader_instructions_saved": 0,
        }
    )

    for finding in findings:
        folder = _bucket_for(finding.asset_path)
        row = rows[folder]
        row["issues"] += 1
        if finding.auto_fixable:
            row["auto_fixable"] += 1
        row["estimated_vram_saved_mb"] += finding.estimated_saving.vram_mb
        row[
            "estimated_shader_instructions_saved"
        ] += finding.estimated_saving.shader_instructions

    output: list[dict[str, Any]] = []
    for folder, row in rows.items():
        output.append(
            {
                "folder": folder,
                "issues": row["issues"],
                "auto_fixable": row["auto_fixable"],
                "estimated_vram_saved_mb": round(row["estimated_vram_saved_mb"], 2),
                "estimated_shader_instructions_saved": (
                    row["estimated_shader_instructions_saved"]
                ),
            }
        )

    output.sort(key=lambda row: row["estimated_vram_saved_mb"], reverse=True)
    return output


def top_offenders(
    findings: list[Finding], n: int = _DEFAULT_TOP_N
) -> list[dict[str, Any]]:
    """Return the *n* assets with the highest aggregate VRAM saving.

    When the same asset triggers multiple rules (a 4K texture with wrong
    compression AND no streaming, say), all of its potential savings are
    summed so the offender bubbles up high.
    """
    per_asset: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "issues": 0,
            "vram_mb": 0.0,
            "shader_instructions": 0,
            "rules": [],
        }
    )

    for finding in findings:
        bucket = per_asset[finding.asset_path]
        bucket["issues"] += 1
        bucket["vram_mb"] += finding.estimated_saving.vram_mb
        bucket["shader_instructions"] += finding.estimated_saving.shader_instructions
        bucket["rules"].append(finding.rule_id)

    rows = [
        {
            "asset_path": path,
            "issues": data["issues"],
            "rules": data["rules"],
            "estimated_vram_saved_mb": round(data["vram_mb"], 2),
            "estimated_shader_instructions_saved": data["shader_instructions"],
        }
        for path, data in per_asset.items()
    ]

    rows.sort(
        key=lambda row: (
            row["estimated_vram_saved_mb"],
            row["estimated_shader_instructions_saved"],
            row["issues"],
        ),
        reverse=True,
    )
    return rows[:n]
