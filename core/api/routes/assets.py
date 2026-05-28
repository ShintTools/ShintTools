# core/api/routes/assets.py
#
# Asset Naming Bot endpoints.
#
# POST /assets/scan          - UE5 plugin: detect naming violations (legacy)
# POST /assets/fix           - UE5 plugin: apply renaming corrections (legacy)
# POST /assets/unity/scan    - Unity plugin: new contract from PDF spec
#                              engine forced to "unity" — no default fallback bug

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from api.database import analysis_results, resolve_tier
from fastapi import APIRouter
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "modules"))

from code_validator.shared.tiers import get_asset_limit  # noqa: E402

router = APIRouter()

# Unity file extensions used for engine auto-detection fallback in /assets/scan
_UNITY_EXTENSIONS: frozenset[str] = frozenset(
    {".unity", ".prefab", ".controller", ".anim", ".mat", ".asset", ".shadergraph"}
)


# ── Models — legacy UE5 endpoints ─────────────────────────────────────────────


class AssetEntry(BaseModel):
    asset_path: str = ""
    name: str = ""
    type: str = ""
    category: str = ""


class AssetScanRequest(BaseModel):
    project_id: str = ""
    api_key: str = ""
    project_name: str = ""
    asset_paths: list[AssetEntry] = Field(default_factory=list)
    engine: str = "unreal"


class AssetIssueEntry(BaseModel):
    asset_path: str = ""
    current_name: str = ""
    fix_suggestion: str = ""
    reason: str = ""
    asset_type: str = ""


class AssetFixRequest(BaseModel):
    issues: list[AssetIssueEntry] = Field(default_factory=list)


# ── Models — Unity Asset Tool (PDF spec) ──────────────────────────────────────


class GenericRule(BaseModel):
    """User-defined generic rule (same logic as Code Tool custom rules)."""

    problem: str = ""
    solution: str = ""


class NamingRule(BaseModel):
    """User-defined naming rule: enforce prefix/suffix for a given asset type."""

    type: str = ""  # Unity asset type, e.g. "Texture2D", "Material"
    prefix: str = ""
    suffix: str = ""


class UnityAssetFile(BaseModel):
    """One asset entry sent by the Unity plugin."""

    path: str = ""
    type: str = ""  # Unity C# class name from AssetDatabase


class UnityAssetScanRequest(BaseModel):
    api_key: str = ""
    genericRules: list[GenericRule] = Field(default_factory=list)
    namingRules: list[NamingRule] = Field(default_factory=list)
    files: list[UnityAssetFile] = Field(default_factory=list)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _detect_engine(records: list[dict], declared: str) -> str:
    """Auto-detect Unity assets when the caller forgot to set engine.

    If every asset path starts with 'Assets/' (case-insensitive) or has a
    Unity-specific extension, force engine='unity' and log a warning so we
    can trace which plugin build is outdated.
    """
    if not records or declared == "unity":
        return declared
    unity_hits = sum(
        1
        for r in records
        if r.get("asset_path", "").lower().startswith("assets/")
        or Path(r.get("asset_path", "")).suffix.lower() in _UNITY_EXTENSIONS
    )
    if unity_hits == len(records):
        print(
            "WARNING /assets/scan: all assets look like Unity but "
            f"engine='{declared}'. Auto-correcting to 'unity'. "
            "Ask the plugin team to send engine='unity' explicitly."
        )
        return "unity"
    return declared


def _apply_naming_rule(
    file: UnityAssetFile, rule: NamingRule, rule_idx: int
) -> dict | None:
    """Check one file against one user-defined NamingRule.

    Returns a finding dict if the file violates the rule, else None.
    fix is the corrected asset name (stem only, no extension), matching
    the Asset Tool UI format 'OldName > NewName'.
    """
    if rule.type and rule.type.lower() != file.type.lower():
        return None

    p = Path(file.path)
    name = p.stem
    violated = False
    fixed = name

    if rule.prefix and not name.startswith(rule.prefix):
        violated = True
        # Strip any existing wrong prefix (everything before first _)
        rest = name.split("_", 1)[1] if "_" in name else name
        fixed = f"{rule.prefix}_{rest}"

    if rule.suffix and not fixed.endswith(rule.suffix):
        violated = True
        fixed = f"{fixed}{rule.suffix}"

    if not violated:
        return None

    return {
        "path": file.path,
        "genericRule": -1,
        "namingRule": rule_idx,
        "fix": fixed,
    }


# ── Endpoints — legacy UE5 ────────────────────────────────────────────────────


@router.post("/assets/scan")
async def scan_assets(payload: AssetScanRequest):
    """Scan asset paths for naming violations (UE5 plugin, legacy contract).

    Includes engine auto-detection fallback: if all assets look like Unity
    (paths start with Assets/ or have Unity extensions) but engine was not
    set, it is corrected to 'unity' automatically with a server-side warning.
    """
    from modules.naming import run_all_naming_rules

    tier = await resolve_tier(payload.api_key)
    asset_limit = get_asset_limit(tier)

    asset_records = [
        {"asset_path": asset.asset_path, "asset_type": asset.type or "Unknown"}
        for asset in payload.asset_paths
        if asset.asset_path
    ]

    # Fallback: auto-correct engine if Unity assets detected with wrong default
    engine = _detect_engine(asset_records, payload.engine.lower())

    total_before_cap = len(asset_records)
    if asset_limit is not None and len(asset_records) > asset_limit:
        asset_records = asset_records[:asset_limit]

    t0 = time.perf_counter()
    issues = run_all_naming_rules(asset_records, engine=engine)
    scan_time = round(time.perf_counter() - t0, 4)

    is_free = tier == "free"
    capped = asset_limit is not None and total_before_cap > asset_limit
    summary = {
        "total_assets": total_before_cap,
        "assets_scanned": len(asset_records),
        "assets_capped": capped,
        "invalid_assets": len(issues),
        "scan_time_seconds": scan_time,
        "tier": tier,
        "limit_applied": is_free,
        "limit_kind": "assets",
        "limit_value": asset_limit if asset_limit is not None else total_before_cap,
        "total_available": total_before_cap,
    }

    try:
        doc = {
            "report_type": "asset_naming",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
            "issues": [i if isinstance(i, dict) else dict(i) for i in issues],
        }
        await analysis_results.insert_one(doc)
    except Exception:
        pass

    return {"summary": summary, "issues": issues}


@router.post("/assets/fix")
async def fix_assets(payload: AssetFixRequest):
    """Apply asset renaming corrections (UE5 plugin, legacy contract)."""
    from modules.naming import apply_asset_rename

    renamed = 0
    for issue in payload.issues:
        if apply_asset_rename(issue.asset_path, issue.fix_suggestion):
            renamed += 1

    return {"assets_renamed": renamed}


# ── Endpoint — Unity Asset Tool ───────────────────────────────────────────────


@router.post("/assets/unity/scan")
async def unity_asset_scan(payload: UnityAssetScanRequest):
    """Scan Unity assets with the new Asset Tool contract (PDF spec).

    engine is always 'unity' — no default fallback bug possible.

    Three layers of checks run in order:
      1. Built-in naming rules (NMU001/NMU009/NMU016 + NM001-NM018)
         → finding: genericRule=-1, namingRule=-1
      2. User namingRules (prefix/suffix per asset type, deterministic)
         → finding: genericRule=-1, namingRule=<index>
      3. User genericRules (LLM agent when SHINTTOOLS_AGENT_ENABLED=1)
         → finding: genericRule=<index>, namingRule=-1

    Output per finding:
        path        — original asset path
        genericRule — index in payload.genericRules (-1 = not a generic rule)
        namingRule  — index in payload.namingRules  (-1 = not a naming rule)
        fix         — corrected asset name (stem only, empty if no fix available)
    """
    from modules.naming import run_all_naming_rules

    t0 = time.perf_counter()
    tier = await resolve_tier(payload.api_key)

    all_findings: list[dict] = []
    note: str = ""

    asset_records = [
        {"asset_path": f.path, "asset_type": f.type or "Unknown"}
        for f in payload.files
        if f.path
    ]

    # 1. Built-in naming rules — engine always forced to "unity"
    from code_validator.shared.tiers import filter_issues_by_tier  # noqa: E402

    raw_issues = run_all_naming_rules(asset_records, engine="unity")
    raw_issues = filter_issues_by_tier(raw_issues, tier)
    for issue in raw_issues:
        all_findings.append(
            {
                "path": issue.get("asset_path", ""),
                "genericRule": -1,
                "namingRule": -1,
                "fix": issue.get("fix_suggestion", ""),
                "rule_id": issue.get("rule_id", ""),
                "severity": issue.get("severity", "warning"),
                "message": issue.get("message", ""),
                "rule_name": issue.get("rule_name", ""),
                "is_auto_fixable": issue.get("is_auto_fixable", False),
            }
        )

    # 2. User naming rules — deterministic prefix/suffix check
    for idx, naming_rule in enumerate(payload.namingRules):
        for file_entry in payload.files:
            finding = _apply_naming_rule(file_entry, naming_rule, idx)
            if finding:
                all_findings.append(finding)

    # 3. User generic rules — LLM agent, best-effort
    if payload.genericRules:
        if os.getenv("SHINTTOOLS_AGENT_ENABLED") == "1":
            try:
                from modules.agent.custom_rule_checker import check_custom_rules

                # Adapt: generic rules have same shape as Code Tool custom rules.
                # Pass asset path as "content" so the LLM can reason about the name.
                adapted_files = [
                    {
                        "path": f.path,
                        "content": f"asset_type: {f.type}\npath: {f.path}",
                        "lines": 0,
                    }
                    for f in payload.files
                ]
                generic_issues = check_custom_rules(payload.genericRules, adapted_files)
                for issue in generic_issues:
                    rule_idx = issue.get("rule_index", 0)
                    all_findings.append(
                        {
                            "path": issue.get("path", ""),
                            "genericRule": rule_idx,
                            "namingRule": -1,
                            "fix": issue.get("fix", ""),
                        }
                    )
            except ImportError:
                note = (
                    "Generic rules require the agent module"
                    " (SHINTTOOLS_AGENT_ENABLED=1)."
                )
        else:
            note = (
                f"{len(payload.genericRules)} generic rule(s) received but "
                "LLM agent is disabled (SHINTTOOLS_AGENT_ENABLED!=1)."
            )

    return {
        "warning": note,
        "time": round(time.perf_counter() - t0, 4),
        "files": all_findings,
    }
