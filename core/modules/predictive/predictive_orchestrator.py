# core/modules/predictive/predictive_orchestrator.py
#
# Orchestrator — assembles the layers into a PredictiveReport.
#
# M1 scope: one-shot analysis over the assets section (Layer 1) + partial
# scores (memory_risk, build_health). Scene (Layer 2), code (Layer 3) and
# sessions arrive in M2/M3; the report's ``stats`` records exactly what was
# and wasn't covered so a degraded report is an honest report.

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from predictive.cost_model.platform_profiles import load_platform_profile
from predictive.cost_model.rule_costs import load_rule_costs
from predictive.layers import (
    layer1_assets,
    layer2_scene,
    layer3_code,
    layer4_scores,
)
from predictive.layers.layer1_assets import normalize_engine
from predictive.schema import (
    DIMENSION_DISPLAY,
    SCHEMA_VERSION,
    AnalyzeRequest,
    BudgetLine,
    BuildReport,
    CostValue,
    FrameBudget,
    FrameLine,
    MemoryBudgetLine,
    MemoryReport,
    PredictiveReport,
    ReportStats,
    Scores,
)

_TOP_ISSUES_N = 10

# impact dimension -> the PlatformProfile budget attribute that prices it.
# Dimensions with no direct budget (gc_mb_min) fall back to a raw-expected
# tiebreak rather than a manufactured denominator.
_BUDGET_ATTR = {
    "cpu_ms_frame": "cpu_budget_ms",
    "gpu_ms_frame": "gpu_budget_ms",
    "vram_mb": "vram_budget_mb",
    "ram_mb": "ram_budget_mb",
    "build_mb": "build_advisory_mb",
}


def _budget_for(profile, dim: str) -> float:
    attr = _BUDGET_ATTR.get(dim)
    return float(getattr(profile, attr, 0) or 0) if attr else 0.0


def _set_primary_cost(item, profile) -> None:
    """Pick the dimension a one-column table should render for this row.

    Dominance is budget-normalized, not raw magnitude — 40 MB of VRAM and
    0.4 ms of CPU aren't comparable as numbers, only as shares of their own
    budget. Without this a client with a fixed "ms" column shows 0 ms for
    every asset (assets cost MB, not ms), which reads as "free".
    """
    best_dim, best_share, best_expected = "", -1.0, 0.0
    for dim, pred in item.impact.items():
        budget = _budget_for(profile, dim)
        share = pred.expected / budget if budget else pred.expected
        if share > best_share:
            best_dim, best_share, best_expected = dim, share, pred.expected

    if not best_dim:
        return
    unit, label = DIMENSION_DISPLAY.get(best_dim, ("", best_dim))
    item.primary_cost = CostValue(
        dimension=best_dim, value=best_expected, unit=unit, label=label
    )


def _has_cost(item) -> bool:
    """Drop rows that price out to nothing in every dimension. A 0-cost row
    is noise: it can't be ranked, can't be simulated, and reads as a bug."""
    return any(pred.expected > 0 for pred in item.impact.values())


def _with_residual(breakdown: list[dict], predicted) -> list[dict]:
    """Guarantee the breakdown sums to ``predicted``.

    The aggregate labels normally cover the whole total; this closes any gap
    left by a term that has no label of its own, so a client can always
    render the breakdown as a stacked bar that reaches the total.
    """
    if predicted is None:
        return breakdown
    residual = predicted.expected - sum(b["expected_ms"] for b in breakdown)
    if residual > 0.01:
        return breakdown + [
            {"label": "Other", "expected_ms": round(residual, 3)}
        ]
    return breakdown


def _itemized_ms(items, dimension: str) -> float:
    """How much of a dimension's total is represented as its own table row.

    Scene dispatch is priced in aggregate but only individually actionable
    offenders become rows, so summing the table legitimately falls short of
    the budget total. Reporting the covered figure lets a client show
    "rows account for X of Y ms" instead of looking like it lost time.
    """
    return round(
        sum(
            item.impact[dimension].expected
            for item in items
            if dimension in item.impact
        ),
        3,
    )


def _frame_line(cpu_total, gpu_total, profile) -> FrameLine:
    """Predicted frame time from the CPU and GPU axes.

    Frame time is NOT cpu + gpu. The two run pipelined — the GPU renders
    frame N while the CPU builds N+1 — so the frame is paced by whichever
    axis is slower. Adding them double-counts the overlapped work and
    overstates the frame by roughly the smaller axis, which is exactly the
    mismatch a client hits when it sums the two lines and compares against
    the budget.
    """
    cpu_ms = cpu_total.expected if cpu_total else 0.0
    gpu_ms = gpu_total.expected if gpu_total else 0.0
    if cpu_total is None and gpu_total is None:
        return FrameLine(budget_ms=profile.frame_budget_ms)

    bottleneck = "cpu" if cpu_ms >= gpu_ms else "gpu"
    return FrameLine(
        budget_ms=profile.frame_budget_ms,
        predicted_ms=round(max(cpu_ms, gpu_ms), 3),
        bottleneck=bottleneck,
        note=(
            "Frame time is paced by the slower axis, not the sum: CPU and GPU "
            f"work overlaps across frames. {bottleneck.upper()}-bound at "
            f"{max(cpu_ms, gpu_ms):.2f} ms (CPU {cpu_ms:.2f} / GPU {gpu_ms:.2f})."
        ),
    )


def _impact_key(item, profile) -> tuple:
    """Rank by how much of its budget an item eats — unit-correct (you
    can't sum ms and MB), so this normalizes each dimension by its own
    budget before summing. An expensive-but-unflagged asset outranks a
    cheap flagged one; severity only breaks ties."""
    order = {"critical": 0, "warning": 1, "info": 2}
    score = 0.0
    for dim, pred in item.impact.items():
        attr = _BUDGET_ATTR.get(dim)
        budget = getattr(profile, attr, 0) if attr else 0
        score += pred.expected / budget if budget else pred.expected
    return (-score, order.get(item.severity, 1))


def analyze_oneshot(request: AnalyzeRequest) -> PredictiveReport:
    """Produce a PredictiveReport from an inline (one-shot) payload."""
    profile = load_platform_profile(request.platform_profile)

    l1 = layer1_assets.analyze_assets(
        request.assets, engine=request.engine, profile="default"
    )
    l2 = layer2_scene.analyze_scenes(request.scenes, start_index=len(l1.items))
    l3 = layer3_code.analyze_code(
        request.code_issues,
        scene_actor_count=l2.max_actor_count,
        start_index=len(l1.items) + len(l2.items),
        code_files=request.code_files,
        engine=normalize_engine(request.engine),
    )

    # Rank items: budget-normalized cost magnitude first (an expensive
    # unflagged asset outranks a cheap flagged issue), severity as tiebreak.
    priced_items = [i for i in l1.items + l2.items + l3.items if _has_cost(i)]
    items = sorted(priced_items, key=lambda i: _impact_key(i, profile))
    for rank, item in enumerate(items, start=1):
        item.rank = rank
        _set_primary_cost(item, profile)

    # Scene dispatch + code patterns share the CPU budget.
    has_cpu_data = bool(l3.items or l2.scenes_analyzed)
    cpu_total = l3.cpu_total.plus(
        l2.cpu_total, basis="code patterns + scene dispatch"
    )

    scores = Scores(
        # Only an axis with data scores — "no data" is not "risk 0".
        cpu_risk=layer4_scores.compute_cpu_risk(cpu_total, profile, items)
        if has_cpu_data
        else Scores().cpu_risk,
        gpu_risk=layer4_scores.compute_gpu_risk(l2.gpu_total, profile, items)
        if l2.scenes_analyzed
        else Scores().gpu_risk,
        memory_risk=layer4_scores.compute_memory_risk(
            l1.vram_total, profile, items
        ),
        build_health=layer4_scores.compute_build_health(
            l1.build_total, profile, items
        ),
    )
    scores.overall_project_health = layer4_scores.compute_overall(scores)

    table = load_rule_costs()
    return PredictiveReport(
        schema_version=SCHEMA_VERSION,
        report_id=f"pr-{uuid.uuid4().hex[:12]}",
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        engine=request.engine,
        project_name=request.project_name,
        platform_profile=profile.model_dump(),
        calibration_version=table.calibration_version,
        disclaimer=(
            f"Static estimate relative to reference hardware "
            f"({profile.reference_hw}). Bands are honest uncertainty, not "
            f"decoration — see docs/predictive/COST_MODEL.md."
        ),
        scores=scores,
        frame_budget=FrameBudget(
            cpu=BudgetLine(
                budget_ms=profile.cpu_budget_ms,
                predicted=cpu_total if has_cpu_data else None,
                breakdown=_with_residual(
                    (
                        [{"label": "Code patterns",
                          "expected_ms": l3.cpu_total.expected}]
                        if l3.items
                        else []
                    )
                    + (
                        [{"label": "Scene dispatch",
                          "expected_ms": l2.cpu_total.expected}]
                        if l2.scenes_analyzed
                        else []
                    ),
                    cpu_total if has_cpu_data else None,
                ),
                itemized_ms=_itemized_ms(items, "cpu_ms_frame"),
            ),
            gpu=BudgetLine(
                budget_ms=profile.gpu_budget_ms,
                predicted=l2.gpu_total if l2.scenes_analyzed else None,
                breakdown=_with_residual(
                    (
                        [{"label": "Dynamic lights + GPU particles",
                          "expected_ms": l2.gpu_total.expected}]
                        if l2.scenes_analyzed
                        else []
                    ),
                    l2.gpu_total if l2.scenes_analyzed else None,
                ),
                itemized_ms=_itemized_ms(items, "gpu_ms_frame"),
            ),
            frame=_frame_line(
                cpu_total if has_cpu_data else None,
                l2.gpu_total if l2.scenes_analyzed else None,
                profile,
            ),
        ),
        memory=MemoryReport(
            vram=MemoryBudgetLine(
                budget_mb=profile.vram_budget_mb, predicted=l1.vram_total
            ),
            ram=MemoryBudgetLine(
                budget_mb=profile.ram_budget_mb, predicted=l3.ram_total
            ),
            gc_pressure=l3.gc_total,
        ),
        build=BuildReport(size_mb=l1.build_total),
        top_issues=items[:_TOP_ISSUES_N],
        cost_items=items,
        scene_summaries=l2.summaries,
        stats=ReportStats(
            assets_analyzed=l1.assets_analyzed,
            scenes_analyzed=l2.scenes_analyzed,
            code_issues_costed=l3.costed,
            code_issues_uncosted=l3.uncosted,
        ),
    )


def analyze_session(session: dict) -> PredictiveReport:
    """Analyze an assembled session document (batched-ingest flow)."""
    return analyze_oneshot(
        AnalyzeRequest(
            engine=str(session.get("engine", "UE5")),
            project_name=str(session.get("project_name", "")),
            platform_profile=str(session.get("platform_profile", "desktop_60")),
            assets=list(session.get("assets") or []),
            scenes=list(session.get("scenes") or []),
            code_issues=list(session.get("code_issues") or []),
            code_files=list(session.get("code_files") or []),
            config=dict(session.get("config") or {}),
        )
    )
