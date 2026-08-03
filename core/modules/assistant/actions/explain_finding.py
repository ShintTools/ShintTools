# core/modules/assistant/actions/explain_finding.py
#
# "Why is this flagged?" — the assistant's first real action.
#
# Resolution order for the finding being asked about:
#   1. Inline `finding` dict in the payload (the UI has the row on screen —
#      the same shape /agent/explain already receives today).
#   2. `context_ref` (an analysis_id returned by a scan) + an optional
#      selector (`rule_id` and/or `asset_path`/`file`) resolved against the
#      analysis_results collection. Ambient context: the user asks about
#      "this finding" and the assistant looks it up — the model never does.
#
# The prose comes from modules/agent's explainer when the LLM is loaded
# (reused, not duplicated — same templates, same cache), and degrades to
# the finding's own deterministic message + fix guidance otherwise (free
# image, model still warming, model unavailable). Degraded is still
# grounded: everything shown came from the rule engine.

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger("shinttools.assistant.explain")

_NEED_TARGET = (
    "I need to know which finding you mean. Run a scan and ask from its "
    "results view, or include the rule id (e.g. 'why LT003 on T_Rock')."
)

_NOT_FOUND = (
    "I couldn't find that finding in the referenced analysis — it may have "
    "expired or the scan may have been re-run. Open the latest results and "
    "ask again from there."
)


async def _resolve_from_analysis(
    analysis_id: str, rule_id: str, asset_path: str
) -> dict[str, Any] | None:
    """Look the finding up in analysis_results; None when unresolvable."""
    try:
        from api.database import analysis_results

        doc = await analysis_results.find_one({"analysis_id": analysis_id})
    except Exception:  # noqa: BLE001 — Mongo best-effort, as everywhere
        return None
    if not doc:
        return None

    issues = doc.get("issues") or doc.get("results") or []
    rule_id = (rule_id or "").strip().upper()
    asset_path = (asset_path or "").strip()

    def _matches(issue: dict) -> bool:
        if rule_id and str(issue.get("rule_id", "")).upper() != rule_id:
            return False
        if asset_path:
            where = str(
                issue.get("asset_path") or issue.get("file") or ""
            )
            if asset_path not in where:
                return False
        return True

    matched = [i for i in issues if isinstance(i, dict) and _matches(i)]
    if not matched:
        return None
    # Deterministic pick: first match in report order — the same order the
    # panel shows. Disambiguation beyond (rule_id, asset_path) is the UI's
    # job; it can always send the finding inline.
    return matched[0]


def _deterministic_reply(finding: dict[str, Any]) -> str:
    """Grounded fallback when no LLM can narrate: the rule's own words."""
    parts: list[str] = []
    name = finding.get("rule_name") or finding.get("rule_id") or "This rule"
    message = finding.get("message") or ""
    parts.append(f"{name}: {message}".strip().rstrip(":"))
    explanation = finding.get("rule_explanation") or ""
    if explanation:
        parts.append(explanation)
    fix = finding.get("fix_suggestion") or finding.get("guidance") or ""
    if fix:
        parts.append(f"Suggested fix: {fix}")
    if finding.get("auto_fixable") is True:
        parts.append("ShintTools' Auto-Fix can apply it for you.")
    return " ".join(p for p in parts if p)


def _llm_reply(finding: dict[str, Any]) -> str | None:
    """Narrate via the existing explainer; None when the LLM can't serve."""
    try:
        from modules.agent.explainer import explain_issue
        from modules.agent.llm_backend import _LLAMA_LOCK, is_loaded
    except ImportError:
        return None  # free image
    if not is_loaded():
        return None
    try:
        with _LLAMA_LOCK:
            text = explain_issue(finding)
        return text or None
    except Exception:  # noqa: BLE001
        logger.exception("explainer failed — degrading to deterministic")
        return None


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    finding = payload.get("finding")
    if not isinstance(finding, dict) or not finding:
        analysis_id = str(payload.get("context_ref") or "").strip()
        if not analysis_id:
            return {"reply": _NEED_TARGET, "resolved": False}
        finding = await _resolve_from_analysis(
            analysis_id,
            str(payload.get("rule_id") or ""),
            str(payload.get("asset_path") or payload.get("file") or ""),
        )
        if finding is None:
            return {"reply": _NOT_FOUND, "resolved": False}

    # Inference is blocking CPU work; keep the event loop responsive the
    # same way /agent/explain does.
    text = await asyncio.to_thread(_llm_reply, finding)
    degraded = text is None
    if degraded:
        text = _deterministic_reply(finding)

    return {
        "reply": text,
        "resolved": True,
        "degraded": degraded,
        "rule_id": finding.get("rule_id", ""),
    }
