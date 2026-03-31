# core/api/routes/assets.py
#
# Asset Naming Bot endpoints.
#
# POST /assets/scan - detect all naming violations (target: < 10 s)
# POST /assets/fix - apply renaming corrections

import time
from datetime import datetime, timezone

from api.database import analysis_results
from fastapi import APIRouter
from pydantic import BaseModel, Field

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
    # Raúl sends the array under 'asset_paths' (not 'assets').
    project_id: str = ""
    api_key: str = ""
    project_name: str = ""
    asset_paths: list[AssetEntry] = Field(
        default_factory=list,
        alias="asset_paths",
    )
    engine: str = "unreal"

    model_config = {"populate_by_name": True}


class AssetIssueEntry(BaseModel):
    asset_path: str = ""
    current_name: str = ""
    suggested_name: str = ""
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
    from modules.naming import scan_asset_paths

    # Extract asset_path strings from the asset objects
    # sent by the plugin
    extracted_paths = [
        entry.asset_path for entry in payload.asset_paths if entry.asset_path
    ]

    t0 = time.perf_counter()
    issues = scan_asset_paths(extracted_paths)
    scan_time = round(time.perf_counter() - t0, 4)

    summary = {
        "total_assets": len(extracted_paths),
        "invalid_assets": len(issues),
        "scan_time_seconds": scan_time,
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
        if apply_asset_rename(issue.asset_path, issue.suggested_name):
            renamed += 1

    return {"assets_renamed": renamed}
