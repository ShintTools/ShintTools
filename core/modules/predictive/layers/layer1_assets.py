# core/modules/predictive/layers/layer1_assets.py
#
# Layer 1 — Asset Intelligence.
#
# Consumes the same asset dicts the LOD Auditor already collects (zero new
# client work) and produces:
#   - aggregate VRAM / build-size Predictions for the whole asset set
#   - one CostItem per priced asset, unconditionally — an asset costs VRAM
#     whether or not it has an inefficiency; Predictive prices, it does not
#     diagnose (that's the LOD Auditor/Asset Optimizer's job)
#   - a Remediation attached to that same item when the LOD Auditor also
#     has a finding-with-saving for it (the Impact Simulator's currency)
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
# "critical" is unreachable from lod_auditor.Finding (warning|info only)
# but kept so a future finding source can't silently sort as "unknown".
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


def _base_item(asset: dict[str, Any], vram: Prediction, build: Prediction, index: int) -> CostItem:
    """One unconditional CostItem per priced asset — name + total cost, no
    diagnosis. Findings (if any) attach a Remediation to this same item."""
    path = str(asset.get("asset_path", ""))
    return CostItem(
        item_id=f"ci-{index:04d}",
        layer=1,
        severity="info",
        title=path,
        rule_id="",
        source={"kind": str(asset.get("asset_type", "")).lower(), "path": path},
        impact={"vram_mb": vram, "build_mb": build},
        remediation=None,
    )


def _recovery_from_finding(finding: Any) -> dict[str, Prediction]:
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
    return recovery


def _attach_findings(
    items_by_path: dict[str, CostItem],
    findings: list[Any],
    next_index: int,
) -> list[CostItem]:
    """Group findings by asset_path, aggregate their recovery onto the
    matching base item (an asset can trip >1 rule — e.g. LT003 + LT008).
    Findings on an asset with no base item (e.g. a Material with only a
    build-size saving, which asset_vram() doesn't price) synthesize a
    fallback item so today's material/build-saving items don't regress."""
    by_path: dict[str, list[Any]] = {}
    for finding in findings:
        recovery = _recovery_from_finding(finding)
        if not recovery:
            continue
        by_path.setdefault(finding.asset_path, []).append(finding)

    fallback_items: list[CostItem] = []
    index = next_index
    for path, path_findings in by_path.items():
        recovery: dict[str, Prediction] = {}
        for finding in path_findings:
            for dim, pred in _recovery_from_finding(finding).items():
                recovery[dim] = recovery[dim].plus(pred) if dim in recovery else pred

        worst = min(path_findings, key=lambda f: _SEVERITY_RANK.get(f.severity, 1))
        biggest = max(
            path_findings,
            key=lambda f: sum(p.expected for p in _recovery_from_finding(f).values()),
        )
        parts = ", ".join(
            f"{pred.expected:.2f} MB {dim.replace('_mb', '').upper()}"
            for dim, pred in recovery.items()
        )
        remediation = Remediation(
            action=f"Recoverable: {parts}",
            recovery=recovery,
            auto_fixable=all(f.auto_fixable for f in path_findings),
        )

        if path in items_by_path:
            item = items_by_path[path]
            item.severity = worst.severity if worst.severity in _SEVERITY_RANK else "warning"
            item.rule_id = biggest.rule_id
            item.remediation = remediation
        else:
            fallback_items.append(
                CostItem(
                    item_id=f"ci-{index:04d}",
                    layer=1,
                    severity=worst.severity if worst.severity in _SEVERITY_RANK else "warning",
                    title=path,
                    rule_id=biggest.rule_id,
                    source={"kind": worst.category.lower(), "path": path},
                    impact=dict(recovery),
                    remediation=remediation,
                )
            )
            index += 1

    return fallback_items


def analyze_assets(
    assets: list[dict[str, Any]],
    engine: str,
    profile: str,
    start_index: int = 0,
) -> Layer1Result:
    """Price the asset set: aggregate memory/build totals + one item per
    priced asset, with a Remediation attached where the LOD Auditor also
    has a finding-with-saving for it.

    ``start_index`` seeds the ci-NNNN numbering so layers can be concatenated
    without id collisions.
    """
    vram_parts: list[Prediction] = []
    build_parts: list[Prediction] = []
    items: list[CostItem] = []
    items_by_path: dict[str, CostItem] = {}
    index = start_index
    for asset in assets:
        vram = asset_vram(asset)
        if vram is None:
            continue
        build = asset_build_mb(vram)
        vram_parts.append(vram)
        build_parts.append(build)

        item = _base_item(asset, vram, build, index)
        items.append(item)
        items_by_path[item.source.get("path", "")] = item
        index += 1

    priced = len(vram_parts)
    vram_total = sum_predictions(
        vram_parts, "mb", f"Σ exact GPU payload of {priced} priced assets"
    )
    build_total = sum_predictions(
        build_parts, "mb", f"Σ cooked-size bands of {priced} priced assets"
    )

    # Reuse the LOD Auditor for the actionable findings. Import here so the
    # predictive module still imports cleanly if lod_auditor is ever split
    # into its own image layer.
    try:
        from lod_auditor import audit_assets

        response = audit_assets(
            assets, engine=normalize_engine(engine), profile=profile
        )
        items.extend(_attach_findings(items_by_path, response.results, index))
    except Exception:  # noqa: BLE001 — pricing must not die on audit errors
        logger.exception("layer1: LOD audit failed — remediation omitted")

    return Layer1Result(
        vram_total=vram_total,
        build_total=build_total,
        items=items,
        assets_analyzed=len(assets),
    )
