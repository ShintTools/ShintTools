# core/modules/assistant/intent_router.py
#
# Closed-menu intent classification — the assistant's only "decision" step.
#
# Three layers, in order of preference:
#
#   1. The UI declared the intent (an Explain button knows what it is).
#      The router is never consulted; this file isn't even imported.
#   2. LLM classification, grammar-constrained (GBNF). The model cannot
#      emit anything outside the intent enum — the failure mode that killed
#      the old tool-calling agent ("ask for JSON and hope") is structurally
#      impossible, because off-menu tokens are never candidates.
#   3. Deterministic keyword routing. The only layer on the free image
#      (no modules/agent there) and the fallback when the model isn't
#      loaded. Deliberately conservative: unmatched -> general_help.
#
# The router classifies; it never extracts arguments. rule_id, analysis_id
# and file paths come from the request's context fields, which the UI
# already knows — a classification cannot invent a target.

from __future__ import annotations

import logging

from .tiers import ALL_INTENTS

logger = logging.getLogger("shinttools.assistant.router")

# GBNF over the exact intent enum. Rebuilt from ALL_INTENTS at import time
# so the grammar cannot drift from the capability table.
INTENT_GRAMMAR: str = "root ::= " + " | ".join(
    f'"{intent}"' for intent in sorted(ALL_INTENTS)
)

_ROUTER_PROMPT = """You are an intent classifier for a game-development \
assistant. Classify the user's message into exactly one intent id.

The assistant has these analysis modules: Code Validator, Asset Naming Bot,
LOD Auditor, Predictive Profiler. A message that asks how one of them is
doing, or what it found, is summarize_module.

Intents:
  explain_finding  — asks why a specific issue/finding was reported, or what it means
  summarize_module — asks for an overview/summary of scan results, or about a module
  why_rule         — asks why a rule exists, its cost, or its rationale
  simulate_change  — asks what would happen if something were changed/fixed
  define_rule      — wants to create or change a team rule/convention
  remember_fact    — states a team decision/preference to remember
  recall_fact      — asks what was decided/remembered before
  general_help     — greetings, capabilities, anything else

Message: {message}
Intent:"""

# Keyword table for layer 3. Spanish + English because studio chat is
# bilingual in practice. First hit wins; order = specificity.
_KEYWORD_ROUTES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("simulate_change", ("what if", "que pasaria", "qué pasaría", "simulate",
                         "simula", "if i fix", "si arreglo", "si cambio")),
    ("define_rule", ("new rule", "nueva regla", "add a rule", "crea una regla",
                     "define una regla", "convention:", "prohibir", "forbid")),
    # recall before remember: the question forms ("qué decidimos", "te
    # acuerdas") contain the bare statement needle ("decidimos") and must
    # win over it.
    ("recall_fact", ("what did we decide", "que decidimos", "qué decidimos",
                     "do you remember", "te acuerdas", "recuerdas")),
    ("remember_fact", ("remember that", "recuerda que", "we decided",
                       "hemos decidido", "decidimos", "apunta que")),
    ("why_rule", ("why does this rule", "why is this a rule", "por que esta regla",
                  "por qué esta regla", "why rule", "rationale", "coste de la regla")),
    ("summarize_module", ("summary", "summarize", "resumen", "resume",
                          "overview", "how bad is", "estado general")),
    ("explain_finding", ("explain", "explica", "why is this flagged",
                         "por que sale", "por qué sale", "what does this mean",
                         "que significa", "qué significa", "this finding",
                         "este finding", "este issue", "este warning")),
)


def classify_by_keywords(message: str) -> str:
    lowered = (message or "").lower()
    for intent, needles in _KEYWORD_ROUTES:
        if any(n in lowered for n in needles):
            return intent

    # Naming a module IS a request about that module's results. The table
    # above had no module name in it at all, so "how is the code validator
    # doing?" matched nothing and fell through to general_help — the
    # assistant's stock capabilities blurb, in answer to a specific question
    # about a specific module. Checked last so an explicit verb still wins:
    # "why does LT003 exist?" is why_rule even though it says LOD.
    from .module_registry import ALIASES

    if any(alias in lowered for alias, _ in ALIASES):
        return "summarize_module"

    return "general_help"


def _classify_by_llm(message: str) -> str | None:
    """Grammar-constrained classification; None when the LLM can't serve."""
    try:
        from modules.agent.llm_backend import _LLAMA_LOCK, generate, is_loaded
    except ImportError:
        return None  # free image — modules/agent stripped
    if not is_loaded():
        return None

    try:
        with _LLAMA_LOCK:
            raw = generate(
                _ROUTER_PROMPT.format(message=message[:2000]),
                max_tokens=8,
                temperature=0.0,
                stop=[],
                grammar_str=INTENT_GRAMMAR,
            )
    except Exception:  # noqa: BLE001 — inference failure must not kill the turn
        logger.exception("intent classification failed — falling back")
        return None

    intent = raw.strip()
    return intent if intent in ALL_INTENTS else None


def classify(message: str) -> tuple[str, str]:
    """Classify *message*; returns (intent, source).

    source: "llm" | "keywords" — surfaced in logs so the M4 golden-set
    harness can measure each layer separately.
    """
    intent = _classify_by_llm(message)
    if intent is not None:
        return intent, "llm"
    return classify_by_keywords(message), "keywords"
