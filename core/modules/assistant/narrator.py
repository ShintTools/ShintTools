# core/modules/assistant/narrator.py
#
# Conversational narration: the model's ONE job per turn, now with the
# thread it is part of.
#
# The existing explainer answers a single finding in isolation and caches
# the result by that finding's hash. That is exactly right for "explain
# this row" and exactly wrong for a follow-up: the same finding asked about
# twice must not replay a cached paragraph when the second question was
# "and why does that matter for a 30 Hz target?". So a turn with history
# takes this path instead — same model, same lock, no cache.
#
# What does NOT change is the contract. The grounded block handed in here
# is already computed by a deterministic action; the model rewords and
# connects it to the question. It cannot fetch anything, and nothing it
# writes chooses what happens next.
#
# The prompt is deliberately NOT the explainer's registry template: that
# one's shared prefix is tuned to be byte-identical across requests so
# llama.cpp reuses its KV cache, and a per-conversation history block would
# break that prefix for every caller. Two prompts, two purposes.

from __future__ import annotations

import logging
from typing import Any, Iterator

logger = logging.getLogger("shinttools.assistant.narrator")

MAX_ANSWER_TOKENS = 320

_SYSTEM = (
    "You are the ShintTools assistant, embedded in a game developer's "
    "editor. You answer questions about analysis results the engine has "
    "already produced.\n"
    "Rules you always follow:\n"
    "- Ground every claim in the DATA block. If the data does not answer "
    "the question, say precisely what is missing.\n"
    "- Never invent rule ids, file paths, thresholds or measurements.\n"
    "- Continue the conversation naturally: the user can refer to things "
    "discussed earlier without repeating them.\n"
    "- Be concise and concrete. No preamble, no sign-off, no bullet lists "
    "unless the user asked for a list."
)


def build_prompt(question: str, data_block: str, history: str = "") -> str:
    """Assemble the conversational prompt. Pure — tests call it directly."""
    sections = [_SYSTEM]
    if history:
        sections.append("CONVERSATION SO FAR:\n" + history)
    sections.append("DATA (already computed by the analysis engine):\n" + data_block)
    sections.append(f"USER: {question}\nASSISTANT:")
    return "\n\n".join(sections)


def _backend():
    """The LLM backend, or None when it cannot serve this request."""
    try:
        from modules.agent import llm_backend
    except ImportError:
        return None  # free image — modules/agent is stripped
    if not llm_backend.is_loaded():
        return None
    return llm_backend


def narrate(question: str, data_block: str, history: str = "") -> str | None:
    """Blocking narration. Returns None when the model cannot serve, so the
    caller degrades to its deterministic text rather than failing."""
    backend = _backend()
    if backend is None:
        return None

    prompt = build_prompt(question, data_block, history)
    try:
        with backend._LLAMA_LOCK:
            text = backend.generate(
                prompt, max_tokens=MAX_ANSWER_TOKENS, temperature=0.2
            )
    except Exception:  # noqa: BLE001 — a turn must survive an inference failure
        logger.exception("narration failed — degrading to deterministic text")
        return None

    text = (text or "").strip()
    return text or None


def narrate_stream(
    question: str, data_block: str, history: str = ""
) -> Iterator[str]:
    """Token-by-token narration for the SSE endpoint.

    Deliberately does NOT take ``_LLAMA_LOCK``: the streaming caller runs
    this inside _aiter_in_thread, which holds the lock for the whole
    generation. Taking it here would deadlock on the plain (non-reentrant)
    lock the backend uses.

    Raises RuntimeError when no model can serve — the caller decides
    whether that is an error event or a fallback to deterministic text.
    """
    backend = _backend()
    if backend is None:
        raise RuntimeError("No local model is loaded.")
    yield from backend.generate_stream(
        build_prompt(question, data_block, history),
        max_tokens=MAX_ANSWER_TOKENS,
        temperature=0.2,
    )


def finding_data_block(finding: dict[str, Any]) -> str:
    """Render a finding as the DATA block — only fields the engine set.

    Every line is a value the rule engine produced; there is nothing here
    for the model to fill in, which is the point.
    """
    fields = (
        ("Rule", finding.get("rule_id")),
        ("Name", finding.get("rule_name")),
        ("Severity", finding.get("severity")),
        ("Where", finding.get("asset_path") or finding.get("file")),
        ("Line", finding.get("line")),
        ("Message", finding.get("message")),
        ("Why it is a rule", finding.get("rule_explanation")),
        ("Suggested fix", finding.get("fix_suggestion") or finding.get("guidance")),
        ("Auto-fixable", finding.get("auto_fixable")),
    )
    lines = [
        f"{label}: {value}"
        for label, value in fields
        if value not in (None, "", [], {})
    ]
    return "\n".join(lines) if lines else "(no structured data available)"
