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
) -> tuple[dict[str, Any] | None, str]:
    """Look the finding up in analysis_results.

    Returns (finding, error). Exactly one is meaningful: a finding when the
    selector identifies one, otherwise a sentence explaining what is missing.

    This used to return ``matched[0]`` whenever anything matched — and with no
    selector at all, EVERY issue matches, so it returned the first row of the
    analysis. A question that named no target got a confident answer about
    whichever finding happened to sort first: ask "why does this rule exist?"
    with a LOD audit in the panel and you were told about a mesh. Nothing in
    the reply admitted a choice had been made.

    Picking blind is the one thing this action must not do. Unselected, it now
    asks which one — losing a turn to a question is strictly better than
    answering the wrong one convincingly.
    """
    try:
        from api.database import analysis_results

        doc = await analysis_results.find_one({"analysis_id": analysis_id})
    except Exception:  # noqa: BLE001 — Mongo best-effort, as everywhere
        return None, _NOT_FOUND
    if not doc:
        return None, _NOT_FOUND

    issues = [
        i for i in (doc.get("issues") or doc.get("results") or [])
        if isinstance(i, dict)
    ]
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

    matched = [i for i in issues if _matches(i)]
    if not matched:
        return None, _NOT_FOUND

    # A selector narrowed it down: first in report order is the same order the
    # panel shows, and finer disambiguation is the UI's job — it can always
    # send the finding inline.
    if rule_id or asset_path:
        return matched[0], ""

    # No selector. One finding in the whole scan is unambiguous anyway;
    # anything more and we ask rather than guess.
    if len(matched) == 1:
        return matched[0], ""
    return None, _ambiguous_reply(matched)


def _ambiguous_reply(matched: list[dict[str, Any]]) -> str:
    """Name the likeliest candidates instead of picking one of them.

    Ranked by frequency: the rule firing most often is the one a vague "why is
    this flagged?" is most likely to be about, and it also tells the user
    something true about the scan on its way past.
    """
    from collections import Counter

    counts = Counter(
        (
            str(i.get("rule_id") or "?"),
            str(i.get("rule_name") or ""),
        )
        for i in matched
    )
    named = "; ".join(
        f"{rid}{f' ({name})' if name else ''} x{n}"
        for (rid, name), n in counts.most_common(3)
    )
    return (
        f"That scan has {len(matched)} findings, so I'd be guessing which one "
        f"you mean. The most frequent are: {named}. Name a rule id, or click "
        f"Explain on the row you're looking at and I'll pick it up from there."
    )


def deterministic_reply(finding: dict[str, Any]) -> str:
    """Grounded fallback when no LLM can narrate: the rule's own words.

    Public because the streaming endpoint needs it too — when a generation
    dies mid-sentence the panel gets this instead of a truncated fragment.
    """
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


async def prepare(payload: dict[str, Any]) -> dict[str, Any]:
    """Resolve WHICH finding this turn is about, before any inference.

    Split out of run() so the streaming endpoint can do the lookup (and
    fail fast with a clean error) before it opens a token stream. Returns
    {"finding": dict} on success or {"error": str} when the target could
    not be established.
    """
    finding = payload.get("finding")
    if isinstance(finding, dict) and finding:
        return {"finding": finding}

    # Resolve WHICH analysis first. A context_ref belonging to a different
    # module than the one the message names is not grounding for this
    # question — see module_resolver.resolve_analysis.
    from ..module_resolver import resolve_analysis, resolve_module

    module, source = resolve_module(
        str(payload.get("message") or ""),
        str(payload.get("module_context") or ""),
    )

    doc, _ = await resolve_analysis(
        module, str(payload.get("context_ref") or "").strip(), source
    )
    if doc is None:
        return {"error": _NEED_TARGET}

    finding, error = await _resolve_from_analysis(
        str(doc.get("analysis_id") or ""),
        str(payload.get("rule_id") or ""),
        str(payload.get("asset_path") or payload.get("file") or ""),
    )
    if finding is None:
        return {"error": error or _NOT_FOUND}
    return {"finding": finding}


def _conversational_reply(
    finding: dict[str, Any], question: str, history: str
) -> str | None:
    """Narrate this finding as part of an ongoing thread.

    Bypasses the explainer's cache deliberately: that cache is keyed on the
    finding alone, so a follow-up about the same row would replay the
    answer to the FIRST question. Same model, same lock, no cache.
    """
    from .. import narrator

    return narrator.narrate(
        question, narrator.finding_data_block(finding), history
    )


def stream_text(
    finding: dict[str, Any], question: str, history: str
) -> Any:
    """Sync generator of text chunks, for the SSE endpoint.

    Runs inside _aiter_in_thread, which already holds the model lock — see
    narrator.narrate_stream for why this must not take it again.
    """
    from .. import narrator

    if history:
        return narrator.narrate_stream(
            question, narrator.finding_data_block(finding), history
        )
    from modules.agent.explainer import explain_issue_stream

    return explain_issue_stream(finding)


def _is_module_level_question(payload: dict[str, Any]) -> bool:
    """The message names a module and no particular finding.

    Then it is a question ABOUT THE MODULE, whatever the router called it.
    "Show me the code validator results" gets classified explain_finding often
    enough — it does read like a request about findings — and answering it by
    asking which of 360 findings was meant is technically honest and
    practically useless. The user named the module; answer about the module.

    Deliberately narrow: only when the module came from the MESSAGE (not the
    ambient panel, which is always set) and no selector is present. An Explain
    click always carries a selector, so it never lands here.
    """
    from ..module_resolver import resolve_module

    if str(payload.get("rule_id") or "").strip():
        return False
    if str(payload.get("asset_path") or payload.get("file") or "").strip():
        return False
    if isinstance(payload.get("finding"), dict) and payload["finding"]:
        return False

    module, source = resolve_module(
        str(payload.get("message") or ""),
        str(payload.get("module_context") or ""),
    )
    return module is not None and source == "message"


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    if _is_module_level_question(payload):
        from . import summarize_module

        return await summarize_module.run(payload)

    prepared = await prepare(payload)
    if "error" in prepared:
        return {"reply": prepared["error"], "resolved": False}
    finding = prepared["finding"]

    history = str(payload.get("history") or "")

    # Inference is blocking CPU work; keep the event loop responsive the
    # same way /agent/explain does.
    if history:
        text = await asyncio.to_thread(
            _conversational_reply,
            finding,
            str(payload.get("message") or ""),
            history,
        )
    else:
        text = await asyncio.to_thread(_llm_reply, finding)

    degraded = text is None
    if degraded:
        text = deterministic_reply(finding)

    return {
        "reply": text,
        "resolved": True,
        "degraded": degraded,
        "rule_id": finding.get("rule_id", ""),
    }
