# core/modules/predictive/layers/layer4_scores.py
#
# Layer 4 — Predictive Engine: budget utilisation → 0-100 risk scores.
#
# The primary signal is *predicted spend against the platform budget* — that
# is what makes the score predictive rather than a lint counter. The curve is
# piecewise: comfortable headroom stays green, the last 15% of budget climbs
# fast, and anything over budget is high-risk scaled by the overrun.
#
#   utilisation ≤ 0.60          → risk  0-20   (linear)
#   0.60 < u ≤ 0.85             → risk 20-50
#   0.85 < u ≤ 1.00             → risk 50-80
#   u > 1.00                    → risk 80-100  (+2 per % over, capped)
#
# M1 ships memory_risk + build_health (asset data only). cpu/gpu risks join
# in M2/M3 when Layers 3/2 land. ``overall`` uses weighted-max, not average:
# one blown axis must sink the project score.

from __future__ import annotations

from predictive.cost_model.platform_profiles import PlatformProfile
from predictive.cost_model.prediction import Prediction
from predictive.schema import CostItem, RiskScore, Scores

# VR-style strict budgets steepen the over-budget slope: a missed frame is a
# comfort problem there, not just a quality problem.
_OVERRUN_SLOPE = 200.0
_OVERRUN_SLOPE_STRICT = 400.0


def utilisation_risk(utilisation: float, strict: bool = False) -> int:
    """Map budget utilisation (0.0-∞) onto the 0-100 piecewise risk curve."""
    u = max(0.0, utilisation)
    if u <= 0.60:
        risk = (u / 0.60) * 20.0
    elif u <= 0.85:
        risk = 20.0 + ((u - 0.60) / 0.25) * 30.0
    elif u <= 1.00:
        risk = 50.0 + ((u - 0.85) / 0.15) * 30.0
    else:
        slope = _OVERRUN_SLOPE_STRICT if strict else _OVERRUN_SLOPE
        risk = 80.0 + (u - 1.00) * slope
    return int(round(min(100.0, risk)))


def _top_drivers(items: list[CostItem], dimension: str, n: int = 5) -> list[str]:
    """The item ids that contribute most to *dimension*, biggest first."""
    scored = [
        (item.impact[dimension].expected, item.item_id)
        for item in items
        if dimension in item.impact
    ]
    scored.sort(reverse=True)
    return [item_id for _, item_id in scored[:n]]


def compute_memory_risk(
    vram_total: Prediction,
    profile: PlatformProfile,
    items: list[CostItem],
) -> RiskScore:
    """Memory risk from VRAM utilisation (RAM joins once Layer 2/3 price it).

    On unified-memory platforms (Steam Deck) the GPU payload competes with
    everything else in one pool, so the effective budget is the joint pool
    scaled by a conservative 2/3 GPU share.
    """
    budget = float(profile.vram_budget_mb)
    if profile.unified_memory:
        budget = (profile.vram_budget_mb + profile.ram_budget_mb) * (2.0 / 3.0)
    utilisation = vram_total.expected / budget if budget > 0 else 0.0
    return RiskScore(
        value=utilisation_risk(utilisation, profile.strict_budget),
        drivers=_top_drivers(items, "vram_mb"),
    )


def compute_build_health(
    build_total: Prediction,
    profile: PlatformProfile,
    items: list[CostItem],
) -> RiskScore:
    """Build health (100 = healthy) from cooked size vs the advisory budget."""
    budget = float(profile.build_advisory_mb)
    utilisation = build_total.expected / budget if budget > 0 else 0.0
    return RiskScore(
        value=100 - utilisation_risk(utilisation),
        drivers=_top_drivers(items, "build_mb"),
    )


def compute_overall(scores: Scores) -> int:
    """Overall health = 100 − weighted max of the known risks.

    Weighted max, not mean: a project with one axis on fire is not "half
    healthy". Unscored axes (value 0 with no drivers — layers not shipped
    yet) are excluded so M1 reports aren't diluted by absent data.
    """
    risks: list[float] = []
    for risk in (scores.cpu_risk, scores.gpu_risk, scores.memory_risk):
        if risk.value > 0 or risk.drivers:
            risks.append(float(risk.value))
    if scores.build_health.value > 0 or scores.build_health.drivers:
        risks.append(float(100 - scores.build_health.value))
    if not risks:
        return 100
    top = max(risks)
    rest = [r for r in risks if r != top] or [0.0]
    # 75% the worst axis, 25% the average of the others.
    return int(round(100 - (0.75 * top + 0.25 * (sum(rest) / len(rest)))))
