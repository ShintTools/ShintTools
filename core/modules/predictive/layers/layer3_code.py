# core/modules/predictive/layers/layer3_code.py
#
# Layer 3 — Deep Code Intelligence.
#
# Two ways in: legacy client-supplied ``code_issues`` (the client already
# ran /validate/* itself and forwards its output — kept for backward
# compat with the frozen v1.0 contract), and ``code_files`` (raw source —
# Predictive scans it in-process via code_scan.scan_code_files, the same
# way Layer 1 calls lod_auditor.audit_assets in-process instead of making
# the client pre-run the LOD audit). Both paths feed the same costing loop.
#
# Each issue whose rule has an entry in rule_costs.yaml becomes a CostItem
# with per-dimension impact bands and a remediation recovery, titled by
# location ("file:line") — not a description; that belongs to the Code
# Validator's own findings UI.
#
# Issues without a cost entry are counted (uncosted), never priced — the
# report's stats expose exactly how much of the code surface the budget
# numbers actually cover.

from __future__ import annotations

from typing import Any

from predictive.cost_model.prediction import Prediction, sum_predictions
from predictive.cost_model.rule_costs import apply_rule_cost, load_rule_costs
from predictive.layers.code_scan import scan_code_files
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
    """Location, not a description — "file:line", falling back to just the
    file when no line is known. What the pattern IS (rule_name/rule_id)
    stays queryable metadata on the item, not the headline."""
    path = str(issue.get("file") or "")
    line = issue.get("line")
    if path and line:
        return f"{path}:{line}"
    return path or str(issue.get("rule_id") or "issue")


_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


def _merge_by_location(items: list[CostItem], start_index: int) -> list[CostItem]:
    """Collapse items that share a source location into one row.

    Titles are locations ("file:line"), so two different rules firing on the
    same line render as two visually identical rows — the "repeated elements"
    the table shows. They are genuinely distinct patterns, but the row's unit
    of meaning is the location, so their costs are summed into a single row
    and the contributing rules are kept in ``source.rule_ids``.

    Budget totals are unaffected: the same Predictions are summed here as
    were accumulated into cpu/gc/ram totals above.
    """
    merged: dict[tuple, CostItem] = {}
    order: list[tuple] = []

    for item in items:
        key = (item.source.get("path", ""), item.source.get("line"))
        if not key[0]:  # no location to merge on — keep as its own row
            key = ("\x00unkeyed", item.item_id)

        existing = merged.get(key)
        if existing is None:
            item.source["rule_ids"] = [item.rule_id] if item.rule_id else []
            merged[key] = item
            order.append(key)
            continue

        for dim, pred in item.impact.items():
            existing.impact[dim] = (
                existing.impact[dim].plus(pred) if dim in existing.impact else pred
            )
        if item.remediation and existing.remediation:
            for dim, pred in item.remediation.recovery.items():
                existing.remediation.recovery[dim] = (
                    existing.remediation.recovery[dim].plus(pred)
                    if dim in existing.remediation.recovery
                    else pred
                )
            existing.remediation.auto_fixable = (
                existing.remediation.auto_fixable and item.remediation.auto_fixable
            )
        elif item.remediation:
            existing.remediation = item.remediation

        if _SEVERITY_ORDER.get(item.severity, 1) < _SEVERITY_ORDER.get(
            existing.severity, 1
        ):
            existing.severity = item.severity
        if item.rule_id and item.rule_id not in existing.source["rule_ids"]:
            existing.source["rule_ids"].append(item.rule_id)

    result = [merged[key] for key in order]
    # Re-number so ids stay contiguous after the merge (the simulator selects
    # by item_id, so they must be stable within the report).
    for offset, item in enumerate(result):
        item.item_id = f"ci-{start_index + offset:04d}"
        if len(item.source.get("rule_ids", [])) > 1:
            item.rule_id = ", ".join(item.source["rule_ids"])
    return result


def analyze_code(
    code_issues: list[dict[str, Any]],
    scene_actor_count: int = 0,
    start_index: int = 0,
    code_files: list[dict[str, Any]] | None = None,
    engine: str = "unreal",
) -> Layer3Result:
    """Quantify validator issues into CostItems + budget aggregates.

    ``scene_actor_count`` (from the scenes section, when present) drives the
    per_scene_actors scaling — a GetAllActorsOfClass in a 20k-actor world is
    not priced like one in an empty test map.

    ``code_files`` (raw ``{"path", "content"}`` source) is scanned in-process
    via code_scan.scan_code_files and unioned with any legacy ``code_issues``
    the client already forwards — both feed the same costing loop below.
    """
    items: list[CostItem] = []
    cpu_parts: list[Prediction] = []
    gc_parts: list[Prediction] = []
    ram_parts: list[Prediction] = []
    uncosted = 0
    index = start_index

    scanned = scan_code_files(code_files, engine) if code_files else []
    for issue in list(code_issues) + scanned:
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
    items = _merge_by_location(items, start_index)
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
