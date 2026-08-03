# core/modules/assistant/actions/__init__.py
#
# The fixed action catalog. One deterministic Python entry point per
# intent — the assistant's whole "agency" lives in this dispatch table,
# the same way lod_orchestrator's rule registries hold the auditor's.
#
# Contract for every action:
#   run(payload: dict) -> dict with at least {"reply": str}
#   - never raises on missing data; says honestly what it needs instead
#   - computes with deterministic code; the LLM (if used at all) only
#     narrates over the computed result

from __future__ import annotations

from typing import Any, Callable

from . import explain_finding, recall_fact, remember_fact

ActionFn = Callable[[dict], Any]

# Intents without a shipped action fall through to the route's honest
# "not wired up yet" reply — never a fake answer.
ACTIONS: dict[str, ActionFn] = {
    "explain_finding": explain_finding.run,
    "remember_fact": remember_fact.run,
    "recall_fact": recall_fact.run,
}

__all__ = ["ACTIONS"]
