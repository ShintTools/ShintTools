# core/modules/agent/tool_implementations.py
#
# Sprint C — Fase 2.
#
# Concrete tools the LLM agent can invoke. Each function is a thin
# adapter over an existing ShintTools capability (the static analysers,
# the auto-fixer, etc.) wrapped in the standard ToolExecutionResult
# shape so the orchestrator can treat every tool uniformly.
#
# Adding a new tool:
#   1. Write a function with explicit keyword args. Type-hint everything.
#   2. Decorate it with @register_tool and supply a JSON Schema for the
#      arguments. The description text is shown to the LLM verbatim, so
#      write it for a model that has never seen ShintTools before.
#   3. Return ToolExecutionResult.ok(data) on success, .error(message)
#      on a clean failure. Unhandled exceptions are caught by
#      ToolDefinition.execute and converted to error results.
#
# IMPORTANT: importing this module is what populates
# `default_tool_registry`. Anywhere we want the agent's tools available,
# import this module (e.g. `from modules.agent import tool_implementations`)
# at startup. The orchestrator does this in Fase 3.

from __future__ import annotations

from typing import Any

from .tool_registry import ToolExecutionResult, register_tool

# ── Tool: analyze_cpp_source ───────────────────────────────────────────────


@register_tool(
    tool_name="analyze_cpp_source",
    tool_description=(
        "Run all UE5 C++ static-analysis rules against a single source "
        "file and return the issues found (rule_id, severity, line, "
        "message, fix suggestion). Use this whenever you need to know "
        "what is wrong with a file before deciding how to fix it. The "
        "issues returned by this tool are the only ones you should act "
        "on — do not invent new rule_ids."
    ),
    arguments_schema={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": (
                    "Path of the file being analysed. Used in the "
                    "returned issues' file_path field; not opened from "
                    "disk by this tool."
                ),
            },
            "file_content": {
                "type": "string",
                "description": "Full UTF-8 source text of the file.",
            },
        },
        "required": ["file_path", "file_content"],
        "additionalProperties": False,
    },
)
def analyze_cpp_source(
    *,
    file_path: str,
    file_content: str,
) -> ToolExecutionResult:
    # Imported lazily so the registry module can be loaded without
    # pulling in the full validator (helps keep the agent unit tests
    # focused and fast).
    from code_validator import analyse

    detected_issues = analyse(file_path, file_content)
    return ToolExecutionResult.ok(
        {
            "file_path": file_path,
            "issue_count": len(detected_issues),
            "issues": detected_issues,
        }
    )


# ── Tool: extract_source_excerpt ───────────────────────────────────────────


@register_tool(
    tool_name="extract_source_excerpt",
    tool_description=(
        "Return the lines [start_line, end_line] (1-indexed, inclusive) "
        "from a file's source. Use this to inspect the exact code "
        "surrounding an issue before proposing a fix, instead of asking "
        "the user for it. Lines past the end of the file are silently "
        "clamped — you will never get an out-of-range error from this."
    ),
    arguments_schema={
        "type": "object",
        "properties": {
            "file_content": {
                "type": "string",
                "description": "Full source text of the file.",
            },
            "start_line": {
                "type": "integer",
                "minimum": 1,
                "description": "First line to return (1-indexed).",
            },
            "end_line": {
                "type": "integer",
                "minimum": 1,
                "description": "Last line to return (1-indexed, inclusive).",
            },
        },
        "required": ["file_content", "start_line", "end_line"],
        "additionalProperties": False,
    },
)
def extract_source_excerpt(
    *,
    file_content: str,
    start_line: int,
    end_line: int,
) -> ToolExecutionResult:
    if start_line > end_line:
        return ToolExecutionResult.error(
            f"start_line ({start_line}) must be <= end_line ({end_line})."
        )

    source_lines = file_content.splitlines()
    total_line_count = len(source_lines)

    if start_line > total_line_count:
        return ToolExecutionResult.error(
            f"start_line ({start_line}) is past the end of the file "
            f"({total_line_count} lines)."
        )

    # Clamp the upper bound so a small over-read (LLM asks for line 200
    # in a 180-line file) returns whatever is available rather than
    # erroring out — the LLM almost always wants "show me around line N"
    # and can recover better from a short result than from a hard error.
    clamped_end_line = min(end_line, total_line_count)

    # 1-indexed inclusive -> 0-indexed half-open slice.
    start_line_zero_indexed = start_line - 1
    excerpt_lines = source_lines[start_line_zero_indexed:clamped_end_line]

    return ToolExecutionResult.ok(
        {
            "excerpt": "\n".join(excerpt_lines),
            "start_line": start_line,
            "end_line": clamped_end_line,
            "line_count": len(excerpt_lines),
        }
    )


# ── Tool: apply_auto_fix_for_issue ─────────────────────────────────────────


@register_tool(
    tool_name="apply_auto_fix_for_issue",
    tool_description=(
        "Attempt to apply ShintTools' built-in auto-fix for a single "
        "issue produced by analyze_cpp_source. Returns whether a fix is "
        "available for this rule_id. Today only a small subset of rules "
        "have auto-fixes implemented; for the rest, the issue must be "
        "fixed manually by the developer. Always inspect the issue with "
        "extract_source_excerpt before calling this."
    ),
    arguments_schema={
        "type": "object",
        "properties": {
            "issue": {
                "type": "object",
                "description": (
                    "An issue dictionary as returned by "
                    "analyze_cpp_source. Must contain at least 'rule_id'."
                ),
                "properties": {
                    "rule_id": {
                        "type": "string",
                        "description": ("The rule identifier (e.g. 'CS001', 'CB006')."),
                    },
                },
                "required": ["rule_id"],
            },
        },
        "required": ["issue"],
        "additionalProperties": False,
    },
)
def apply_auto_fix_for_issue(
    *,
    issue: dict[str, Any],
) -> ToolExecutionResult:
    if "rule_id" not in issue:
        return ToolExecutionResult.error(
            "issue is missing the required 'rule_id' field."
        )

    from code_validator import apply_fix

    fix_was_applied = apply_fix(issue)
    return ToolExecutionResult.ok(
        {
            "rule_id": issue["rule_id"],
            "fix_was_applied": fix_was_applied,
        }
    )
