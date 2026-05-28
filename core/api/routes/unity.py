# core/api/routes/unity.py
#
# Unity-specific endpoints.
#
# POST /validate/unity/scan
#   Full project scan with the JSON contract that the Unity plugin expects.
#   Returns contextBefore / contextAfter / fix inline — no separate fix call
#   needed. The previous /validate/fix returned empty content for C# files
#   because CppFixer only handles C++; this endpoint runs the C#-aware fixer
#   directly and embeds the result in the scan response.
#
# Custom rules (rules[].problem / rules[].solution) are accepted but
# processed by the LLM agent when available.  Built-in rules always run
# regardless.

import sys
import time
from pathlib import Path

from api.database import resolve_tier
from fastapi import APIRouter
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "modules"))

from code_validator.unity.csharp._csharp_helpers import (  # noqa: E402
    CSHARP_RULE_TO_PATTERN,
)
from code_validator.unity.csharp._csharp_helpers import (  # noqa: E402
    _fixer as _csharp_fixer,
)
from code_validator.unity.csharp.csharp_orchestrator import (  # noqa: E402
    run_all_csharp_rules,
)

router = APIRouter()

# ── Request models ─────────────────────────────────────────────────────────────


class CustomRule(BaseModel):
    """User-defined rule from the Unity plugin Settings panel."""

    problem: str = ""  # natural language: where/when to apply
    solution: str = ""  # natural language: how to fix


class UnityScanFile(BaseModel):
    """One C# script to analyse."""

    path: str = ""
    content: str = ""
    lines: int = 0


class UnityScanRequest(BaseModel):
    api_key: str = ""
    # User-defined rules (LLM-powered, processed when agent is available)
    rules: list[CustomRule] = Field(default_factory=list)
    files: list[UnityScanFile] = Field(default_factory=list)


# ── Helpers ────────────────────────────────────────────────────────────────────

_CS_EXTENSION = ".cs"


def _build_fix(rule_id: str, file_content: str, line: int) -> str:
    """Return the full corrected file content for a single fixable issue.

    Returns an empty string when no fix pattern exists for the rule or when
    the fixer produces no change — the plugin treats '' as 'no fix available'.
    """
    if _csharp_fixer is None or rule_id not in CSHARP_RULE_TO_PATTERN:
        return ""
    try:
        fixed, _, _ = _csharp_fixer.fix(rule_id, file_content, line)
        return fixed if fixed != file_content else ""
    except Exception:
        return ""


def _scan_file(
    file_path: str,
    file_content: str,
    allowed_rules: frozenset | None,
) -> list[dict]:
    """Run built-in C# rules on one file and return issues in Unity format."""
    if Path(file_path).suffix.lower() != _CS_EXTENSION:
        return []

    raw_issues = run_all_csharp_rules(file_content, file_path)

    # Apply tier filter
    if allowed_rules is not None:
        raw_issues = [i for i in raw_issues if i.get("rule_id", "") in allowed_rules]

    result: list[dict] = []
    for issue in raw_issues:
        rule_id: str = issue.get("rule_id", "")
        line: int = issue.get("line", 0)

        result.append(
            {
                # ── Spec-required fields ──────────────────────────────────
                "path": file_path,
                "genericRule": -1,
                "namingRule": -1,
                "line": line,
                "contextLine": issue.get("context_line_start", line),
                "contextBefore": issue.get("context_before", ""),
                "contextAfter": issue.get("context_after", ""),
                "fix": _build_fix(rule_id, file_content, line),
                # ── Extra fields for the UI (badge, message, rule name) ───
                "rule_id": rule_id,
                "severity": issue.get("severity", "warning"),
                "message": issue.get("message", ""),
                "rule_name": issue.get("rule_name", ""),
                "is_auto_fixable": issue.get("is_auto_fixable", False),
            }
        )

    return result


# ── Endpoint ───────────────────────────────────────────────────────────────────


@router.post("/validate/unity/scan")
async def unity_scan(payload: UnityScanRequest):
    """Scan Unity C# scripts and return findings in the Unity plugin format.

    Built-in rules always run.  Custom rules (payload.rules) are processed
    by the LLM agent when SHINTTOOLS_AGENT_ENABLED=1; otherwise they are
    acknowledged but skipped.

    Output per issue:
        path          — script path
        genericRule   — index in payload.rules (-1 = built-in or naming rule)
        namingRule    — always -1 for script scan (no naming rules here)
        line          — 1-based line number of the finding
        contextLine   — first line of the context window
        contextBefore — current code around the issue
        contextAfter  — code after applying the fix (empty if not auto-fixable)
        fix           — full corrected script content (empty if not auto-fixable)
        rule_id       — built-in rule ID for UI badge (e.g. "UN004")
        severity      — "warning" | "info" | "error"
        message       — human-readable description
        rule_name     — short rule title
        is_auto_fixable — whether a one-click fix is available
    """
    t0 = time.perf_counter()

    tier: str = await resolve_tier(payload.api_key)
    from code_validator.shared.tiers import get_tier_config  # noqa: E402

    allowed_rules: frozenset | None = get_tier_config(tier)["rules"]

    all_issues: list[dict] = []

    # ── Built-in rules ────────────────────────────────────────────────────────
    for file_entry in payload.files:
        file_issues = _scan_file(
            file_entry.path,
            file_entry.content,
            allowed_rules,
        )
        all_issues.extend(file_issues)

    # ── Custom rules (LLM agent, best-effort) ─────────────────────────────────
    custom_rules_note: str = ""
    if payload.rules:
        try:
            import os

            if os.getenv("SHINTTOOLS_AGENT_ENABLED") == "1":
                from modules.agent.custom_rule_checker import check_custom_rules

                custom_issues = check_custom_rules(
                    payload.rules,
                    payload.files,
                )
                all_issues.extend(custom_issues)
            else:
                custom_rules_note = (
                    f"{len(payload.rules)} custom rule(s) received but "
                    "LLM agent is disabled (SHINTTOOLS_AGENT_ENABLED!=1)."
                )
        except ImportError:
            custom_rules_note = (
                "Custom rules require the agent module " "(SHINTTOOLS_AGENT_ENABLED=1)."
            )

    return {
        "warning": custom_rules_note,
        "time": round(time.perf_counter() - t0, 4),
        "files": all_issues,
    }
