# core/api/routes/validate.py
#
# Endpoints:
#   POST /validate/assets      — validate asset naming (mock, Sprint 4 pending)
#   POST /validate/code        — single file analysis
#   POST /validate/project     — batch of source files (full project scan)
#   POST /validate/blueprints  — full Blueprint export from UE5 plugin
#   POST /validate/fix         — apply auto-fixes (stub, Sprint 5 pending)

import sys
from datetime import datetime, timezone
from pathlib import Path

from api.database import analysis_results
from fastapi import APIRouter
from pydantic import BaseModel, Field

# Add modules path to import code_validator rules
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "modules"))

from code_validator.rules.blueprint_rules import (  # noqa: E402
    run_all_blueprint_rules_from_export,
)
from code_validator.rules.ue5_cpp_rules import run_all_cpp_rules  # noqa: E402

router = APIRouter()


# ── Request models ────────────────────────────────────


class ValidateAssetsRequest(BaseModel):
    # List of asset paths to validate
    paths: list[str] = Field(
        default_factory=list, description="Asset paths to validate"
    )


class ValidateCodeRequest(BaseModel):
    # Relative path of the source file
    file_path: str = Field(..., description="Relative path of the source file")
    # Full text content of the source file
    content: str = Field(default="", description="Full text content of the source file")
    # Target engine: unreal or unity
    engine: str = Field(
        default="unreal", description="Target engine: 'unreal' | 'unity'"
    )


class FileEntry(BaseModel):
    # Fields matching the UE5 plugin JSON structure
    name: str = ""
    path: str = ""
    type: str = ""
    content: str = ""
    lines_count: int = 0


class ValidateProjectRequest(BaseModel):
    project_id: str = ""
    api_key: str = ""
    project_name: str = ""
    files: list[FileEntry] = Field(default_factory=list)
    engine: str = "unreal"


class ValidateBlueprintsRequest(BaseModel):
    # Full Blueprint export JSON from the UE5 plugin.
    # Expected structure:
    # {
    #   "project_id": "...",
    #   "files": [
    #     {
    #       "name": "BP_PlayerCharacter",
    #       "path": "/Game/Blueprints/...",
    #       "type": "blueprint",
    #       "graphs": [...],
    #       "variables": [...],
    #       "functions": [...],
    #       "stats": {...}
    #     }
    #   ]
    # }
    project_id: str = Field(
        default="", description="Project identifier from the plugin"
    )
    api_key: str = Field(default="", description="API key from the plugin")
    project_name: str = Field(default="", description="Project name")
    files: list[dict] = Field(
        default_factory=list, description="Blueprint file dicts exported by the plugin"
    )
    engine: str = Field(
        default="unreal", description="Target engine: 'unreal' | 'unity'"
    )


class IssueEntry(BaseModel):
    rule_id: str = ""
    severity: str = "warning"
    message: str = ""
    file_path: str = ""
    line: int = 0


class ApplyFixesRequest(BaseModel):
    issues: list[IssueEntry] = Field(default_factory=list)


# ── Shared helpers ────────────────────────────────────

# Extensions we support for C++ analysis
_CPP_EXTENSIONS = {".cpp", ".h", ".hpp", ".cc"}

# All rules now support auto-fix (all have snippet + fix_suggestion)
_FIXABLE_RULES = {
    # Performance
    "CP001",
    "CP002",
    "CP003",
    "CP004",
    "CP005",
    "CP006",
    "CP007",
    "CP008",
    "CP009",
    "CP010",
    "CP011",
    "CP012",
    "CP013",
    "CP016",
    # Best Practices
    "CB001",
    "CB002",
    "CB004",
    "CB005",
    "CB007",
    "CB008",
    "CB009",
    "CB010",
    "CB011",
    "CB012",
    "CB013",
    "CB014",
    "CB015",
    "CB016",
    "CB018",
    "CB019",
    "CB020",
    "CB021",
    "CB023",
    "CB025",
    "CB030",
    "CB031",
    "CB032",
    # Security
    "CS002",
    "CS003",
    "CS004",
    "CS005",
    "CS007",
    "CS008",
    "CS011",
    "CS012",
    # Maintainability
    "CM001",
    "CM002",
    "CM003",
    "CM005",
    "CM006",
    "CM007",
    "CM008",
    "CM009",
    # Blueprint rules
    "BPB001",
    "BPB003",
    "BPB007",
    "BPP001",
    "BPM001",
    "BPM002",
}


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
    Unity and other engines pending Phase 2.
    """
    file_ext = Path(file_path).suffix.lower()

    if engine == "unreal" and file_ext in _CPP_EXTENSIONS:
        return run_all_cpp_rules(content, file_path)

    return []


async def _persist_result(
    report_type: str,
    summary: dict,
    issues: list[dict],
) -> None:
    """
    Save result to MongoDB for the dashboard.
    Best-effort — never blocks the response if MongoDB
    is unavailable.
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
    Kept for backward compatibility with existing plugin
    versions. Real analysis lives in POST /assets/scan.
    """
    # TODO Sprint 4: Remove once all plugins use /assets/scan
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
    Saves results to MongoDB after analysis.
    The response structure must not change — the plugin
    depends on this exact format.
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
async def validate_blueprints(
    payload: ValidateBlueprintsRequest,
):
    """
    Validate Blueprint assets from the full UE5 plugin export.
    Receives the complete JSON exported by the plugin
    (graphs, variables, functions, stats per Blueprint)
    and runs all deterministic Blueprint rules.
    Saves results to MongoDB after analysis.
    """
    # Build the export dict that the runner expects
    plugin_export = {"files": payload.files}

    all_issues = run_all_blueprint_rules_from_export(plugin_export)

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
    Apply auto-fixes server-side.
    Sprint 5: wire to real AST-based fixer.
    Currently only CB006 (printf) and MT001 (GEngine debug
    message) are marked as fixable.
    All fixes are opt-in — the developer approves each one
    in the plugin panel before the fix is applied.
    """
    files_fixed: set[str] = set()
    issues_fixed: int = 0

    for issue in payload.issues:
        if issue.rule_id in _FIXABLE_RULES:
            files_fixed.add(issue.file_path)
            issues_fixed += 1

    return {
        "files_fixed": len(files_fixed),
        "issues_fixed": issues_fixed,
    }
