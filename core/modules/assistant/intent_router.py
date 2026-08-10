# core/modules/assistant/intent_router.py
#
# Closed-menu intent classification — the assistant's only "decision" step.
#
# Four layers, in order of preference:
#
#   1. The UI declared the intent (an Explain button knows what it is).
#      The router is never consulted; this file isn't even imported.
#   2. Explicit performative markers ("new rule:", "recuerda que"). The user
#      named the OPERATION, not the topic — there is nothing left to infer.
#   3. LLM classification, grammar-constrained (GBNF). The model cannot
#      emit anything outside the intent enum — the failure mode that killed
#      the old tool-calling agent ("ask for JSON and hope") is structurally
#      impossible, because off-menu tokens are never candidates.
#   4. Deterministic keyword routing. The only layer on the free image
#      (no modules/agent there) and the fallback when the model isn't
#      loaded. Deliberately conservative: unmatched -> general_help.
#
# The router classifies; it never extracts arguments. rule_id, analysis_id
# and file paths come from the request's context fields, which the UI
# already knows — a classification cannot invent a target.

from __future__ import annotations

import logging
import re

from .tiers import ROUTABLE_INTENTS

logger = logging.getLogger("shinttools.assistant.router")

# GBNF over the exact intent enum. Rebuilt from ROUTABLE_INTENTS at import
# time so the grammar cannot drift from the capability table.
#
# ROUTABLE_INTENTS, not ALL_INTENTS: confirm_pending is reachable only once
# Python has established that the previous turn left a proposal open. A
# token the model can emit is a token the model will eventually emit on the
# wrong message, and that one would commit a stored decision.
INTENT_GRAMMAR: str = "root ::= " + " | ".join(
    f'"{intent}"' for intent in sorted(ROUTABLE_INTENTS)
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
    return intent if intent in ROUTABLE_INTENTS else None


# ── Layer 0: the user named the operation ────────────────────────────────────
#
# Performatives, not topic vocabulary: "new rule:" IS the request to create a
# rule, the way "Explain" on a row IS explain_finding. Nothing about the rest
# of the sentence can change that, so nothing about it gets a vote.
#
# This layer exists because the keyword table below — the only place that ever
# knew these phrases — runs ONLY when the LLM cannot serve. With a model
# loaded it never ran, so "nueva regla: convención de nombres para los
# widgets" went to the 1.5B, came back summarize_module (the sentence does
# mention naming), and the assistant answered with the previous naming scan.
# From the user's side the assistant had ignored the rule and replayed an old
# answer — which is exactly what it had done.
#
# Kept deliberately short. Every entry must be a phrase whose ONLY reading is
# "perform this operation"; topic words like "lod" or "naming" are precisely
# what must not be in here.
_EXPLICIT_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("define_rule", ("new rule", "nueva regla", "add a rule",
                     "crea una regla", "define una regla", "convention:")),
    ("remember_fact", ("remember that", "recuerda que", "apunta que")),
)


def classify_explicit(message: str) -> str | None:
    """The intent the user named outright, or None to keep classifying."""
    lowered = (message or "").lower()
    for intent, markers in _EXPLICIT_MARKERS:
        if any(m in lowered for m in markers):
            return intent
    return None


_RULE_ID_RE = re.compile(r"\b[A-Z]{2,4}\d{3}\b")


def _names_a_module_only(message: str) -> bool:
    """True when the message is about a MODULE rather than one finding.

    Naming a module and no rule id is a question about that module's results:
    "how is the code validator doing?", "share the code validator results".

    A message that names an operation outright is never "about a module",
    however many module words it happens to contain — a rule is usually
    ABOUT naming or LODs, so the aliases fire on the rule's own subject.
    Layer 0 already returned by the time this runs; the guard states the
    precedence so a future reordering cannot quietly resurrect the bug.
    """
    from .module_registry import ALIASES

    if classify_explicit(message) is not None:
        return False
    if _RULE_ID_RE.search(message or ""):
        return False   # names a specific rule — that is a finding question
    lowered = (message or "").lower()
    return any(alias in lowered for alias, _ in ALIASES)


def classify(message: str) -> tuple[str, str]:
    """Classify *message*; returns (intent, source).

    source: "explicit" | "llm" | "keywords" | "llm+module" — surfaced in logs
    so the M4 golden-set harness can measure each layer separately.
    """
    explicit = classify_explicit(message)
    if explicit is not None:
        logger.info("router: intent=%s source=explicit", explicit)
        return explicit, "explicit"

    intent = _classify_by_llm(message)
    if intent is not None:
        # Deterministic correction over the model's answer.
        #
        # Module awareness was added to the keyword layer, but the keyword
        # layer only runs when the LLM cannot — so with a model loaded it
        # never ran, and "share the results view of code validator" came back
        # as explain_finding. The action then asked which of 360 findings the
        # user meant, to a question that had named no finding at all.
        #
        # The model is not wrong to hesitate here; the phrasing does mention
        # findings. But "a module and no rule id" is decidable in Python, and
        # anything decidable in Python does not get delegated to a 1.5B — the
        # same principle that keeps argument extraction out of the model.
        if intent == "explain_finding" and _names_a_module_only(message):
            logger.info("router: explain_finding -> summarize_module (module named)")
            return "summarize_module", "llm+module"
        return intent, "llm"
    return classify_by_keywords(message), "keywords"
