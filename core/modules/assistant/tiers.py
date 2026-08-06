# core/modules/assistant/tiers.py
#
# Capability table for the assistant, per subscription tier.
#
# The assistant is NOT gated as a block (unlike LOD Auditor / Predictive,
# which 403 below Studio). Every tier gets the endpoint; what varies is
# which intents it may run, whether its memory persists, and which model
# profile serves it. Same spirit as code_validator/shared/tiers.py, applied
# to intents instead of rule_ids.

from __future__ import annotations

from typing import Any

# The closed intent menu. This is the whole universe of things the router
# may classify a message into — adding an intent means adding an action
# module under actions/ AND a row here, never teaching the model new verbs.
ALL_INTENTS: frozenset[str] = frozenset(
    {
        "explain_finding",
        "summarize_module",
        "why_rule",
        "simulate_change",
        "define_rule",
        "remember_fact",
        "recall_fact",
        "general_help",
    }
)

_FREE_INTENTS = frozenset({"explain_finding", "general_help"})
_INDIE_INTENTS = _FREE_INTENTS | frozenset({"why_rule", "summarize_module"})

# memory: "none"    — conversation lives only in process memory, discarded
#                     when it expires; nothing written to Mongo.
#         "session" — conversation + summaries persist, but no studio facts.
#         "full"    — everything, including confirmed studio facts and
#                     proactive decision memory.
ASSISTANT_TIERS: dict[str, dict[str, Any]] = {
    "free": {
        "intents": _FREE_INTENTS,
        "memory": "none",
        "model_profile": "light",
        "studio_rules": None,  # not available
    },
    "indie": {
        "intents": _INDIE_INTENTS,
        "memory": "session",
        "model_profile": "light",
        "studio_rules": "llm_evaluated",  # Tier B only
    },
    "studio": {
        "intents": ALL_INTENTS,
        "memory": "full",
        "model_profile": "light",  # flips to "advanced" after the M4 gate
        "studio_rules": "all",  # Tier A + Tier B
    },
}

# Enterprise is a superset of Studio (GH #37 lesson — never gate with
# `!= "studio"`). One shared dict, not a copy, so they cannot drift.
ASSISTANT_TIERS["enterprise"] = ASSISTANT_TIERS["studio"]


def assistant_capabilities(tier: str) -> dict[str, Any]:
    """Capability row for *tier*, defaulting unknown tiers to free."""
    key = (tier or "free").strip().lower()
    return ASSISTANT_TIERS.get(key, ASSISTANT_TIERS["free"])


def allowed_intents_for(tier: str) -> frozenset[str]:
    return assistant_capabilities(tier)["intents"]
