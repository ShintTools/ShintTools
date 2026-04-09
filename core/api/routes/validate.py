# core/api/routes/validate.py
#
# Endpoints:
#   POST /validate/assets      — validate asset naming (mock, Sprint 4 pending)
#   POST /validate/code        — single file analysis
#   POST /validate/project     — batch of source files (full project scan)
#   POST /validate/blueprints  — full Blueprint export from UE5 plugin
#   POST /validate/fix         — apply auto-fixes with Tree-sitter

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from api.database import analysis_results
from fastapi import APIRouter
from pydantic import BaseModel, Field

# Add modules path to import code_validator rules
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "modules"))

from code_validator.parsers.cpp_fixer import CppFixer  # noqa: E402
from code_validator.parsers.fix_patterns import RULE_TO_PATTERN  # noqa: E402
from code_validator.rules.blueprint_rules import (  # noqa: E402
    run_all_blueprint_rules_from_export,
)
from code_validator.rules.ue5_cpp_rules import run_all_cpp_rules  # noqa: E402

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
        default="unreal", description="Target engine: 'unreal' | 'unity'"
    )


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


class ValidateBlueprintsRequest(BaseModel):
    """Request for Blueprint validation from UE5 plugin export."""

    project_id: str = Field(
        default="", description="Project identifier from the plugin"
    )
    api_key: str = Field(default="", description="API key from the plugin")
    project_name: str = Field(default="", description="Project name")
    files: list[dict] = Field(
        default_factory=list,
        description="Blueprint file dicts exported by the plugin",
    )
    engine: str = Field(
        default="unreal", description="Target engine: 'unreal' | 'unity'"
    )


class FixIssueEntry(BaseModel):
    """Single issue to fix - must include content for Tree-sitter."""

    rule_id: str = Field(..., description="Rule ID (e.g., CP001)")
    file_path: str = Field(..., description="Path to the source file")
    line: Optional[int] = Field(default=None, description="Line number of the issue")
    content: str = Field(..., description="Full content of the source file")


class ApplyFixesRequest(BaseModel):
    """Request to apply auto-fixes using Tree-sitter."""

    issues: list[FixIssueEntry] = Field(default_factory=list)


# ── Shared helpers ────────────────────────────────────

_CPP_EXTENSIONS = {".cpp", ".h", ".hpp", ".cc"}


def _build_summary(
    issues: list[dict],
    files_scanned: int = 1,
) -> dict:
    """Build a standard summary dict from a list of issues."""
    errors = sum(1 for i in issues if i.get("severity") == "error")
    warnings = sum(1 for i in issues if i.get("severity") == "warning")
    return {
        "total": len(issues),
        "issues": len(issues),
        "errors": errors,
        "warnings": warnings,
        "files_scanned": files_scanned,
    }


def _analyse_file(
    file_path: str,
    content: str,
    engine: str = "unreal",
) -> list[dict]:
    """
    Run rules against a single source file.
    Currently supports C++ files for Unreal Engine.
    """
    file_ext = Path(file_path).suffix.lower()

    if engine == "unreal" and file_ext in _CPP_EXTENSIONS:
        issues = run_all_cpp_rules(content, file_path)
        # Add is_auto_fixable based on fix_patterns
        for issue in issues:
            rule_id = issue.get("rule_id", "")
            issue["is_auto_fixable"] = rule_id in RULE_TO_PATTERN
        return issues

    return []


def _is_auto_fixable(rule_id: str) -> bool:
    """Check if a rule has a Tree-sitter fix pattern."""
    return rule_id in RULE_TO_PATTERN


async def _persist_result(
    report_type: str,
    summary: dict,
    issues: list[dict],
) -> None:
    """
    Save result to MongoDB for the dashboard.
    Best-effort — never blocks the response if MongoDB is unavailable.
    """
    try:
        doc = {
            "report_type": report_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
            "issues": issues,
        }
        await analysis_results.insert_one(doc)
    except Exception:
        pass


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
        "message": "Mock response — use /assets/scan for real analysis",
    }


@router.post("/validate/code")
async def validate_code(payload: ValidateCodeRequest):
    """
    Analyses a single source file for code smells.
    Runs deterministic C++ rules for .cpp and .h files.
    Each issue includes is_auto_fixable based on Tree-sitter patterns.
    """
    issues = _analyse_file(
        payload.file_path,
        payload.content,
        payload.engine,
    )
    summary = _build_summary(issues, files_scanned=1)
    await _persist_result("code_validator", summary, issues)

    return {"summary": summary, "issues": issues}


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

    summary = _build_summary(
        all_issues,
        files_scanned=len(payload.files),
    )
    await _persist_result("code_validator_project", summary, all_issues)

    return {"summary": summary, "issues": all_issues}


@router.post("/validate/blueprints")
async def validate_blueprints(payload: ValidateBlueprintsRequest):
    """
    Validate Blueprint assets from the full UE5 plugin export.
    Receives the complete JSON exported by the plugin
    (graphs, variables, functions, stats per Blueprint)
    and runs all deterministic Blueprint rules.
    """
    plugin_export = {"files": payload.files}
    all_issues = run_all_blueprint_rules_from_export(plugin_export)

    # Add is_auto_fixable for Blueprint rules
    for issue in all_issues:
        rule_id = issue.get("rule_id", "")
        issue["is_auto_fixable"] = rule_id in RULE_TO_PATTERN

    blueprints_scanned = sum(1 for f in payload.files if f.get("type") == "blueprint")

    summary = _build_summary(
        all_issues,
        files_scanned=blueprints_scanned,
    )
    await _persist_result("code_validator_blueprints", summary, all_issues)

    return {"summary": summary, "issues": all_issues}


@router.post("/validate/fix")
async def apply_fixes(payload: ApplyFixesRequest):
    """
    Apply auto-fixes using Tree-sitter AST analysis.

    The plugin must send the full file content for each issue.
    Tree-sitter parses the code, understands its structure,
    and generates safe fixes.

    Returns:
        - fixes: List of fix results with original and fixed code
        - summary: Count of successful and failed fixes

    Example request:
    {
        "issues": [
            {
                "rule_id": "CP001",
                "file_path": "Source/MyGame/MyActor.cpp",
                "line": 45,
                "content": "void AMyActor::Tick(...) { ... full file content ... }"
            }
        ]
    }

    Example response:
    {
        "fixes": [
            {
                "rule_id": "CP001",
                "file_path": "Source/MyGame/MyActor.cpp",
                "success": true,
                "original_code": "AActor* Target = FindObjectOfType<AActor>();",
                "fixed_code": "// [SHINTTOOLS] Moved to BeginPlay...",
                "additions": "// Add to .h: UPROPERTY() AActor* CachedTarget;",
                "changes": ["Line 46: Target -> CachedTarget"]
            }
        ],
        "summary": {
            "total": 1,
            "successful": 1,
            "failed": 0
        }
    }
    """
    fixes: list[dict] = []
    successful = 0
    failed = 0

    for issue in payload.issues:
        rule_id = issue.rule_id
        file_path = issue.file_path
        content = issue.content
        line_number = issue.line

        # Check if rule has a Tree-sitter pattern
        if not _is_auto_fixable(rule_id):
            fixes.append(
                {
                    "rule_id": rule_id,
                    "file_path": file_path,
                    "success": False,
                    "error": f"No Tree-sitter pattern for rule {rule_id}",
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
                        "error": "No changes made - pattern not found in code",
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

    return {
        "fixes": fixes,
        "summary": {
            "total": len(payload.issues),
            "successful": successful,
            "failed": failed,
        },
    }
