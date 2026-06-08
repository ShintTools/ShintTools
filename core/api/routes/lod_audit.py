# core/api/routes/lod_audit.py
#
# LOD Auditor endpoints:
#   POST /assets/lod/audit   — full audit, returns per-finding details
#   POST /assets/lod/report  — aggregated view (folder summary + top offenders)
#
# Both endpoints share the same scan and tier gate.

import logging
import os
import time
from typing import Any

from api.database import resolve_tier
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("shinttools.lod_audit")

router = APIRouter()


# Optional: LLM explainer for detailed guidance on each violation
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
    """Asset metadata for LOD auditing.

    A single payload model accepts fields from every category — Pydantic
    accepts the dict shape from any engine without strict per-type
    discrimination. Individual rules access fields via dict.get() with
    safe defaults, so omitted fields simply skip the rule.
    """

    asset_path: str = ""
    asset_type: str = ""
    feature_level: str = ""  # "" | "Mobile" — gates the LMB* rules

    # ── Textures
    usage: str = ""
    compression: str = ""
    width: int = 0
    height: int = 0
    srgb: bool = True
    mips_enabled: bool = True
    streaming: bool = False
    lod_group: str = "World"
    referenced_by_materials: int = -1  # -1 = plugin did not compute

    # ── Backwards-compat aliases (older plugin builds)
    resolution_x: int = 0
    resolution_y: int = 0
    streaming_enabled: bool = False

    # ── Materials
    instruction_count: int = 0
    blend_mode: str = "Opaque"
    sampler_count: int = 0
    texture_samples: list[dict] = Field(default_factory=list)
    used_by_primitives: int = -1
    is_material_instance: bool = False
    material_nodes: list[str] = Field(default_factory=list)

    # ── Meshes
    lod_count: int = 0
    lods: list[dict] = Field(default_factory=list)
    bounds_radius: float = 100.0
    vert_count: int = 0
    content_hash: str = ""
    size_kb: float = 0.0

    # ── Animations
    anim_source: str = ""
    compression_format: str = ""
    raw_size_kb: float = 0.0
    compressed_size_kb: float = 0.0
    curve_count: int = 0
    key_count: int = 0
    duration_sec: float = 0.0

    # ── Particles
    sim_target: str = ""
    max_particles: int = 0
    uses_cpu_only_modules: bool = False
    bounds_mode: str = ""

    # ── Audio
    size_mb: float = 0.0

    # ── Lighting
    resolution: int = 0
    surface_area_m2: float = 0.0
    avg_overdraw: float = 0.0


class LodAuditRequest(BaseModel):
    """Request to audit assets for LOD violations."""

    api_key: str = ""
    profile: str = "default"  # "default" | "mobile" — selects threshold YAML
    assets: list[LodAssetFile] = Field(default_factory=list)


class LodReportRequest(LodAuditRequest):
    """Request to build an aggregated LOD report.

    Same shape as audit; the response includes folder-level summary and
    top offenders instead of individual findings.
    """

    top_n: int = 10  # number of top offenders to return


class Saving(BaseModel):
    vram_mb: float = 0.0
    shader_instructions: int = 0
    memory_rank: int = 0


class Finding(BaseModel):
    asset_path: str = ""
    rule_id: str = ""
    category: str = ""
    severity: str = ""
    message: str = ""
    auto_fixable: bool = False
    current: dict = Field(default_factory=dict)
    recommended: dict = Field(default_factory=dict)
    guidance: str | None = None
    estimated_saving: Saving = Field(default_factory=Saving)


class AuditSummary(BaseModel):
    assets_audited: int = 0
    issues_found: int = 0
    auto_fixable: int = 0
    estimated_vram_saved_mb: float = 0.0
    estimated_shader_instructions_saved: int = 0


class LodAuditResponse(BaseModel):
    error: str = ""
    time: float = 0.0
    summary: AuditSummary = Field(default_factory=AuditSummary)
    results: list[Finding] = Field(default_factory=list)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _to_audit_dict(asset_model: LodAssetFile) -> dict[str, Any]:
    """Flatten the Pydantic model and apply backwards-compat field aliases."""
    asset_dict = asset_model.model_dump()
    # Aliases — older plugin builds use resolution_x/y and streaming_enabled
    if asset_dict["width"] == 0 and asset_dict["resolution_x"]:
        asset_dict["width"] = asset_dict["resolution_x"]
    if asset_dict["height"] == 0 and asset_dict["resolution_y"]:
        asset_dict["height"] = asset_dict["resolution_y"]
    if asset_dict["streaming_enabled"] and not asset_dict["streaming"]:
        asset_dict["streaming"] = True
    return asset_dict


async def _enforce_studio(api_key: str, route_label: str) -> str:
    """Tier-gate helper that returns the resolved tier or raises 403."""
    tier = await resolve_tier(api_key)
    logger.info("%s: tier=%s", route_label, tier)
    if tier != "studio":
        logger.info("%s: denied tier=%s — Studio required", route_label, tier)
        raise HTTPException(
            status_code=403,
            detail={
                "error": "LOD Auditor requires a Studio subscription.",
                "current_tier": tier,
                "required_tier": "studio",
            },
        )
    return tier


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/assets/lod/audit")
async def lod_audit(payload: LodAuditRequest):
    """Audit assets for LOD and optimization issues.

    Studio-tier only. Returns one Finding per violation plus an aggregate
    summary. Accepts ``profile`` to swap threshold sets at runtime
    (default | mobile).
    """
    from lod_auditor import audit_assets
    from lod_auditor.config import load_profile

    t0 = time.perf_counter()
    tier = await _enforce_studio(payload.api_key, "/assets/lod/audit")

    # Pre-warm the chosen threshold profile so every rule reads the same YAML.
    # load_profile is cached, so the cost is one yaml.safe_load per process.
    load_profile(payload.profile)

    assets_dicts = [_to_audit_dict(f) for f in payload.assets if f.asset_path]
    logger.info(
        "/assets/lod/audit: assets=%d profile=%s", len(assets_dicts), payload.profile
    )

    try:
        audit_response = audit_assets(assets_dicts, allowed_rules=None)
    except Exception as e:
        logger.error("/assets/lod/audit: error during audit: %s", e)
        return {
            "error": str(e),
            "time": round(time.perf_counter() - t0, 4),
            "summary": AuditSummary(),
            "results": [],
        }

    results: list[dict[str, Any]] = []
    for f in audit_response.results:
        result_dict = {
            "asset_path": f.asset_path,
            "rule_id": f.rule_id,
            "category": f.category,
            "severity": f.severity,
            "message": f.message,
            "current": f.current,
            "recommended": f.recommended,
            "auto_fixable": f.auto_fixable,
            "guidance": f.guidance,
            "estimated_saving": {
                "vram_mb": round(f.estimated_saving.vram_mb, 2),
                "shader_instructions": f.estimated_saving.shader_instructions,
            },
        }

        # Optional LLM-generated guidance (currently scoped to indie, kept
        # for forward-compat; Studio tier sees deterministic guidance).
        if _EXPLAINER_AVAILABLE and _explain_issue and tier == "studio":
            try:
                issue_dict = {
                    "rule_id": f.rule_id,
                    "rule_name": f"{f.rule_id} — {f.message[:60]}",
                    "rule_explanation": "",
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
            except Exception as e:
                logger.warning(
                    "/assets/lod/audit: guidance failed for %s: %s",
                    f.asset_path,
                    e,
                )

        results.append(result_dict)

    logger.info("/assets/lod/audit: completed with %d findings", len(results))

    return {
        "error": "",
        "time": round(time.perf_counter() - t0, 4),
        "profile": payload.profile,
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


@router.post("/assets/lod/report")
async def lod_report(payload: LodReportRequest):
    """Aggregated LOD audit report.

    Runs the same scan as /audit but returns a per-folder summary and
    the top N offenders ranked by VRAM saving. Studio-tier only.
    """
    from lod_auditor import audit_assets
    from lod_auditor.config import load_profile
    from lod_auditor.lod_report import build_folder_summary, top_offenders

    t0 = time.perf_counter()
    await _enforce_studio(payload.api_key, "/assets/lod/report")

    load_profile(payload.profile)
    assets_dicts = [_to_audit_dict(f) for f in payload.assets if f.asset_path]
    logger.info(
        "/assets/lod/report: assets=%d profile=%s top_n=%d",
        len(assets_dicts),
        payload.profile,
        payload.top_n,
    )

    try:
        audit_response = audit_assets(assets_dicts, allowed_rules=None)
    except Exception as e:
        logger.error("/assets/lod/report: error during audit: %s", e)
        return {
            "error": str(e),
            "time": round(time.perf_counter() - t0, 4),
            "summary": AuditSummary(),
            "by_folder": [],
            "top_offenders": [],
        }

    by_folder = build_folder_summary(audit_response.results)
    offenders = top_offenders(audit_response.results, payload.top_n)

    return {
        "error": "",
        "time": round(time.perf_counter() - t0, 4),
        "profile": payload.profile,
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
        "by_folder": by_folder,
        "top_offenders": offenders,
    }


@router.get("/assets/lod/profiles")
async def list_profiles():
    """List available LOD threshold profiles (no auth — discoverability)."""
    from lod_auditor.config import available_profiles

    return {"profiles": available_profiles()}
