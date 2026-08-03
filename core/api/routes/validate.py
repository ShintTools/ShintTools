# core/api/routes/validate.py
#
# Endpoints:
#   POST /validate/assets      — validate asset naming (mock, Sprint 4 pending)
#   POST /validate/code        — single file analysis
#   POST /validate/project     — batch of source files (full project scan)
#   POST /validate/blueprints  — full Blueprint export from UE5 plugin
#   POST /validate/fix         — apply auto-fixes with Tree-sitter

import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from api.database import analysis_results, get_latest_score, persist_score, resolve_tier
from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Add modules path to import code_validator rules
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "modules"))

from code_validator.shared._rule_metadata import RULE_NAMES  # noqa: E402
from code_validator.shared.tiers import FREE_RULES, filter_issues_by_tier  # noqa: E402
from code_validator.unity.csharp.csharp_orchestrator import (  # noqa: E402
    run_all_csharp_rules,
)
from code_validator.unity.parsers.unity_vs_parser import parse_unity_graph  # noqa: E402
from code_validator.unity.visual_scripting.unity_graph_orchestrator import (  # noqa: E402,E501
    run_all_unity_graph_rules,
)
from code_validator.unreal.blueprint.blueprint_orchestrator import (  # noqa: E402
    run_all_blueprint_rules_from_export,
)
from code_validator.unreal.cpp.cpp_orchestrator import run_all_cpp_rules  # noqa: E402
from code_validator.unreal.parsers.fixers.cpp_fixer import CppFixer  # noqa: E402
from code_validator.unreal.parsers.fixers.fix_patterns import (  # noqa: E402
    RULE_TO_PATTERN,
)

# Total code-validator rules available (C++ + Blueprint), excluding
# asset-naming (NM*) which lives in /assets/scan. Computed once at
# import so the summary can advertise "X of Y rules" without a per-
# request recount.
_TOTAL_CODE_RULES: int = sum(1 for rid in RULE_NAMES if not rid.startswith("NM"))
from metrics.score_calculator import (  # noqa: E402
    compute_score,
    recalculate_after_fixes,
)

router = APIRouter()

# Initialize Tree-sitter fixer
_fixer = CppFixer()


# ── Request models ────────────────────────────────────


class ValidateAssetsRequest(BaseModel):
    """Request for asset naming validation."""

    paths: list[str] = Field(
        default_factory=list, description="Asset paths to validate"
    )


class ValidateCodeRequest(BaseModel):
    """Request for single file code analysis."""

    file_path: str = Field(..., description="Relative path of the source file")
    content: str = Field(default="", description="Full text content of the source file")
    engine: str = Field(
        default="unreal",
        description="Target engine: 'unreal' | 'unity'",
    )
    api_key: str = Field(default="", description="License API key")


class FileEntry(BaseModel):
    """Single file entry matching the UE5 plugin JSON structure."""

    name: str = ""
    path: str = ""
    type: str = ""
    content: str = ""
    lines_count: int = 0


class ValidateProjectRequest(BaseModel):
    """Request for batch project validation."""

    project_id: str = ""
    api_key: str = ""
    project_name: str = ""
    files: list[FileEntry] = Field(default_factory=list)
    engine: str = "unreal"
    # Scopes which persistent studio rules apply (assistant M3). Optional
    # and additive — clients that don't send it simply run built-ins only.
    studio_id: str = ""


class ValidateBlueprintsRequest(BaseModel):
    """Request for Blueprint validation from UE5 plugin export."""

    project_id: str = Field(
        default="",
        description="Project identifier from the plugin",
    )
    api_key: str = Field(default="", description="API key from the plugin")
    project_name: str = Field(default="", description="Project name")
    files: list[dict] = Field(
        default_factory=list,
        description="Blueprint file dicts exported by the plugin",
    )
    engine: str = Field(
        default="unreal",
        description="Target engine: 'unreal' | 'unity'",
    )


class FixIssueEntry(BaseModel):
    """Single issue to fix - must include content for Tree-sitter."""

    rule_id: str = Field(..., description="Rule ID (e.g., CP001)")
    file_path: str = Field(..., description="Path to the source file")
    line: Optional[int] = Field(default=None, description="Line number of the issue")
    content: str = Field(..., description="Full content of the source file")


class ApplyFixesRequest(BaseModel):
    """Request to apply auto-fixes using Tree-sitter."""

    project_id: str = Field(
        default="",
        description="Project identifier for score update",
    )
    api_key: str = Field(default="", description="License API key")
    issues: list[FixIssueEntry] = Field(default_factory=list)


# ── Shared helpers ────────────────────────────────────

_CPP_EXTENSIONS = {".cpp", ".h", ".hpp", ".cc"}

# Default severity per rule prefix — used when the fix endpoint
# needs to know the severity but only has the rule_id.
_RULE_PREFIX_SEVERITY: dict[str, str] = {
    "CP": "warning",
    "CB": "warning",
    "CS": "warning",
    "CM": "warning",
    "BPB": "warning",
    "BPP": "warning",
    "BPM": "info",
    "BPS": "error",
    "NM": "warning",
}

# Override for specific rules that have a different severity
_RULE_SEVERITY_OVERRIDES: dict[str, str] = {
    "CP001": "error",
    "CP005": "error",
    "CP006": "error",
    "CP012": "error",
    "CP016": "error",
    "CP018": "error",
    "CS008": "error",
    "CS012": "error",
    "CS013": "error",
    "CS015": "error",
    "CS016": "error",
    "CS017": "error",
    "CM001": "error",
    "CM003": "info",
    "CM007": "info",
    "CM008": "info",
    "CM009": "info",
}


def _get_severity_for_rule(rule_id: str) -> str:
    """Best-effort severity lookup from a rule_id."""
    if rule_id in _RULE_SEVERITY_OVERRIDES:
        return _RULE_SEVERITY_OVERRIDES[rule_id]
    for prefix, severity in _RULE_PREFIX_SEVERITY.items():
        if rule_id.startswith(prefix):
            return severity
    return "warning"


def _build_summary(
    issues: list[dict],
    files_scanned: int = 1,
    tier: str = "free",
) -> dict:
    """Build a standard summary dict from a list of issues.

    Includes cap-metadata fields so the plugin can render an
    "X of Y rules — upgrade for full coverage" banner without
    trusting any client-side heuristic. `limit_applied` is part
    of the signed payload (Phase A), so the plugin cannot lie
    about whether the cap was applied.
    """
    errors = sum(1 for i in issues if i.get("severity") == "error")
    warnings = sum(1 for i in issues if i.get("severity") == "warning")
    is_free = tier == "free"
    return {
        "total": len(issues),
        "issues": len(issues),
        "errors": errors,
        "warnings": warnings,
        "files_scanned": files_scanned,
        "tier": tier,
        # ── Free-tier cap metadata (consumed by UE5 + Unity plugins)
        "limit_applied": is_free,
        "limit_kind": "rules",
        "limit_value": len(FREE_RULES) if is_free else _TOTAL_CODE_RULES,
        "total_available": _TOTAL_CODE_RULES,
    }


def _analyse_file(
    file_path: str,
    content: str,
    engine: str = "unreal",
) -> list[dict]:
    """
    Run rules against a single source file.

    Engine routing:
      - `engine="unreal"` + .cpp/.h   → run_all_cpp_rules    (full taxonomy)
      - `engine="unity"`  + .cs       → run_all_csharp_rules (partial — see
                                        rules/csharp/ for implemented set)
      - anything else                  → no detectors, empty list
    """
    file_ext = Path(file_path).suffix.lower()
    issues: list[dict] = []

    if engine == "unreal" and file_ext in _CPP_EXTENSIONS:
        issues = run_all_cpp_rules(content, file_path)
    elif engine == "unity" and file_ext == ".cs":
        issues = run_all_csharp_rules(content, file_path)

    for issue in issues:
        rule_id = issue.get("rule_id", "")
        issue["is_auto_fixable"] = rule_id in RULE_TO_PATTERN
        issue["file_path"] = file_path
    return issues


def _is_auto_fixable(rule_id: str) -> bool:
    """Check if a rule has a Tree-sitter fix pattern."""
    return rule_id in RULE_TO_PATTERN


async def _persist_result(
    report_type: str,
    summary: dict,
    issues: list[dict],
) -> str:
    """
    Save result to MongoDB for the dashboard.
    Best-effort — never blocks the response if MongoDB is
    unavailable.

    Returns the analysis_id stamped on the stored document. Clients hand
    it back as the assistant's `context_ref` ("explain this finding"), so
    it is generated and returned even when the insert fails — the id is
    then simply unresolvable, which the assistant reports honestly.
    """
    analysis_id = f"an-{uuid.uuid4().hex[:12]}"
    try:
        doc = {
            "analysis_id": analysis_id,
            "report_type": report_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
            "issues": issues,
        }
        await analysis_results.insert_one(doc)
    except Exception:
        pass
    return analysis_id


# ── Endpoints ─────────────────────────────────────────


@router.post("/validate/assets")
async def validate_assets(payload: ValidateAssetsRequest):
    """
    Validates asset naming conventions.
    Kept for backward compatibility with existing plugin versions.
    Real analysis lives in POST /assets/scan.
    """
    return {
        "summary": {
            "total": 0,
            "issues": 0,
            "errors": 0,
            "warnings": 0,
        },
        "issues": [],
        "message": ("Mock response — use /assets/scan for real analysis"),
    }


@router.post("/validate/code")
async def validate_code(payload: ValidateCodeRequest):
    """
    Analyses a single source file for code smells.
    Runs deterministic C++ rules for .cpp and .h files.
    Each issue includes is_auto_fixable based on Tree-sitter
    patterns.
    """
    issues = _analyse_file(
        payload.file_path,
        payload.content,
        payload.engine,
    )

    # Filter by subscription tier
    tier = await resolve_tier(payload.api_key)
    issues = filter_issues_by_tier(issues, tier)

    summary = _build_summary(issues, files_scanned=1, tier=tier)
    analysis_id = await _persist_result("code_validator", summary, issues)

    return {
        "summary": summary,
        "issues": issues,
        "tier": tier,
        "analysis_id": analysis_id,
    }


@router.post("/validate/project")
async def validate_project(payload: ValidateProjectRequest):
    """
    Validate all source files in the project (batch).
    The plugin collects every .cpp / .h, reads them,
    and sends them all here in a single request.
    """
    all_issues: list[dict] = []

    for file_entry in payload.files:
        file_issues = _analyse_file(
            file_entry.path,
            file_entry.content,
            payload.engine,
        )
        all_issues.extend(file_issues)

    # Filter by subscription tier
    tier = await resolve_tier(payload.api_key)
    all_issues = filter_issues_by_tier(all_issues, tier)

    # Persistent studio rules (assistant M3) — best-effort add-on; a
    # failing studio rule never breaks the built-in scan. Only rules the
    # user explicitly activated run here, and their findings carry
    # source="studio_rule" so the panel can badge them.
    if payload.studio_id:
        try:
            from modules.assistant.rule_runner import evaluate_studio_rules

            all_issues.extend(
                await evaluate_studio_rules(
                    payload.studio_id,
                    payload.project_id,
                    payload.engine,
                    [(f.path, f.content) for f in payload.files],
                )
            )
        except Exception:
            logger.exception("studio rules evaluation failed")

    files_scanned = len(payload.files)

    summary = _build_summary(
        all_issues,
        files_scanned=files_scanned,
        tier=tier,
    )
    analysis_id = await _persist_result(
        "code_validator_project", summary, all_issues
    )

    # Compute and persist Quality Score automatically
    score_doc = compute_score(
        issues=all_issues,
        files_scanned=files_scanned,
        project_id=payload.project_id,
        scan_type="full",
        tier=tier,
    )
    await persist_score(score_doc)

    return {
        "summary": summary,
        "issues": all_issues,
        "tier": tier,
        "quality_score": score_doc["overall_score"],
        "analysis_id": analysis_id,
    }


@router.post("/validate/blueprints")
async def validate_blueprints(
    payload: ValidateBlueprintsRequest,
):
    """
    Validate Blueprint assets from the full UE5 plugin export.
    Receives the complete JSON exported by the plugin
    (graphs, variables, functions, stats per Blueprint)
    and runs all deterministic Blueprint rules.
    """
    plugin_export = {"files": payload.files}
    all_issues = run_all_blueprint_rules_from_export(plugin_export)

    # Add is_auto_fixable and normalize file_path
    for issue in all_issues:
        rule_id = issue.get("rule_id", "")
        issue["is_auto_fixable"] = rule_id in RULE_TO_PATTERN
        issue["file_path"] = issue.get("asset_path", "")

    # Filter by subscription tier
    tier = await resolve_tier(payload.api_key)
    all_issues = filter_issues_by_tier(all_issues, tier)

    blueprints_scanned = sum(1 for f in payload.files if f.get("type") == "blueprint")

    summary = _build_summary(
        all_issues,
        files_scanned=blueprints_scanned,
        tier=tier,
    )
    analysis_id = await _persist_result(
        "code_validator_blueprints", summary, all_issues
    )

    # Compute and persist Quality Score automatically
    score_doc = compute_score(
        issues=all_issues,
        files_scanned=blueprints_scanned,
        project_id=payload.project_id,
        scan_type="full",
        tier=tier,
    )
    await persist_score(score_doc)

    return {
        "summary": summary,
        "issues": all_issues,
        "tier": tier,
        "quality_score": score_doc["overall_score"],
        "analysis_id": analysis_id,
    }


class UnityGraphFile(BaseModel):
    """One Visual Scripting `.asset` file shipped by the Unity plugin."""

    path: str = ""
    content: str = ""


class ValidateUnityGraphsRequest(BaseModel):
    """Request for Visual Scripting graph validation.

    Accepts `files` (unified Unity plugin contract) or `graphs` (legacy alias).
    The Unity plugin should always send `files` — the `graphs` field is kept
    for backward compatibility only.
    """

    project_id: str = ""
    api_key: str = ""
    project_name: str = ""
    # Unified contract — same field name as Code Tool and Asset Tool
    files: list[UnityGraphFile] = Field(default_factory=list)
    # Legacy alias — kept so any older plugin build doesn't break
    graphs: list[UnityGraphFile] = Field(default_factory=list)


def _graph_parse_failure_reason(content: str, path: str) -> str:
    """Return a short reason string explaining why parse_unity_graph returned None."""
    if not content or not content.strip():
        return "content is empty — the plugin sent an empty string for this file"
    from code_validator.unity.parsers.unity_vs_parser import (
        _VS_EMBEDDED_JSON_HINT,
        _VS_HEAD_SCAN_BYTES,
        _VS_MARKERS,
        _VS_TYPE_PREFIX,
        _extract_json_string,
    )

    head = content[:_VS_HEAD_SCAN_BYTES]
    has_class_marker = any(m in head for m in _VS_MARKERS)
    has_json_field = _VS_EMBEDDED_JSON_HINT in head
    has_type_prefix = _VS_TYPE_PREFIX in head
    if not has_class_marker and not has_json_field:
        return (
            "not recognised as a Visual Scripting asset — "
            "missing '_json:' field and Unity.VisualScripting.* class markers. "
            "Make sure Asset Serialization Mode is set to ForceText in Unity."
        )
    if has_json_field and not has_type_prefix:
        return (
            "_json: field found but no Unity.VisualScripting.* type names inside — "
            "the embedded JSON may be from a different asset type."
        )
    if _extract_json_string(content) is None:
        return (
            "VS asset detected but could not extract the embedded JSON blob — "
            "the _json: field may be malformed or exceed the 16 KB scan window."
        )
    return "JSON extracted but failed to parse — the embedded JSON may be malformed."


@router.post("/validate/unity-graphs")
async def validate_unity_graphs(payload: ValidateUnityGraphsRequest):
    """Validate Unity Visual Scripting (com.unity.visualscripting) graph assets.

    Accepts the YAML content of one or more `.asset` files and runs the built-in
    Visual Scripting rules. Returns findings in the same unified format used by
    /validate/unity/scan and /assets/unity/scan so the Unity plugin can reuse
    its generic result handler for the Graph Tool.

    Input: `files` list (unified contract). Falls back to `graphs` if `files`
    is empty (backward compat with older builds).

    Output per finding:
        path          — graph asset path
        rule          — index in user rules[] (-1 = built-in)
        line          — 0 (graphs have no line numbers)
        contextLine   — 0
        contextBefore — relevant graph context or empty string
        contextAfter  — empty (graph auto-fix not yet available)
        fix           — empty (graph auto-fix not yet available)
        rule_id       — built-in rule ID (e.g. "VSG001")
        severity      — "warning" | "info" | "error"
        message       — human-readable description
        rule_name     — short rule title
        is_auto_fixable — always false (graph YAML editing not yet wired)
    """
    import time

    t0 = time.perf_counter()

    # Unified contract: prefer `files`, fall back to legacy `graphs`
    entries = payload.files if payload.files else payload.graphs

    graphs_received = len(entries)
    parse_failures: list[str] = []
    parsed_graphs: list[dict] = []
    for entry in entries:
        g = parse_unity_graph(entry.content, entry.path)
        if g is not None:
            parsed_graphs.append(g)
        else:
            reason = _graph_parse_failure_reason(entry.content, entry.path)
            parse_failures.append(f"{entry.path}: {reason}")
            logger.warning(
                "validate_unity_graphs: skipped '%s' — %s", entry.path, reason
            )

    if graphs_received == 0:
        logger.warning(
            "validate_unity_graphs: received 0 files — "
            "check that the plugin is sending 'files' (not 'graphs') in the payload."
        )

    # Run built-in Visual Scripting rules
    all_issues = run_all_unity_graph_rules(parsed_graphs)

    # Normalize to unified output shape (same as /validate/unity/scan)
    normalized: list[dict] = []
    for issue in all_issues:
        normalized.append(
            {
                "path": issue.get("asset_path", issue.get("file_path", "")),
                "rule": -1,  # built-in rule
                "line": 0,  # graphs have no line numbers
                "contextLine": 0,
                "contextBefore": issue.get("context", ""),
                "contextAfter": "",
                "fix": "",
                "rule_id": issue.get("rule_id", ""),
                "severity": issue.get("severity", "warning"),
                "message": issue.get("message", ""),
                "rule_name": issue.get("rule_name", ""),
                "is_auto_fixable": False,
            }
        )

    tier = await resolve_tier(payload.api_key)
    normalized = filter_issues_by_tier(normalized, tier)

    analysis_id = await _persist_result(
        "code_validator_unity_graphs",
        _build_summary(normalized, files_scanned=len(parsed_graphs), tier=tier),
        normalized,
    )

    return {
        "error": "",
        "time": round(time.perf_counter() - t0, 4),
        "analysis_id": analysis_id,
        "files": normalized,
        "graphs_received": graphs_received,
        "graphs_parsed": len(parsed_graphs),
        "parse_failures": parse_failures,
    }


@router.post("/validate/unity-graphs/debug")
async def validate_unity_graphs_debug(payload: ValidateUnityGraphsRequest):
    """Diagnostic endpoint — echoes back what the plugin sent without parsing.

    Daniel can call this instead of /validate/unity-graphs to verify that
    the payload is arriving correctly before debugging the parser.
    """
    entries = payload.files if payload.files else payload.graphs
    return {
        "graphs_received": len(entries),
        "using_field": (
            "files" if payload.files else ("graphs" if payload.graphs else "none")
        ),
        "entries": [
            {
                "path": e.path,
                "content_length": len(e.content),
                "content_preview": e.content[:200] if e.content else "",
                "content_empty": not bool(e.content and e.content.strip()),
            }
            for e in entries
        ],
    }


@router.post("/validate/fix")
async def apply_fixes(payload: ApplyFixesRequest):
    """
    Apply auto-fixes using Tree-sitter AST analysis.

    The plugin must send the full file content for each issue.
    Tree-sitter parses the code, understands its structure,
    and generates safe fixes.

    Returns:
        - fixes: List of fix results with original and fixed
          code
        - summary: Count of successful and failed fixes
    """
    fixes: list[dict] = []
    successful = 0
    failed = 0

    # Resolve tier to block fixes on rules outside the plan
    tier = await resolve_tier(payload.api_key)
    from code_validator.shared.tiers import get_tier_config  # noqa: E402

    tier_cfg = get_tier_config(tier)
    allowed_rules = tier_cfg["rules"]  # None = all allowed

    for issue in payload.issues:
        rule_id = issue.rule_id
        file_path = issue.file_path
        content = issue.content
        line_number = issue.line

        # Block fixes for rules outside the client's tier
        if allowed_rules is not None and rule_id not in allowed_rules:
            fixes.append(
                {
                    "rule_id": rule_id,
                    "file_path": file_path,
                    "success": False,
                    "error": (f"Rule {rule_id} requires Indie plan"),
                }
            )
            failed += 1
            continue

        # Check if rule has a Tree-sitter pattern
        if not _is_auto_fixable(rule_id):
            fixes.append(
                {
                    "rule_id": rule_id,
                    "file_path": file_path,
                    "success": False,
                    "error": (f"No Tree-sitter pattern for " f"rule {rule_id}"),
                }
            )
            failed += 1
            continue

        # Apply the fix using Tree-sitter
        try:
            fixed_code, additions, changes = _fixer.fix(
                rule_id,
                content,
                line_number,
            )

            # Check if fix was actually applied
            if fixed_code == content:
                fixes.append(
                    {
                        "rule_id": rule_id,
                        "file_path": file_path,
                        "success": False,
                        "error": ("No changes made - pattern " "not found in code"),
                    }
                )
                failed += 1
            else:
                fixes.append(
                    {
                        "rule_id": rule_id,
                        "file_path": file_path,
                        "success": True,
                        "original_code": content,
                        "fixed_code": fixed_code,
                        "additions": additions,
                        "changes": changes,
                    }
                )
                successful += 1

        except Exception as e:
            fixes.append(
                {
                    "rule_id": rule_id,
                    "file_path": file_path,
                    "success": False,
                    "error": str(e),
                }
            )
            failed += 1

    # Persist fix results
    await _persist_result(
        "code_validator_fixes",
        {"successful": successful, "failed": failed},
        fixes,
    )

    # Recalculate Quality Score after successful fixes
    if successful > 0 and payload.project_id:
        prev_score = await get_latest_score(payload.project_id)
        if prev_score:
            fixed_issues = [
                {
                    "rule_id": f["rule_id"],
                    "severity": _get_severity_for_rule(f["rule_id"]),
                }
                for f in fixes
                if f.get("success")
            ]
            new_score = recalculate_after_fixes(prev_score, fixed_issues)
            await persist_score(new_score)

            return {
                "fixes": fixes,
                "summary": {
                    "total": len(payload.issues),
                    "successful": successful,
                    "failed": failed,
                },
                "quality_score": new_score["overall_score"],
            }

    return {
        "fixes": fixes,
        "summary": {
            "total": len(payload.issues),
            "successful": successful,
            "failed": failed,
        },
    }
