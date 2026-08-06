# core/modules/predictive/cost_model/rule_costs.py
#
# Loader + application of the per-rule cost table (config/rule_costs.yaml).
#
# The table maps code_validator rule_ids to multi-dimensional cost bands.
# apply_rule_cost() turns one validator issue (+ optional occurrence context
# + scene size) into per-dimension Predictions, applying the rule's scaling
# policy. An issue whose rule has no entry gets None — the caller counts it
# as uncosted, it never contributes an invented number.

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel
from predictive.cost_model.prediction import Prediction

_CONFIG_PATH = Path(__file__).parent / "config" / "rule_costs.yaml"

# per_scene_actors: cost was characterised against a 5k-actor scene; scale
# linearly with the actual count, clamped so a pathological scene can't
# produce absurd extrapolations.
_ACTOR_BASELINE = 5000.0
_ACTOR_CLAMP = (0.2, 4.0)
# per_loop_depth: nested loops multiply the iteration count; clamp keeps a
# deeply-nested outlier from dominating the whole budget.
_LOOP_CLAMP = (1.0, 4.0)


class CostEntry(BaseModel):
    """One rule's cost row, as loaded from the YAML."""

    rule_id: str
    dimensions: dict[str, dict[str, float]]  # dim -> {min, expected, max}
    scaling: str = "per_occurrence"
    confidence: str = "low"
    basis: str = ""
    remediation_action: str = ""
    recovery_pct: float = 0.0


class RuleCostTable(BaseModel):
    calibration_version: str
    reference_hw: str
    entries: dict[str, CostEntry]


@lru_cache(maxsize=1)
def load_rule_costs() -> RuleCostTable:
    with _CONFIG_PATH.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    entries: dict[str, CostEntry] = {}
    for rule_id, spec in (raw.get("rules") or {}).items():
        remediation = spec.get("remediation") or {}
        entries[rule_id] = CostEntry(
            rule_id=rule_id,
            dimensions=spec.get("dimensions") or {},
            scaling=spec.get("scaling", "per_occurrence"),
            confidence=spec.get("confidence", "low"),
            basis=spec.get("basis", ""),
            remediation_action=remediation.get("action", ""),
            recovery_pct=float(remediation.get("recovery_pct", 0.0)),
        )
    return RuleCostTable(
        calibration_version=raw.get("calibration_version", "unknown"),
        reference_hw=raw.get("reference_hw", ""),
        entries=entries,
    )


def _scale_factor(
    entry: CostEntry, context: dict[str, Any], scene_actor_count: int
) -> tuple[float, str]:
    """Resolve the scaling multiplier + a human suffix for the basis."""
    if entry.scaling == "per_scene_actors" and scene_actor_count > 0:
        factor = scene_actor_count / _ACTOR_BASELINE
        factor = max(_ACTOR_CLAMP[0], min(_ACTOR_CLAMP[1], factor))
        return factor, f", scaled for a {scene_actor_count}-actor scene"
    if entry.scaling == "per_loop_depth":
        depth = float(context.get("loop_depth", 0) or 0)
        if depth > 1:
            factor = max(_LOOP_CLAMP[0], min(_LOOP_CLAMP[1], depth))
            return factor, f", scaled for loop depth {int(depth)}"
    return 1.0, ""


def apply_rule_cost(
    issue: dict[str, Any],
    scene_actor_count: int = 0,
) -> tuple[dict[str, Prediction], dict[str, Prediction], CostEntry] | None:
    """Price one validator issue.

    Returns (impact, recovery, entry) — both keyed by dimension — or None
    when the rule has no cost entry (the caller records it as uncosted).

    ``issue`` is the raw dict from /validate/*: at minimum ``rule_id``;
    optionally ``occurrence_context`` ({in_tick, loop_depth,
    call_count_estimate}) which scaling policies read.
    """
    table = load_rule_costs()
    entry = table.entries.get(str(issue.get("rule_id", "")))
    if entry is None:
        return None

    context = issue.get("occurrence_context") or {}
    factor, suffix = _scale_factor(entry, context, scene_actor_count)
    calls = float(context.get("call_count_estimate", 1) or 1)
    factor *= max(1.0, calls)

    impact: dict[str, Prediction] = {}
    recovery: dict[str, Prediction] = {}
    for dim, band in entry.dimensions.items():
        unit = "mb_min" if dim == "gc_mb_min" else (
            "mb" if dim in ("ram_mb", "vram_mb", "build_mb") else "ms_frame"
        )
        pred = Prediction.banded(
            band["expected"], band["min"], band["max"], unit,
            entry.confidence, entry.basis + suffix,
        ).scaled(factor)
        impact[dim] = pred
        if entry.recovery_pct > 0:
            recovery[dim] = pred.scaled(
                entry.recovery_pct / 100.0,
                basis=(
                    f"{entry.remediation_action} "
                    f"(~{entry.recovery_pct:g}% of the cost)"
                ),
            )
    return impact, recovery, entry
