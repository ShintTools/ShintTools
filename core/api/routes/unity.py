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
import uuid
from datetime import datetime, timezone
from pathlib import Path

from api.database import analysis_results, resolve_tier
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
                "rule": -1,
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


async def _persist_unity_code_scan(issues: list[dict]) -> str:
    """Persist a Unity C# scan and return its analysis_id.

    Mirrors _persist_result in validate.py and _persist_unity_scan in
    assets.py — analysis_id doubles as the assistant's context_ref, so it
    is generated and returned even when the insert fails (then simply
    unresolvable, which the assistant reports honestly). Before this,
    /validate/unity/scan never persisted a result at all, so the Unity
    Code Validator's "Explain" action could never resolve a finding
    server-side — the client had nothing usable to hand back as
    context_ref, and Settings.ANALYSIS_ID stayed null forever.

    Issues here key the script path as "path" (this endpoint's own
    contract), but explain_finding's lookup reads "asset_path"/"file" —
    mirrored onto each entry so the same resolution logic works
    regardless of which engine produced the analysis.
    """
    analysis_id = f"an-{uuid.uuid4().hex[:12]}"
    try:
        doc = {
            "analysis_id": analysis_id,
            "report_type": "code_validator_unity",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "issues": [
                {**i, "asset_path": i.get("path", "")} for i in issues
            ],
        }
        await analysis_results.insert_one(doc)
    except Exception:
        pass
    return analysis_id


# ── Endpoint ───────────────────────────────────────────────────────────────────


@router.post("/validate/unity/scan")
async def unity_scan(payload: UnityScanRequest):
    """Scan Unity C# scripts and return findings in the Unity plugin format.

    Built-in rules always run.  Custom rules (payload.rules) are processed
    by the LLM agent when SHINTTOOLS_AGENT_ENABLED=1; otherwise they are
    acknowledged but skipped.

    Output per issue:
        path          — script path
        rule          — index in payload.rules (-1 = built-in)
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

    Also returns:
        analysis_id — persisted in analysis_results; the assistant's
                      "explain this finding" resolves against it via
                      context_ref (see _persist_unity_code_scan).
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
                pass  # LLM disabled — custom rules silently skipped
        except ImportError:
            pass

    analysis_id = await _persist_unity_code_scan(all_issues)

    return {
        "error": "",
        "time": round(time.perf_counter() - t0, 4),
        "files": all_issues,
        "analysis_id": analysis_id,
    }
