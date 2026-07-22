# core/modules/predictive/layers/layer5_simulator.py
#
# Layer 5 — Impact Simulator.
#
# The report IS the simulator's database: every CostItem carries its
# remediation.recovery, so replaying a selection is pure arithmetic over the
# cached report — no re-analysis, an answer in milliseconds.
#
#   deltas       = -Σ recovery of the selected items, per dimension
#   scores_after = layer4 re-run over (reported totals − selected recovery),
#                  optionally against a different platform profile — the
#                  "what if I port to Steam Deck?" scenario.
#
# Stateless fallback: when the cached report expired, the client can inline
# the cost_items it kept. Deltas and recommendations still work; the
# before/after scores need the report's aggregate totals and stay at their
# defaults (documented in API.md) — the client holds the full report anyway.

from __future__ import annotations

from typing import Any

from predictive.cost_model.platform_profiles import (
    PlatformProfile,
    load_platform_profile,
)
from predictive.cost_model.prediction import Prediction
from predictive.layers import layer4_scores
from predictive.schema import CostItem, Scores, SimulateResponse

_RECOMMEND_N = 3

# Report field that backs each simulated dimension.
_DIMENSION_SOURCES = {
    "cpu_ms_frame": ("frame_budget", "cpu", "predicted"),
    "gpu_ms_frame": ("frame_budget", "gpu", "predicted"),
    "vram_mb": ("memory", "vram", "predicted"),
    "build_mb": ("build", "size_mb"),
}


def _items_from(report: dict[str, Any] | None,
                inline_items: list[dict[str, Any]]) -> list[CostItem]:
    raw = (report or {}).get("cost_items") or inline_items or []
    return [CostItem(**item) for item in raw]


def _sum_recovery(items: list[CostItem]) -> dict[str, Prediction]:
    """Per-dimension recovery total across *items*."""
    totals: dict[str, Prediction] = {}
    for item in items:
        if item.remediation is None:
            continue
        for dim, pred in item.remediation.recovery.items():
            totals[dim] = totals[dim].plus(pred) if dim in totals else pred
    return totals


def _report_total(report: dict[str, Any], path: tuple[str, ...]) -> Prediction | None:
    node: Any = report
    for key in path:
        node = (node or {}).get(key)
    if not node:
        return None
    try:
        return Prediction(**node)
    except Exception:  # noqa: BLE001 — malformed cached report
        return None


def _minus_recovery(total: Prediction | None,
                    recovery: Prediction | None) -> Prediction | None:
    """total − recovery, floored at zero (a fix can't make spend negative)."""
    if total is None:
        return None
    if recovery is None:
        return total
    return Prediction.banded(
        max(0.0, total.expected - recovery.expected),
        max(0.0, total.min - recovery.min),
        max(0.0, total.max - recovery.max),
        total.unit,
        total.confidence,
        f"{total.basis} minus selected fixes",
    )


def _scores_from(report: dict[str, Any]) -> Scores:
    try:
        return Scores(**(report.get("scores") or {}))
    except Exception:  # noqa: BLE001
        return Scores()


def _recompute_scores(
    report: dict[str, Any],
    recovery: dict[str, Prediction],
    remaining: list[CostItem],
    profile: PlatformProfile,
) -> Scores:
    """Layer 4 over the adjusted totals — the after picture."""
    before = _scores_from(report)
    cpu = _minus_recovery(
        _report_total(report, _DIMENSION_SOURCES["cpu_ms_frame"]),
        recovery.get("cpu_ms_frame"),
    )
    gpu = _minus_recovery(
        _report_total(report, _DIMENSION_SOURCES["gpu_ms_frame"]),
        recovery.get("gpu_ms_frame"),
    )
    vram = _minus_recovery(
        _report_total(report, _DIMENSION_SOURCES["vram_mb"]),
        recovery.get("vram_mb"),
    )
    build = _minus_recovery(
        _report_total(report, _DIMENSION_SOURCES["build_mb"]),
        recovery.get("build_mb"),
    )

    after = Scores(
        cpu_risk=layer4_scores.compute_cpu_risk(cpu, profile, remaining)
        if cpu is not None
        else before.cpu_risk,
        gpu_risk=layer4_scores.compute_gpu_risk(gpu, profile, remaining)
        if gpu is not None
        else before.gpu_risk,
        memory_risk=layer4_scores.compute_memory_risk(vram, profile, remaining)
        if vram is not None
        else before.memory_risk,
        build_health=layer4_scores.compute_build_health(
            build, profile, remaining
        )
        if build is not None
        else before.build_health,
    )
    after.overall_project_health = layer4_scores.compute_overall(after)
    return after


def _recommendations(remaining: list[CostItem]) -> list[dict[str, Any]]:
    """Top unselected items by total expected recovery — 'fix this next'."""
    scored: list[tuple[float, CostItem]] = []
    for item in remaining:
        if item.remediation is None or not item.remediation.recovery:
            continue
        total = sum(p.expected for p in item.remediation.recovery.values())
        if total > 0:
            scored.append((total, item))
    scored.sort(key=lambda pair: -pair[0])
    out = []
    for total, item in scored[:_RECOMMEND_N]:
        headline = max(
            item.remediation.recovery.items(), key=lambda kv: kv[1].expected
        )
        out.append(
            {
                "item_id": item.item_id,
                "reason": (
                    f"Largest remaining recovery: "
                    f"{headline[1].to_display()} ({headline[0]})"
                ),
                "auto_fixable": item.remediation.auto_fixable,
            }
        )
    return out


def simulate(
    report: dict[str, Any] | None,
    selected_item_ids: list[str],
    inline_items: list[dict[str, Any]],
    platform_profile: str = "",
) -> SimulateResponse:
    """Replay a selection against a cached report (or inline items).

    ``platform_profile`` overrides the report's profile for the after
    scores — the porting scenario. Deltas are profile-independent (they are
    reference-HW figures, like every ms in the report).
    """
    items = _items_from(report, inline_items)
    by_id = {item.item_id: item for item in items}
    selected = [by_id[i] for i in selected_item_ids if i in by_id]
    remaining = [
        item for item in items if item.item_id not in set(selected_item_ids)
    ]

    recovery = _sum_recovery(selected)
    deltas = {
        dim: pred.negated(basis=f"Σ recovery of {len(selected)} selected fixes")
        for dim, pred in recovery.items()
    }

    response = SimulateResponse(
        report_id=str((report or {}).get("report_id", "")),
        selected_count=len(selected),
        deltas=deltas,
        recommendations=_recommendations(remaining),
    )

    if report is not None:
        report_profile = str(
            ((report.get("platform_profile") or {}).get("profile")) or ""
        )
        profile_name = platform_profile or report_profile or "desktop_60"
        profile = load_platform_profile(profile_name)
        if platform_profile and platform_profile != report_profile:
            # Porting scenario: both sides of the comparison must use the
            # NEW platform's budgets, or before/after mixes two platforms.
            response.scores_before = _recompute_scores(report, {}, items, profile)
        else:
            response.scores_before = _scores_from(report)
        response.scores_after = _recompute_scores(
            report, recovery, remaining, profile
        )
    return response
