# core/modules/predictive/layers/layer1_assets.py
#
# Layer 1 — Asset Intelligence.
#
# Consumes the same asset dicts the LOD Auditor already collects (zero new
# client work) and produces:
#   - aggregate VRAM / build-size Predictions for the whole asset set
#   - CostItems for every LOD-audit finding that carries a measurable saving
#     (those findings ARE the optimizations the Impact Simulator toggles)
#
# The LOD audit itself is reused wholesale via lod_auditor.audit_assets —
# Layer 1 adds pricing and aggregation, not new detection rules.

from __future__ import annotations

import logging
from typing import Any

from predictive.cost_model.asset_costs import asset_build_mb, asset_vram
from predictive.cost_model.prediction import Prediction, sum_predictions
from predictive.schema import CostItem, Remediation

logger = logging.getLogger("shinttools.predictive.layer1")

# LOD-audit severities map onto the report's item severities directly.
_SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}


def normalize_engine(raw: str) -> str:
    """Map any engine spelling ("UE5", "Unity", "unreal") to the canonical
    rule engine "unreal" | "unity" the lod_auditor rules key off."""
    e = (raw or "").strip().lower()
    if e in ("unity", "unity6"):
        return "unity"
    return "unreal"


class Layer1Result:
    """Aggregates + items Layer 1 hands to the orchestrator."""

    def __init__(
        self,
        vram_total: Prediction,
        build_total: Prediction,
        items: list[CostItem],
        assets_analyzed: int,
    ) -> None:
        self.vram_total = vram_total
        self.build_total = build_total
        self.items = items
        self.assets_analyzed = assets_analyzed


def _finding_to_item(finding: Any, index: int) -> CostItem | None:
    """Promote one LOD-audit Finding with a nonzero saving to a CostItem.

    The finding's estimated_saving is the *recovery* — what fixing it buys
    back. Its impact on the current project is that same figure: the asset
    is costing that much more than it needs to.
    """
    saving = finding.estimated_saving
    recovery: dict[str, Prediction] = {}
    if saving.vram_mb > 0:
        recovery["vram_mb"] = Prediction.exact(
            saving.vram_mb, "mb", f"{finding.rule_id} saving from the LOD audit"
        )
    if saving.build_size_mb > 0:
        recovery["build_mb"] = Prediction.exact(
            saving.build_size_mb, "mb", f"{finding.rule_id} cooked-size saving"
        )
    if not recovery:
        return None

    return CostItem(
        item_id=f"ci-{index:04d}",
        layer=1,
        severity=finding.severity if finding.severity in _SEVERITY_RANK else "warning",
        title=(finding.rule_name or finding.rule_id) + f" — {finding.asset_path}",
        rule_id=finding.rule_id,
        source={
            "kind": finding.category.lower(),
            "path": finding.asset_path,
        },
        impact=dict(recovery),  # excess cost today == what the fix recovers
        remediation=Remediation(
            action=finding.message,
            recovery=recovery,
            auto_fixable=bool(finding.auto_fixable),
        ),
    )


def analyze_assets(
    assets: list[dict[str, Any]],
    engine: str,
    profile: str,
    start_index: int = 0,
) -> Layer1Result:
    """Price the asset set: aggregate memory/build totals + audit-driven items.

    ``start_index`` seeds the ci-NNNN numbering so layers can be concatenated
    without id collisions.
    """
    vram_parts: list[Prediction] = []
    build_parts: list[Prediction] = []
    priced = 0
    for asset in assets:
        vram = asset_vram(asset)
        if vram is None:
            continue
        priced += 1
        vram_parts.append(vram)
        build_parts.append(asset_build_mb(vram))

    vram_total = sum_predictions(
        vram_parts, "mb", f"Σ exact GPU payload of {priced} priced assets"
    )
    build_total = sum_predictions(
        build_parts, "mb", f"Σ cooked-size bands of {priced} priced assets"
    )

    # Reuse the LOD Auditor for the actionable findings. Import here so the
    # predictive module still imports cleanly if lod_auditor is ever split
    # into its own image layer.
    items: list[CostItem] = []
    try:
        from lod_auditor import audit_assets

        response = audit_assets(
            assets, engine=normalize_engine(engine), profile=profile
        )
        index = start_index
        for finding in response.results:
            item = _finding_to_item(finding, index)
            if item is not None:
                items.append(item)
                index += 1
    except Exception:  # noqa: BLE001 — pricing must not die on audit errors
        logger.exception("layer1: LOD audit failed — items omitted")

    return Layer1Result(
        vram_total=vram_total,
        build_total=build_total,
        items=items,
        assets_analyzed=len(assets),
    )
