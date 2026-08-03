# core/modules/assistant/actions/why_rule.py
#
# "Why does this rule exist?" — answered from the cost engine, not from
# the model's memory of general best practice.
#
# The differentiator: a generic assistant says "GetAllActorsOfClass in
# Tick is slow". This one says it costs 0.9–1.8 ms (expected 1.4) on the
# calibrated reference hardware, cites the rule's own recorded basis, and
# names the recovery its remediation buys — every number read from
# rule_costs.yaml and the rule catalog. Nothing is invented; when a rule
# has no costed entry we say so instead of estimating.

from __future__ import annotations

import re
from typing import Any

_RULE_ID = re.compile(r"\b([A-Z]{2,3}\d{3})\b")

_NEED_RULE = (
    "Which rule? Name it (e.g. 'why CP006?') or ask from a finding's row "
    "and I'll pick it up from there."
)


def _resolve_rule_id(payload: dict[str, Any]) -> str:
    explicit = str(payload.get("rule_id") or "").strip().upper()
    if explicit:
        return explicit
    finding = payload.get("finding")
    if isinstance(finding, dict) and finding.get("rule_id"):
        return str(finding["rule_id"]).strip().upper()
    match = _RULE_ID.search(str(payload.get("message") or "").upper())
    return match.group(1) if match else ""


def _rule_catalog_entry(rule_id: str) -> tuple[str, str]:
    """(name, explanation) from whichever catalog owns this rule."""
    for module, name_key in (
        ("lod_auditor.rule_metadata", "LOD_RULE_NAMES"),
        ("code_validator.shared._rule_metadata", "RULE_NAMES"),
    ):
        try:
            mod = __import__(module, fromlist=[name_key])
        except ImportError:
            continue
        names = getattr(mod, name_key, {})
        if rule_id in names:
            explain = getattr(mod, "get_rule_explanation", None)
            return names[rule_id], (explain(rule_id) if explain else "")
    return "", ""


def _cost_sentence(rule_id: str) -> tuple[str, dict[str, Any]]:
    """Cost prose + the structured figures, straight from rule_costs.yaml."""
    try:
        from predictive.cost_model.rule_costs import load_rule_costs
    except ImportError:
        return "", {}

    try:
        table = load_rule_costs()
    except Exception:  # noqa: BLE001
        return "", {}

    entry = table.entries.get(rule_id)
    if entry is None:
        return "", {}

    parts: list[str] = []
    for dim, band in entry.dimensions.items():
        unit = "ms/frame" if dim.startswith("cpu") or dim.startswith("gpu") else dim
        parts.append(
            f"{band.get('min', 0)}–{band.get('max', 0)} {unit} "
            f"(expected {band.get('expected', 0)})"
        )
    cost = "; ".join(parts)
    sentence = (
        f"On the calibrated reference hardware ({table.reference_hw}, "
        f"calibration {table.calibration_version}) it costs {cost}, "
        f"{entry.confidence} confidence."
    )
    if entry.basis:
        sentence += f" {entry.basis}"
    if entry.remediation_action:
        sentence += (
            f" Fixing it — {entry.remediation_action} — recovers about "
            f"{entry.recovery_pct:.0f}% of that."
        )
    return sentence, {
        "dimensions": entry.dimensions,
        "confidence": entry.confidence,
        "recovery_pct": entry.recovery_pct,
        "calibration_version": table.calibration_version,
    }


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    rule_id = _resolve_rule_id(payload)
    if not rule_id:
        return {"reply": _NEED_RULE, "rule_id": ""}

    name, explanation = _rule_catalog_entry(rule_id)
    if not name:
        return {
            "reply": (
                f"I don't have {rule_id} in the rule catalog — check the id, "
                "or it may belong to a module this Core edition doesn't ship."
            ),
            "rule_id": rule_id,
        }

    cost_sentence, cost_data = _cost_sentence(rule_id)

    lines = [f"{rule_id} — {name}."]
    if explanation:
        lines.append(explanation)
    if cost_sentence:
        lines.append(cost_sentence)
    else:
        # Honest gap: the rule is real, its performance cost isn't
        # calibrated. Better than inventing a number.
        lines.append(
            "This rule has no calibrated cost entry yet, so I can't put a "
            "figure on its runtime impact."
        )

    return {
        "reply": " ".join(lines),
        "rule_id": rule_id,
        "rule_name": name,
        "cost": cost_data,
    }
