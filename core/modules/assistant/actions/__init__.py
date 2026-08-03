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

from . import (
    define_rule,
    explain_finding,
    recall_fact,
    remember_fact,
    simulate_change,
    summarize_module,
    why_rule,
)

ActionFn = Callable[[dict], Any]

# Every intent on the menu now has a deterministic action behind it.
ACTIONS: dict[str, ActionFn] = {
    "explain_finding": explain_finding.run,
    "summarize_module": summarize_module.run,
    "why_rule": why_rule.run,
    "simulate_change": simulate_change.run,
    "define_rule": define_rule.run,
    "remember_fact": remember_fact.run,
    "recall_fact": recall_fact.run,
}

__all__ = ["ACTIONS"]
