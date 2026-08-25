# core/api/routes/assets.py
#
# Asset Naming Bot endpoints.
#
# POST /assets/scan          - UE5 plugin: detect naming violations (legacy)
# POST /assets/fix           - UE5 plugin: apply renaming corrections (legacy)
# POST /assets/unity/scan    - Unity plugin: new contract from PDF spec
#                              engine forced to "unity" — no default fallback bug

import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from api.database import analysis_results, resolve_tier
from api.middleware import enforce_same_origin
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

logger = logging.getLogger("shinttools.assets")

# Optional: custom rule checker for layer-3 (LLM). Imported at module level
# so tests can monkeypatch api.routes.assets.check_custom_rules directly.
# Falls back gracefully when the agent module is not installed.
try:
    from modules.agent.custom_rule_checker import (  # noqa: E402
        CustomRule as _CustomRule,
    )
    from modules.agent.custom_rule_checker import check_custom_rules

    _CHECKER_AVAILABLE = True
except ImportError:
    _CHECKER_AVAILABLE = False
    _CustomRule = None  # type: ignore[assignment]
    check_custom_rules = None  # type: ignore[assignment]

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
        logger.warning(
            "/assets/scan: all assets look like Unity but engine='%s'. "
            "Auto-correcting to 'unity'. "
            "Ask the plugin team to send engine='unity' explicitly.",
            declared,
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
        # Strip any existing wrong prefix (everything before the first _).
        rest = name.split("_", 1)[1] if "_" in name else name
        # Fall back to the full name if the extracted rest is empty or
        # starts with a non-alphanumeric character (e.g. name was "T_").
        if not rest or not rest[0].isalnum():
            rest = name
        # Don't add an extra _ when the prefix already ends with one.
        sep = "" if rule.prefix.endswith("_") else "_"
        fixed = f"{rule.prefix}{sep}{rest}"

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
async def scan_assets(payload: AssetScanRequest, request: Request):
    """Scan asset paths for naming violations (UE5 plugin, legacy contract).

    Includes engine auto-detection fallback: if all assets look like Unity
    (paths start with Assets/ or have Unity extensions) but engine was not
    set, it is corrected to 'unity' automatically with a server-side warning.

    api_key is optional (Free tier scans with none) so this stays reachable
    without a full auth requirement — but that means it must not be
    reachable by a forged cross-origin browser request either (CSRF,
    security audit 2026-08-25); enforce_same_origin closes that gap without
    touching the tier semantics.
    """
    enforce_same_origin(request)
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

    # analysis_id doubles as the assistant's context_ref — generated even
    # when the insert fails (then simply unresolvable, reported honestly).
    analysis_id = f"an-{uuid.uuid4().hex[:12]}"
    try:
        doc = {
            "analysis_id": analysis_id,
            "report_type": "asset_naming",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
            "issues": [i if isinstance(i, dict) else dict(i) for i in issues],
        }
        await analysis_results.insert_one(doc)
    except Exception:
        pass

    return {"summary": summary, "issues": issues, "analysis_id": analysis_id}


@router.post("/assets/fix")
async def fix_assets(payload: AssetFixRequest, request: Request):
    """Apply asset renaming corrections (UE5 plugin, legacy contract).

    No api_key field in this legacy contract at all — see scan_assets for
    why enforce_same_origin is the appropriate gate here (CSRF, security
    audit 2026-08-25) rather than introducing a new mandatory-key
    requirement that would break the shipped plugin's existing calls.
    """
    enforce_same_origin(request)
    from modules.naming import apply_asset_rename

    renamed = 0
    for issue in payload.issues:
        if apply_asset_rename(issue.asset_path, issue.fix_suggestion):
            renamed += 1

    return {"assets_renamed": renamed}


# ── Endpoint — Unity Asset Tool ───────────────────────────────────────────────


async def _persist_unity_scan(findings: list[dict]) -> str:
    """Persist a Unity asset scan and return its analysis_id.

    Mirrors _persist_result in validate.py and the inline block in
    /assets/scan just above — analysis_id doubles as the assistant's
    context_ref, so it is generated and returned even when the insert
    fails (then simply unresolvable, which the assistant reports
    honestly). Before this, /assets/unity/scan never persisted a result
    at all, so "explain this finding" could never resolve a Unity finding
    server-side — the client had nothing to hand back as context_ref.

    Findings here key the asset path as "path" (the Unity Asset Tool
    contract), but explain_finding's lookup reads "asset_path"/"file" —
    mirrored onto each entry so the same resolution logic works
    regardless of which engine produced the analysis.
    """
    analysis_id = f"an-{uuid.uuid4().hex[:12]}"
    try:
        doc = {
            "analysis_id": analysis_id,
            "report_type": "asset_naming_unity",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "issues": [
                {**f, "asset_path": f.get("path", "")} for f in findings
            ],
        }
        await analysis_results.insert_one(doc)
    except Exception:
        pass
    return analysis_id


@router.post("/assets/unity/scan")
async def unity_asset_scan(payload: UnityAssetScanRequest, request: Request):
    """Scan Unity assets with the new Asset Tool contract (PDF spec).

    engine is always 'unity' — no default fallback bug possible.

    Three layers of checks run in order:
      1. Built-in naming rules (NMU001/NMU009/NMU016 + NM001-NM018)
         → finding: genericRule=-1, namingRule=-1
         → available to all tiers
      2. User namingRules (prefix/suffix per asset type, deterministic)
         → finding: genericRule=-1, namingRule=<index>
         → indie+ only
      3. User genericRules (LLM agent when SHINTTOOLS_AGENT_ENABLED=1)
         → finding: genericRule=<index>, namingRule=-1
         → indie+ only; silently skipped when agent disabled

    Output per finding:
        path        — original asset path
        genericRule — index in payload.genericRules (-1 = not a generic rule)
        namingRule  — index in payload.namingRules  (-1 = not a naming rule)
        fix         — corrected asset name (stem only, empty if unavailable)

    Also returns analysis_id (top level) — the assistant's context_ref for
    "explain this finding" follow-ups, same contract as /assets/scan and
    every Code Validator endpoint.

    api_key is optional here too (the Unity plugin scans on Free with none),
    so the same CSRF gate as /assets/scan applies — see enforce_same_origin.
    """
    enforce_same_origin(request)
    from modules.naming import run_all_naming_rules

    t0 = time.perf_counter()
    tier = await resolve_tier(payload.api_key)
    logger.info(
        "/assets/unity/scan: tier=%s files=%d namingRules=%d genericRules=%d",
        tier,
        len(payload.files),
        len(payload.namingRules),
        len(payload.genericRules),
    )

    all_findings: list[dict] = []

    asset_records = [
        {"asset_path": f.path, "asset_type": f.type or "Unknown"}
        for f in payload.files
        if f.path
    ]

    # ── Layer 1: built-in naming rules — all tiers ────────────────────────
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
            }
        )
    logger.info("/assets/unity/scan: layer1=%d findings", len(all_findings))

    # Layers 2 and 3 are indie+ features.
    if tier == "free":
        analysis_id = await _persist_unity_scan(all_findings)
        return {
            "error": "",
            "time": round(time.perf_counter() - t0, 4),
            "files": all_findings,
            "analysis_id": analysis_id,
        }

    # ── Layer 2: user naming rules — deterministic prefix/suffix ─────────
    layer2_count = 0
    for idx, naming_rule in enumerate(payload.namingRules):
        for file_entry in payload.files:
            finding = _apply_naming_rule(file_entry, naming_rule, idx)
            if finding:
                all_findings.append(finding)
                layer2_count += 1
    logger.info("/assets/unity/scan: layer2=%d findings", layer2_count)

    # ── Layer 3: user generic rules — LLM, best-effort ───────────────────
    layer3_count = 0
    if payload.genericRules:
        if os.getenv("SHINTTOOLS_AGENT_ENABLED") == "1":
            if not _CHECKER_AVAILABLE or check_custom_rules is None:
                logger.warning(
                    "/assets/unity/scan: custom_rule_checker not available — "
                    "layer 3 skipped"
                )
            else:
                # Map GenericRule → CustomRule (name=problem, description=solution).
                adapted_rules = [
                    _CustomRule(
                        name=gr.problem,
                        description=gr.solution,
                    )
                    for gr in payload.genericRules
                ]
                # Map UnityAssetFile → (path, content) tuple.
                adapted_files = [
                    (f.path, f"asset_type: {f.type}\npath: {f.path}")
                    for f in payload.files
                    if f.path
                ]
                logger.debug(
                    "/assets/unity/scan: layer3 calling LLM with %d rules, %d files",
                    len(adapted_rules),
                    len(adapted_files),
                )
                violations = check_custom_rules(adapted_rules, adapted_files)
                # Map RuleViolation back to the (genericRule index, path, fix) shape.
                rule_name_to_idx = {
                    gr.problem: i for i, gr in enumerate(payload.genericRules)
                }
                for v in violations:
                    rule_idx = rule_name_to_idx.get(v.rule_name, 0)
                    all_findings.append(
                        {
                            "path": v.file_path,
                            "genericRule": rule_idx,
                            "namingRule": -1,
                            "fix": v.fix_suggestion,
                        }
                    )
                    layer3_count += 1
        else:
            logger.debug(
                "/assets/unity/scan: SHINTTOOLS_AGENT_ENABLED!=1 — layer 3 skipped"
            )
    logger.info("/assets/unity/scan: layer3=%d findings", layer3_count)

    analysis_id = await _persist_unity_scan(all_findings)
    return {
        "error": "",
        "time": round(time.perf_counter() - t0, 4),
        "files": all_findings,
        "analysis_id": analysis_id,
    }
