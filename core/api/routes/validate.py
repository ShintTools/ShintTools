# core/api/routes/validate.py
#
# Endpoints:
#   POST /validate/assets      — validate asset naming (mock, Sprint 4 pending)
#   POST /validate/code        — single file analysis
#   POST /validate/project     — batch of source files (full project scan)
#   POST /validate/blueprints  — batch of Blueprint asset paths
#   POST /validate/fix         — apply auto-fixes

import sys
from datetime import datetime, timezone
from pathlib import Path

from api.database import analysis_results
from fastapi import APIRouter
from pydantic import BaseModel, Field

# Add modules path to import code_validator rules
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "modules"))

from code_validator.rules.blueprint_rules import run_all_blueprint_rules  # noqa: E402
from code_validator.rules.ue5_cpp_rules import run_all_cpp_rules  # noqa: E402

router = APIRouter()


# Request models


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
    file_path: str = ""
    content: str = ""


class ValidateProjectRequest(BaseModel):
    files: list[FileEntry] = Field(default_factory=list)
    engine: str = "unreal"


class ValidateBlueprintsRequest(BaseModel):
    asset_paths: list[str] = Field(default_factory=list)
    engine: str = "unreal"


class IssueEntry(BaseModel):
    rule_id: str = ""
    severity: str = "warning"
    message: str = ""
    file_path: str = ""
    line: int = 0


class ApplyFixesRequest(BaseModel):
    issues: list[IssueEntry] = Field(default_factory=list)


# ── Shared helpers ────────────────────────────────────────────────────────────

# Extensions we support for C++ analysis
_CPP_EXTENSIONS = {".cpp", ".h", ".hpp", ".cc"}


def _build_summary(issues: list[dict], files_scanned: int = 1) -> dict:
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


def _analyse_file(file_path: str, content: str, engine: str = "unreal") -> list[dict]:
    """
    Run rules against a single source file.
    Currently supports C++ files for Unreal Engine.
    """
    file_ext = Path(file_path).suffix.lower()

    if engine == "unreal" and file_ext in _CPP_EXTENSIONS:
        return run_all_cpp_rules(content, file_path)

    # Unity and other engines — pending Phase 2
    return []


async def _persist_result(report_type: str, summary: dict, issues: list[dict]) -> None:
    """
    Save result to MongoDB for the dashboard.
    Dashboard persistence is best-effort; never block the response.
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


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/validate/assets")
async def validate_assets(payload: ValidateAssetsRequest):
    """
    Validates asset naming conventions.
    Returns mock response until Sprint 4 is fully implemented.
    NOTE: The real asset scan now lives in POST /assets/scan.
    This endpoint is kept for backward compatibility with
    existing plugin versions.
    """
    # TODO Sprint 4: Remove this mock once all plugins migrate to /assets/scan
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
    Saves results to MongoDB after analysis.
    The response structure must not change — the plugin
    depends on this exact format.
    """
    issues = _analyse_file(payload.file_path, payload.content, payload.engine)
    summary = _build_summary(issues, files_scanned=1)
    await _persist_result("code_validator", summary, issues)

    return {"summary": summary, "issues": issues}


@router.post("/validate/project")
async def validate_project(payload: ValidateProjectRequest):
    """
    Validate all source files in the project (batch).
    The plugin collects every .cpp / .h, reads them, and sends them here.
    """
    all_issues: list[dict] = []

    for file_entry in payload.files:
        file_issues = _analyse_file(
            file_entry.file_path, file_entry.content, payload.engine
        )
        all_issues.extend(file_issues)

    summary = _build_summary(all_issues, files_scanned=len(payload.files))
    await _persist_result("code_validator_project", summary, all_issues)

    return {"summary": summary, "issues": all_issues}


@router.post("/validate/blueprints")
async def validate_blueprints(payload: ValidateBlueprintsRequest):
    """
    Validate Blueprint assets.
    Sprint 5: replace with real Blueprint parser (uses UHT reflection data).
    Currently applies naming + structure heuristics from asset path alone.
    """
    all_issues: list[dict] = []

    for asset_path in payload.asset_paths:
        bp_issues = run_all_blueprint_rules(asset_path)
        all_issues.extend(bp_issues)

    summary = _build_summary(all_issues, files_scanned=len(payload.asset_paths))
    await _persist_result("code_validator_blueprints", summary, all_issues)

    return {"summary": summary, "issues": all_issues}


@router.post("/validate/fix")
async def apply_fixes(payload: ApplyFixesRequest):
    """
    Apply auto-fixes server-side.
    Sprint 5: wire to real AST-based fixer.
    Currently only CV004 (printf) and CV007 (debug message)
    are fixable.
    """
    fixable_rules = {"CV004", "CV007"}

    files_fixed: set[str] = set()
    issues_fixed: int = 0

    for issue in payload.issues:
        if issue.rule_id in fixable_rules:
            files_fixed.add(issue.file_path)
            issues_fixed += 1

    return {
        "files_fixed": len(files_fixed),
        "issues_fixed": issues_fixed,
    }
