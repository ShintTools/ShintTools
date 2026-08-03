# core/modules/assistant/actions/define_rule.py
#
# "New rule: never use TCHAR_TO_ANSI in headers."
#
# Same contract as memory: the action creates a DRAFT and asks for
# confirmation — a rule never runs in anyone's scan until the user
# activates it. The reply spells out how the rule was understood
# (template + parameters, or LLM-evaluated) so what gets confirmed is
# exactly what will execute.

from __future__ import annotations

from typing import Any

from .. import rule_compiler, rule_store
from ..rule_templates import TEMPLATES

_EMPTY = (
    "Describe the rule — e.g. 'new rule: never use TCHAR_TO_ANSI in "
    "headers' or 'all .uasset tests must live under Content/Tests'."
)


def _describe(compiled: dict[str, Any]) -> str:
    if compiled["tier"] == "template":
        template = compiled["template"]
        label = TEMPLATES[template["template_id"]]["label"]
        params = {
            k: v for k, v in template["params"].items() if not k.startswith("_")
        }
        rendered = ", ".join(f"{k}={v}" for k, v in params.items())
        return (
            f"I understood it as a deterministic '{label}' rule "
            f"({rendered}). It will run on every scan at zero cost."
        )
    return (
        "I couldn't map it to a deterministic template, so it will be "
        "evaluated by the local model against relevant files (cached — an "
        "unchanged file is never re-checked)."
    )


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    message = str(payload.get("message") or "").strip()
    if not message or len(message.split()) < 3:
        return {"reply": _EMPTY, "rule_id": ""}

    compiled = rule_compiler.compile_rule(message)
    body = (
        compiled["template"]
        if compiled["tier"] == "template"
        else {"description": message, "example_violation": "", "example_ok": ""}
    )

    engine = str(payload.get("engine") or "both").strip().lower() or "both"
    rule = await rule_store.create_rule(
        str(payload.get("studio_id") or ""),
        str(payload.get("project_id") or ""),
        message[:80],
        compiled["tier"],
        {"engine": engine, "applies_to": []},
        body,
        source_conversation_id=str(payload.get("conversation_id") or ""),
    )

    return {
        "reply": (
            f"Draft rule created. {_describe(compiled)} "
            "Confirm it in the Rules panel and it starts enforcing on the "
            "next scan."
        ),
        "rule_id": rule["rule_id"],
        "rule_tier": compiled["tier"],
        "rule_status": "draft",
    }
