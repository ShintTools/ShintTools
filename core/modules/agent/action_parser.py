# core/modules/agent/action_parser.py
#
# Sprint C — Fase 3.
#
# Turns whatever the LLM says into a structured ParsedAction the
# orchestrator can act on. DeepSeek Coder 1.3B does not have native
# function calling, so we instruct it (in prompt_builder.py) to emit
# a single-line JSON object and parse it here.
#
# The parser is intentionally TOLERANT:
#   - Code fences around the JSON are stripped.
#   - Leading / trailing prose ("Sure, I'll call ... :") is ignored;
#     we look for the last balanced {...} block in the text.
#   - Missing or malformed JSON is converted to a "finish" action with
#     the raw text as the answer, never an exception.
#
# Why tolerant: a hard failure here would force the orchestrator to
# crash the request; a soft fallback lets the model still produce
# *something* useful even when its output is messy.

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class AgentActionKind(str, Enum):
    """The two things an agent's response can be: a request to invoke
    a tool, or a final answer to the user."""

    TOOL_CALL = "tool_call"
    FINISH = "finish"


@dataclass(frozen=True)
class ParsedAction:
    """Structured form of an LLM response. Exactly one of the
    (tool_name, tool_arguments) / (final_answer) pairs is populated
    depending on `kind`."""

    kind: AgentActionKind

    # Populated when kind == TOOL_CALL:
    tool_name: Optional[str] = None
    tool_arguments: Optional[dict[str, Any]] = None

    # Populated when kind == FINISH:
    final_answer: Optional[str] = None

    # Always present — useful for debugging and for recording in the
    # AgentStep history what the LLM literally produced.
    raw_llm_response: str = ""

    @classmethod
    def tool_call(
        cls,
        *,
        tool_name: str,
        tool_arguments: dict[str, Any],
        raw_llm_response: str,
    ) -> "ParsedAction":
        return cls(
            kind=AgentActionKind.TOOL_CALL,
            tool_name=tool_name,
            tool_arguments=tool_arguments,
            raw_llm_response=raw_llm_response,
        )

    @classmethod
    def finish(cls, *, final_answer: str, raw_llm_response: str) -> "ParsedAction":
        return cls(
            kind=AgentActionKind.FINISH,
            final_answer=final_answer,
            raw_llm_response=raw_llm_response,
        )


# ── Parser ─────────────────────────────────────────────────────────────────


def _strip_code_fences(possibly_fenced_text: str) -> str:
    """Remove leading / trailing ```...``` fences if present, leaving
    only the content. Handles ```json, ```JSON, plain ``` and the
    occasional ~~~~ variant."""

    stripped_text = possibly_fenced_text.strip()
    if not stripped_text:
        return stripped_text

    fence_markers = ("```", "~~~")
    for fence_marker in fence_markers:
        if stripped_text.startswith(fence_marker):
            fence_marker_length = len(fence_marker)
            without_open_fence = stripped_text[fence_marker_length:]
            # The line right after the opening fence may name the
            # language ("json"); we drop it.
            newline_position = without_open_fence.find("\n")
            if newline_position >= 0:
                content_start_index = newline_position + 1
                without_open_fence = without_open_fence[content_start_index:]
            if without_open_fence.endswith(fence_marker):
                trim_to_index = -fence_marker_length
                without_open_fence = without_open_fence[:trim_to_index]
            return without_open_fence.strip()

    return stripped_text


def _find_last_balanced_json_object(arbitrary_text: str) -> Optional[str]:
    """Scan from right to left looking for a balanced {...} block.
    Returns the substring on success, or None if no balanced block is
    found. We scan from the right because the LLM tends to place its
    JSON action AT THE END of an explanation, not the beginning."""

    closing_brace_index = arbitrary_text.rfind("}")
    while closing_brace_index >= 0:
        # Walk left from this } counting brace depth until we hit zero.
        brace_depth = 0
        in_string_literal = False
        escape_next_character = False
        for scan_index in range(closing_brace_index, -1, -1):
            current_character = arbitrary_text[scan_index]

            if escape_next_character:
                escape_next_character = False
                continue
            if current_character == "\\":
                escape_next_character = True
                continue
            if current_character == '"' and not escape_next_character:
                in_string_literal = not in_string_literal
                continue
            if in_string_literal:
                continue

            if current_character == "}":
                brace_depth += 1
            elif current_character == "{":
                brace_depth -= 1
                if brace_depth == 0:
                    block_end_index = closing_brace_index + 1
                    candidate_block = arbitrary_text[scan_index:block_end_index]
                    return candidate_block

        # No balance from this closing brace; try the previous } if any.
        closing_brace_index = arbitrary_text.rfind("}", 0, closing_brace_index)

    return None


def _coerce_to_parsed_action(
    decoded_payload: dict[str, Any],
    raw_llm_response: str,
) -> Optional[ParsedAction]:
    """Validate the JSON shape and convert to a ParsedAction.
    Returns None if the payload doesn't match either expected schema."""

    declared_action = decoded_payload.get("action")

    if declared_action == AgentActionKind.TOOL_CALL.value:
        tool_name_value = decoded_payload.get("tool")
        tool_arguments_value = decoded_payload.get("arguments", {})
        if not isinstance(tool_name_value, str) or not tool_name_value:
            return None
        if not isinstance(tool_arguments_value, dict):
            return None
        return ParsedAction.tool_call(
            tool_name=tool_name_value,
            tool_arguments=tool_arguments_value,
            raw_llm_response=raw_llm_response,
        )

    if declared_action == AgentActionKind.FINISH.value:
        final_answer_value = decoded_payload.get("answer")
        if not isinstance(final_answer_value, str):
            return None
        return ParsedAction.finish(
            final_answer=final_answer_value,
            raw_llm_response=raw_llm_response,
        )

    return None


def parse_llm_response(raw_llm_response: str) -> ParsedAction:
    """Convert an LLM's free-form text into a ParsedAction.

    Order of attempts:
      1. Strip code fences and try to parse the whole thing as JSON.
      2. If that fails, find the last balanced {...} block in the text
         and try to parse THAT as JSON.
      3. If neither works, fall back to a FINISH action carrying the
         raw text as the final answer (best-effort: don't crash).
    """

    # Attempt 1: whole text after removing code fences.
    candidate_after_fence_strip = _strip_code_fences(raw_llm_response)
    try:
        decoded_payload = json.loads(candidate_after_fence_strip)
        if isinstance(decoded_payload, dict):
            parsed = _coerce_to_parsed_action(
                decoded_payload, raw_llm_response=raw_llm_response
            )
            if parsed is not None:
                return parsed
    except json.JSONDecodeError:
        pass

    # Attempt 2: greedy last-balanced-block.
    last_balanced_block = _find_last_balanced_json_object(raw_llm_response)
    if last_balanced_block is not None:
        try:
            decoded_payload = json.loads(last_balanced_block)
            if isinstance(decoded_payload, dict):
                parsed = _coerce_to_parsed_action(
                    decoded_payload, raw_llm_response=raw_llm_response
                )
                if parsed is not None:
                    return parsed
        except json.JSONDecodeError:
            pass

    # Fallback: treat the raw text as the final answer.
    return ParsedAction.finish(
        final_answer=raw_llm_response.strip(),
        raw_llm_response=raw_llm_response,
    )
