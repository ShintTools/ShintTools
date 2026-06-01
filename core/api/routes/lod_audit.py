# core/api/routes/lod_audit.py
#
# LOD Auditor endpoint: POST /assets/lod/audit
#
# Scans Unity/UE5 assets for LOD and optimization violations.
# Three-tier architecture:
#   - All tiers: LT001 (compression), LT003 (resolution)
#   - Indie+: All texture rules (LT001-LT005) + material + mesh rules
#
# Tier gating prevents free users from seeing premium insights.

import logging
import os
import time

from api.database import resolve_tier
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("shinttools.lod_audit")

router = APIRouter()


# Optional: LLM explainer for detailed guidance on each violation
# Only loaded if SHINTTOOLS_AGENT_ENABLED=1 and model is available
_EXPLAINER_AVAILABLE = False
_explain_issue = None

if os.getenv("SHINTTOOLS_AGENT_ENABLED") == "1":
    try:
        from agent.explainer import explain_issue as _explain

        _explain_issue = _explain
        _EXPLAINER_AVAILABLE = True
    except ImportError:
        logger.debug("LLM explainer not available — detailed guidance disabled")


# ── Models ────────────────────────────────────────────────────────────────────


class LodAssetFile(BaseModel):
    """Asset metadata for LOD auditing."""

    asset_path: str = ""
    asset_type: str = ""  # "Texture2D", "StaticMesh", "Material", etc.
    usage: str = ""  # Texture usage: "BaseColor", "Normal", "Mask", etc.
    compression: str = ""  # e.g. "BC7", "BC5", "None"
    resolution_x: int = 0  # Texture width (pixels)
    resolution_y: int = 0  # Texture height (pixels)
    vert_count: int = 0  # Mesh vertex count
    lod_count: int = 0  # Number of LOD levels
    streaming_enabled: bool = False  # Texture streaming flag


class LodAuditRequest(BaseModel):
    """Request to audit assets for LOD violations."""

    api_key: str = ""
    assets: list[LodAssetFile] = Field(default_factory=list)


class Saving(BaseModel):
    """Estimated savings if finding is fixed."""

    vram_mb: float = 0.0
    shader_instructions: int = 0
    memory_rank: int = 0  # 1=critical, 2=high, 3=medium


class Finding(BaseModel):
    """One LOD/optimization violation."""

    asset_path: str = ""
    rule_id: str = ""  # LT001, LT002, etc.
    category: str = ""  # "Texture", "Material", "Mesh"
    severity: str = ""  # "error", "warning", "info"
    message: str = ""
    auto_fixable: bool = False
    current: dict = Field(default_factory=dict)  # Current asset values
    recommended: dict = Field(default_factory=dict)  # Recommended values
    guidance: str | None = None  # Optional guidance text
    estimated_saving: Saving = Field(default_factory=Saving)


class AuditSummary(BaseModel):
    """Top-level statistics."""

    assets_audited: int = 0
    issues_found: int = 0
    auto_fixable: int = 0
    estimated_vram_saved_mb: float = 0.0
    estimated_shader_instructions_saved: int = 0


class LodAuditResponse(BaseModel):
    """Response from LOD audit."""

    error: str = ""
    time: float = 0.0
    summary: AuditSummary = Field(default_factory=AuditSummary)
    results: list[Finding] = Field(default_factory=list)


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.post("/assets/lod/audit")
async def lod_audit(payload: LodAuditRequest):
    """Audit assets for LOD and optimization issues.

    Three-tier architecture:
      - Free: LT001 (compression), LT003 (size) only
      - Indie+: All rules (LT001-LT005, LM001-LM003, LD001-LD003)

    Response includes per-finding VRAM savings estimates and
    auto-fix recommendations.
    """
    from lod_auditor import audit_assets

    t0 = time.perf_counter()
    tier = await resolve_tier(payload.api_key)
    logger.info("/assets/lod/audit: tier=%s assets=%d", tier, len(payload.assets))

    # Tier gate: LOD Auditor is Studio-exclusive.
    # Free and Indie clients receive a 403 with an upgrade prompt.
    if tier != "studio":
        logger.info("/assets/lod/audit: denied tier=%s — Studio required", tier)
        raise HTTPException(
            status_code=403,
            detail={
                "error": "LOD Auditor requires a Studio subscription.",
                "current_tier": tier,
                "required_tier": "studio",
            },
        )

    # Convert Pydantic models to dicts for the auditor
    assets_dicts = [
        {
            "asset_path": f.asset_path,
            "asset_type": f.asset_type,
            "usage": f.usage,
            "compression": f.compression,
            "resolution_x": f.resolution_x,
            "resolution_y": f.resolution_y,
            "vert_count": f.vert_count,
            "lod_count": f.lod_count,
            "streaming_enabled": f.streaming_enabled,
        }
        for f in payload.assets
        if f.asset_path
    ]

    # Studio tier: all rules visible — no filter
    allowed_rules: frozenset[str] | None = None

    # Run the audit
    try:
        audit_response = audit_assets(assets_dicts, allowed_rules=allowed_rules)
    except Exception as e:
        logger.error("/assets/lod/audit: error during audit: %s", e)
        return {
            "error": str(e),
            "time": round(time.perf_counter() - t0, 4),
            "summary": AuditSummary(),
            "results": [],
        }

    # Convert Finding objects to dicts for JSON response
    # Optionally generate LLM explanations for each finding
    results = []
    for f in audit_response.results:
        result_dict = {
            "asset_path": f.asset_path,
            "rule_id": f.rule_id,
            "category": f.category,
            "severity": f.severity,
            "message": f.message,
            "auto_fixable": f.auto_fixable,
            "current": f.current,
            "recommended": f.recommended,
            "guidance": f.guidance,
            "estimated_saving": {
                "vram_mb": round(f.estimated_saving.vram_mb, 2),
                "shader_instructions": f.estimated_saving.shader_instructions,
            },
        }

        # Generate detailed guidance via LLM if available
        if _EXPLAINER_AVAILABLE and _explain_issue and tier == "indie":
            try:
                issue_dict = {
                    "rule_id": f.rule_id,
                    "rule_name": f"{f.rule_id} — {f.message[:60]}",
                    "rule_explanation": "",  # The explainer registry will fill this from YAML
                    "asset_path": f.asset_path,
                    "message": f.message,
                    "severity": f.severity,
                    "is_auto_fixable": f.auto_fixable,
                    "current": f.current,
                    "recommended": f.recommended,
                    "snippet": f"Current: {f.current}\nRecommended: {f.recommended}",
                }
                explanation = _explain_issue(issue_dict)
                result_dict["detailed_guidance"] = explanation
                logger.debug(
                    "/assets/lod/audit: generated guidance for %s:%s",
                    f.asset_path,
                    f.rule_id,
                )
            except Exception as e:
                logger.warning(
                    "/assets/lod/audit: failed to generate guidance for %s: %s",
                    f.asset_path,
                    e,
                )

        results.append(result_dict)

    logger.info("/assets/lod/audit: completed with %d findings", len(results))

    return {
        "error": "",
        "time": round(time.perf_counter() - t0, 4),
        "summary": {
            "assets_audited": audit_response.summary.assets_audited,
            "issues_found": audit_response.summary.issues_found,
            "auto_fixable": audit_response.summary.auto_fixable,
            "estimated_vram_saved_mb": round(
                audit_response.summary.estimated_vram_saved_mb, 2
            ),
            "estimated_shader_instructions_saved": (
                audit_response.summary.estimated_shader_instructions_saved
            ),
        },
        "results": results,
    }
