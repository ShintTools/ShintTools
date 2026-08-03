# core/modules/assistant/__init__.py
#
# Native AI assistant — conversational layer over the deterministic Core.
#
# Architecture contract (decided up front, see docs/assistant/ARCHITECTURE.md
# once M7 lands): the LLM never free-form tool-calls. Every turn is
#
#     classify intent (closed menu, grammar-constrained)
#       -> run ONE deterministic Python action from a fixed catalog
#       -> LLM writes the final prose over data the action already computed
#
# This is the generalisation of the pattern that already works in this Core
# (explainer.py, custom_rule_checker.py): detection and computation stay
# deterministic; the model only narrates. The earlier tool-calling agent was
# removed for good reason (see modules/agent/__init__.py) — this module is
# the "build it from scratch with the right contract" that note asked for.
#
# Unlike modules/agent (paid image only), this package ships in BOTH
# editions: the assistant serves every tier, degraded on Free (no LLM in the
# free image -> deterministic keyword routing + deterministic answers).

from .conversation_store import (
    append_turn,
    get_conversation,
    start_conversation,
)
from .tiers import allowed_intents_for, assistant_capabilities

__all__ = [
    "append_turn",
    "get_conversation",
    "start_conversation",
    "allowed_intents_for",
    "assistant_capabilities",
]
