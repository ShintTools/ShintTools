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
from predictive.layers import layer1_assets, layer4_scores
from predictive.schema import (
    SCHEMA_VERSION,
    AnalyzeRequest,
    BuildReport,
    FrameBudget,
    MemoryBudgetLine,
    MemoryReport,
    PredictiveReport,
    ReportStats,
    Scores,
)

# Until M5 lands measured ground truth, every report says so.
CALIBRATION_VERSION = "uncalibrated-dev"

_TOP_ISSUES_N = 10


def _severity_key(item) -> tuple:
    order = {"critical": 0, "warning": 1, "info": 2}
    # Largest recovery first within a severity band (vram then build).
    recovery = 0.0
    if item.remediation:
        for pred in item.remediation.recovery.values():
            recovery += pred.expected
    return (order.get(item.severity, 1), -recovery)


def analyze_oneshot(request: AnalyzeRequest) -> PredictiveReport:
    """Produce a PredictiveReport from an inline (one-shot) payload."""
    profile = load_platform_profile(request.platform_profile)

    l1 = layer1_assets.analyze_assets(
        request.assets, engine=request.engine, profile="default"
    )

    # Rank items: severity first, biggest recovery inside each band.
    items = sorted(l1.items, key=_severity_key)
    for rank, item in enumerate(items, start=1):
        item.rank = rank

    scores = Scores(
        memory_risk=layer4_scores.compute_memory_risk(
            l1.vram_total, profile, items
        ),
        build_health=layer4_scores.compute_build_health(
            l1.build_total, profile, items
        ),
    )
    scores.overall_project_health = layer4_scores.compute_overall(scores)

    return PredictiveReport(
        schema_version=SCHEMA_VERSION,
        report_id=f"pr-{uuid.uuid4().hex[:12]}",
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        engine=request.engine,
        project_name=request.project_name,
        platform_profile=profile.model_dump(),
        calibration_version=CALIBRATION_VERSION,
        disclaimer=(
            f"Static estimate relative to reference hardware "
            f"({profile.reference_hw}). Bands are honest uncertainty, not "
            f"decoration — see docs/predictive/COST_MODEL.md."
        ),
        scores=scores,
        frame_budget=FrameBudget(),  # M2/M3 — CPU/GPU spend needs code+scene
        memory=MemoryReport(
            vram=MemoryBudgetLine(
                budget_mb=profile.vram_budget_mb, predicted=l1.vram_total
            ),
            ram=MemoryBudgetLine(budget_mb=profile.ram_budget_mb),
        ),
        build=BuildReport(size_mb=l1.build_total),
        top_issues=items[:_TOP_ISSUES_N],
        cost_items=items,
        stats=ReportStats(
            assets_analyzed=l1.assets_analyzed,
            scenes_analyzed=0,
            code_issues_costed=0,
            code_issues_uncosted=len(request.code_issues),
        ),
    )
