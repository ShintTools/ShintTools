# core/modules/predictive/layers/layer3_code.py
#
# Layer 3 — Deep Code Intelligence.
#
# Takes validator issues (the /validate/* output the client already has) and
# quantifies them: each issue whose rule has an entry in rule_costs.yaml
# becomes a CostItem with per-dimension impact bands and a remediation
# recovery. The spec's literal target: "Tick → GetAllActorsOfClass:
# impacto estimado +1.4 ms CPU/frame".
#
# Issues without a cost entry are counted (uncosted), never priced — the
# report's stats expose exactly how much of the code surface the budget
# numbers actually cover.

from __future__ import annotations

from typing import Any

from predictive.cost_model.prediction import Prediction, sum_predictions
from predictive.cost_model.rule_costs import apply_rule_cost, load_rule_costs
from predictive.schema import CostItem, Remediation

# Dimensions Layer 3 aggregates into budget totals.
_CPU = "cpu_ms_frame"
_GPU = "gpu_ms_frame"
_GC = "gc_mb_min"
_RAM = "ram_mb"

_SEVERITY_BY_EXPECTED_MS = (
    (1.0, "critical"),  # >= 1 ms/frame from a single issue
    (0.2, "warning"),
)


class Layer3Result:
    def __init__(
        self,
        cpu_total: Prediction,
        gc_total: Prediction | None,
        ram_total: Prediction | None,
        items: list[CostItem],
        costed: int,
        uncosted: int,
    ) -> None:
        self.cpu_total = cpu_total
        self.gc_total = gc_total
        self.ram_total = ram_total
        self.items = items
        self.costed = costed
        self.uncosted = uncosted


def _severity_for(impact: dict[str, Prediction]) -> str:
    cpu = impact.get(_CPU)
    if cpu is not None:
        for threshold, severity in _SEVERITY_BY_EXPECTED_MS:
            if cpu.expected >= threshold:
                return severity
    return "info"


def _title_for(issue: dict[str, Any]) -> str:
    """"Tick → GetAllActorsOfClass" style title when context allows."""
    rule_name = str(issue.get("rule_name") or issue.get("rule_id") or "issue")
    context = issue.get("occurrence_context") or {}
    if context.get("in_tick"):
        # The rule names already read "X in Tick/Update" — the arrow form is
        # only added when the plain name doesn't mention the hot path.
        lowered = rule_name.lower()
        if "tick" not in lowered and "update" not in lowered:
            return f"Tick → {rule_name}"
    return rule_name


def analyze_code(
    code_issues: list[dict[str, Any]],
    scene_actor_count: int = 0,
    start_index: int = 0,
) -> Layer3Result:
    """Quantify validator issues into CostItems + budget aggregates.

    ``scene_actor_count`` (from the scenes section, when present) drives the
    per_scene_actors scaling — a GetAllActorsOfClass in a 20k-actor world is
    not priced like one in an empty test map.
    """
    items: list[CostItem] = []
    cpu_parts: list[Prediction] = []
    gc_parts: list[Prediction] = []
    ram_parts: list[Prediction] = []
    uncosted = 0
    index = start_index

    for issue in code_issues:
        priced = apply_rule_cost(issue, scene_actor_count)
        if priced is None:
            uncosted += 1
            continue
        impact, recovery, entry = priced

        if _CPU in impact:
            cpu_parts.append(impact[_CPU])
        if _GC in impact:
            gc_parts.append(impact[_GC])
        if _RAM in impact:
            ram_parts.append(impact[_RAM])

        items.append(
            CostItem(
                item_id=f"ci-{index:04d}",
                layer=3,
                severity=_severity_for(impact),
                title=_title_for(issue),
                rule_id=entry.rule_id,
                source={
                    "kind": "code",
                    "path": issue.get("file", ""),
                    "line": issue.get("line"),
                },
                impact=impact,
                remediation=Remediation(
                    action=entry.remediation_action,
                    recovery=recovery,
                    auto_fixable=bool(issue.get("auto_fixable", False)),
                ),
            )
        )
        index += 1

    costed = len(items)
    table = load_rule_costs()
    cpu_total = sum_predictions(
        cpu_parts,
        "ms_frame",
        f"Σ {len(cpu_parts)} costed code patterns "
        f"({table.calibration_version})",
    )
    gc_total = (
        sum_predictions(gc_parts, "mb_min", f"Σ {len(gc_parts)} GC-pressure patterns")
        if gc_parts
        else None
    )
    ram_total = (
        sum_predictions(ram_parts, "mb", f"Σ {len(ram_parts)} allocation patterns")
        if ram_parts
        else None
    )
    return Layer3Result(
        cpu_total=cpu_total,
        gc_total=gc_total,
        ram_total=ram_total,
        items=items,
        costed=costed,
        uncosted=uncosted,
    )
