# core/api/routes/assets.py
#
# Asset Naming Bot endpoints.
#
# POST /assets/scan - detect all naming violations (target: < 10 s)
# POST /assets/fix - apply renaming corrections

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from api.database import analysis_results, resolve_tier
from fastapi import APIRouter
from pydantic import BaseModel, Field

# Add modules path for tiers import
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "modules"))

from code_validator.shared.tiers import get_asset_limit  # noqa: E402

router = APIRouter()


# ── Models ────────────────────────────────────────────


class AssetEntry(BaseModel):
    # Single asset entry as sent by the UE5 plugin
    asset_path: str = ""
    name: str = ""
    type: str = ""
    category: str = ""


class AssetScanRequest(BaseModel):
    # Full scan request from the UE5 plugin.
    # The plugin sends asset objects in 'assets[]',
    # not a plain list of paths.
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


# ── Endpoints ─────────────────────────────────────────


@router.post("/assets/scan")
async def scan_assets(payload: AssetScanRequest):
    """
    Scan all asset paths for naming convention violations.

    UE5 naming conventions enforced:
      - Textures:      T_  prefix
      - Static Mesh:   SM_ prefix
      - Skeletal Mesh: SK_ prefix
      - Material:      M_  prefix
      - Blueprint:     BP_ prefix
      - Sound:         S_  or SFX_ prefix
      - Particle:      P_  prefix
      - Widget BP:     WBP_ prefix
      - DataTable:     DT_ prefix
      - DataAsset:     DA_ prefix

    Sprint 4: replace type inference with real
    AssetRegistry lookups.
    """
    from modules.naming import run_all_naming_rules

    # Resolve subscription tier and apply asset limit
    tier = await resolve_tier(payload.api_key)
    asset_limit = get_asset_limit(tier)

    # Build asset records passing both path and type to the rules.
    # asset_type comes from UE5 AssetRegistry via the plugin — used
    # by NM001 (prefix) and NM009 (wrong folder) for accurate detection.
    asset_records = [
        {
            "asset_path": asset.asset_path,
            "asset_type": asset.type or "Unknown",
        }
        for asset in payload.asset_paths
        if asset.asset_path
    ]

    # Cap assets scanned based on tier (Free = 500, Indie = unlimited)
    total_before_cap = len(asset_records)
    if asset_limit is not None and len(asset_records) > asset_limit:
        asset_records = asset_records[:asset_limit]

    t0 = time.perf_counter()
    issues = run_all_naming_rules(asset_records, engine=payload.engine)
    scan_time = round(time.perf_counter() - t0, 4)

    is_free = tier == "free"
    capped = asset_limit is not None and total_before_cap > asset_limit
    summary = {
        "total_assets": total_before_cap,
        "assets_scanned": len(asset_records),
        "assets_capped": capped,  # legacy field, kept for older plugin builds
        "invalid_assets": len(issues),
        "scan_time_seconds": scan_time,
        "tier": tier,
        # ── Canonical cap-metadata (consumed by UE5 + Unity plugins).
        # `limit_applied` reflects the tier policy (Free always caps,
        # even if the project happens to have ≤ 500 assets), so the
        # plugin can render an "X of Y assets — upgrade for full scan"
        # banner without trusting client-side heuristics.
        "limit_applied": is_free,
        "limit_kind": "assets",
        "limit_value": asset_limit if asset_limit is not None else total_before_cap,
        "total_available": total_before_cap,
    }

    # Persist to MongoDB
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
    """
    Apply asset renaming corrections.
    Sprint 4: replace with real AssetRegistry rename
    via Python UE bindings.
    Currently returns a mock acknowledgement.
    """
    from modules.naming import apply_asset_rename

    renamed = 0
    for issue in payload.issues:
        if apply_asset_rename(issue.asset_path, issue.fix_suggestion):
            renamed += 1

    return {"assets_renamed": renamed}
