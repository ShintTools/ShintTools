# core/modules/assistant/actions/summarize_module.py
#
# "How bad is it?" — an aggregate over a persisted analysis.
#
# Reads the stored report by context_ref and counts; it does not re-run
# any scan and does not ask the model to summarise raw findings (a 1.5B
# asked to digest 400 rows invents). Severity counts, the worst offenders
# by frequency and any studio-rule violations are computed here, and the
# sentence is assembled from those numbers.

from __future__ import annotations

from collections import Counter
from typing import Any

_NEED_REF = (
    "Run a scan first — then ask from its results and I'll summarise what "
    "it found."
)

_NOT_FOUND = (
    "I couldn't find that analysis; it may have been superseded by a newer "
    "scan. Open the latest results and ask again."
)


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    analysis_id = str(payload.get("context_ref") or "").strip()
    if not analysis_id:
        return {"reply": _NEED_REF, "resolved": False}

    try:
        from api.database import analysis_results

        doc = await analysis_results.find_one({"analysis_id": analysis_id})
    except Exception:  # noqa: BLE001
        doc = None
    if not doc:
        return {"reply": _NOT_FOUND, "resolved": False}

    issues = [i for i in (doc.get("issues") or []) if isinstance(i, dict)]
    if not issues:
        return {
            "reply": "That scan came back clean — nothing was flagged.",
            "resolved": True,
            "total": 0,
        }

    severities = Counter(str(i.get("severity", "info")) for i in issues)
    by_rule = Counter(
        f"{i.get('rule_id', '?')} ({i.get('rule_name', '')})".strip()
        for i in issues
    )
    studio_hits = sum(1 for i in issues if i.get("source") == "studio_rule")

    head = (
        f"{len(issues)} findings in that scan: "
        + ", ".join(
            f"{count} {sev}" for sev, count in severities.most_common()
        )
        + "."
    )
    top = "; ".join(f"{name} x{count}" for name, count in by_rule.most_common(3))
    lines = [head, f"Most frequent: {top}."]
    if studio_hits:
        lines.append(
            f"{studio_hits} of them come from your own team rules."
        )

    return {
        "reply": " ".join(lines),
        "resolved": True,
        "total": len(issues),
        "severities": dict(severities),
        "studio_rule_hits": studio_hits,
    }
