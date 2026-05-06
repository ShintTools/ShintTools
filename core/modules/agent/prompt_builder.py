# core/modules/agent/prompt_builder.py
#
# Sprint C — Fase 3.
#
# Builds the textual prompt fed to the LLM at every iteration of the
# orchestrator loop. The prompt is composed of:
#
#   1. SYSTEM section — who the agent is, the action protocol it must
#      follow, and the catalogue of tools it may call.
#   2. CONTEXT section — initial information the orchestrator wants the
#      LLM to be aware of (e.g. the file path being reviewed). Stays
#      stable across iterations.
#   3. HISTORY section — what has happened so far in this run (each
#      LLM response and the tool result it produced). Grows by one
#      entry per iteration.
#   4. NEXT-ACTION cue — the trailing line that asks the LLM to decide
#      what to do next.
#
# The builder is a pure function-of-state: same inputs -> same output.
# Anything stateful (the iteration counter, the running history) is
# owned by the orchestrator.

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .tool_registry import ToolDefinition

# ── History entries ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AgentHistoryEntry:
    """One past iteration's contribution to the prompt: what the LLM
    said, plus what the tool returned (if any)."""

    iteration_number: int
    llm_raw_response: str
    tool_name_invoked: str | None  # None when the LLM tried to finish
    tool_result_payload: Any | None  # the data or error_message string
    tool_result_was_successful: bool | None


# ── Prompt builder ─────────────────────────────────────────────────────────


_SYSTEM_HEADER = (
    "You are ShintTools' UE5 code-review agent. You help a developer "
    "understand and fix issues found by ShintTools' static analyser in "
    "their Unreal Engine 5 C++ source. You think step by step and you "
    "ALWAYS act through the tools listed below — never invent issues, "
    "never invent code that the tools have not produced for you."
)

_PROTOCOL_INSTRUCTIONS = (
    "PROTOCOL — every reply MUST be a single JSON object on one line.\n"
    "\n"
    'To call a tool:  {"action": "tool_call", "tool": "<tool_name>", '
    '"arguments": {<json args matching the tool schema>}}\n'
    'To finish:       {"action": "finish", "answer": "<your reply to '
    'the developer, in Spanish>"}\n'
    "\n"
    "Rules:\n"
    "- Output ONLY the JSON object. No prose before or after it.\n"
    "- Pick exactly one tool per turn; never chain calls in one reply.\n"
    "- Stop with a 'finish' action as soon as you have enough to answer."
)


def _format_one_tool(tool_definition: ToolDefinition) -> str:
    """Render a single tool entry inside the SYSTEM section."""
    schema_as_json = json.dumps(
        tool_definition.arguments_schema, ensure_ascii=False, indent=2
    )
    return (
        f"### Tool: {tool_definition.tool_name}\n"
        f"Description: {tool_definition.tool_description}\n"
        f"Arguments schema:\n{schema_as_json}"
    )


def _format_history_entry(history_entry: AgentHistoryEntry) -> str:
    """Render one iteration of past activity for the LLM to read on
    the next turn. We keep this compact: full LLM response + a JSON
    line for the tool result. No explanatory text — the LLM is reading
    machine-readable history, not a story."""

    rendered_lines: list[str] = []
    rendered_lines.append(f"--- Iteration {history_entry.iteration_number} ---")
    rendered_lines.append("Assistant:")
    rendered_lines.append(history_entry.llm_raw_response)

    if history_entry.tool_name_invoked is not None:
        result_envelope = {
            "tool": history_entry.tool_name_invoked,
            "success": history_entry.tool_result_was_successful,
        }
        if history_entry.tool_result_was_successful:
            result_envelope["data"] = history_entry.tool_result_payload
        else:
            result_envelope["error"] = history_entry.tool_result_payload

        rendered_lines.append("Tool result:")
        rendered_lines.append(json.dumps(result_envelope, ensure_ascii=False, indent=2))

    return "\n".join(rendered_lines)


def build_agent_prompt(
    *,
    user_request: str,
    initial_context: dict[str, Any],
    registered_tools: list[ToolDefinition],
    history_entries: list[AgentHistoryEntry],
) -> str:
    """Assemble the full prompt for the next LLM call. Pure function:
    no I/O, no model state read.

    Arguments:
        user_request: the original developer's question / task.
        initial_context: stable per-run information (file_path, etc.).
            Serialised as JSON inside the prompt so the LLM can refer
            to specific keys.
        registered_tools: every tool the LLM may call this turn.
        history_entries: past iterations, oldest first. Empty on the
            first call.
    """

    prompt_sections: list[str] = []

    # SYSTEM
    prompt_sections.append(_SYSTEM_HEADER)
    prompt_sections.append(_PROTOCOL_INSTRUCTIONS)
    prompt_sections.append("# Available tools")
    for tool_definition in registered_tools:
        prompt_sections.append(_format_one_tool(tool_definition))

    # CONTEXT
    prompt_sections.append("# Run context")
    prompt_sections.append(json.dumps(initial_context, ensure_ascii=False, indent=2))
    prompt_sections.append("# Developer request")
    prompt_sections.append(user_request)

    # HISTORY
    if history_entries:
        prompt_sections.append("# History so far")
        for one_history_entry in history_entries:
            prompt_sections.append(_format_history_entry(one_history_entry))

    # NEXT ACTION cue — the LLM continues from here.
    prompt_sections.append(
        "# Your next action (respond with the single JSON object now):"
    )

    # Two newlines between sections keeps the boundary visible to the
    # tokenizer without bloating the token count.
    return "\n\n".join(prompt_sections)
