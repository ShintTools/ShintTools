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

from api.database import resolve_tier_detailed
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
    # Engine drives engine-aware fix guidance (Unreal vs Unity wording) and,
    # when explain=True, which agent prompt template is used. Accepts any of
    # "unreal"/"ue5"/"unity"/"unity6" (case-insensitive); normalised internally.
    engine: str = "unreal"
    # Bounded LLM enrichment (Unreal only). When explain=True, after the
    # deterministic findings are computed the top `max_explanations` findings
    # (by estimated saving) get an LLM-written `ai_guidance`. Off by default
    # because each explanation costs ~20-40s on CPU.
    explain: bool = False
    max_explanations: int = 5
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


def _normalize_engine(raw: str) -> str:
    """Map any engine spelling the plugin sends to the canonical rule engine.

    Rules + guidance key off "unreal" / "unity". Anything unrecognised
    defaults to "unreal" (the historical behaviour before the field existed).
    """
    e = (raw or "").strip().lower()
    if e in ("unity", "unity6"):
        return "unity"
    return "unreal"


# Canonical engine -> the agent prompt-registry engine token. The registry
# resolves LOD templates as templates/lod_auditor/{engine}/vN.yaml; only "ue5"
# exists today, so Unity findings are never sent to the LLM (deterministic
# guidance only — see the enrichment guard below).
_REGISTRY_ENGINE = {"unreal": "ue5", "unity": "unity6"}

# Hard ceiling on enrichment regardless of what the client requests — the model
# is CPU-only at ~20-40s/finding, so even Studio can't ask for a 200-finding
# enrichment that would block the request for over an hour.
_MAX_EXPLANATIONS_CEILING = 10


def _saving_score(finding) -> float:
    """Rank key for enrichment: VRAM saved + a small weight on shader savings.

    Highest-impact findings get the (expensive) LLM treatment first.
    """
    s = finding.estimated_saving
    return s.vram_mb + 0.01 * s.shader_instructions


def _enrich_top_findings(
    *,
    findings: list,
    result_dicts: list[dict[str, Any]],
    registry_engine: str,
    max_explanations: int,
) -> None:
    """Attach LLM ``ai_guidance`` to the top-N findings, best-effort.

    Sorts findings by estimated saving, takes the top ``max_explanations``
    (clamped to [0, ceiling]), runs the explainer on each, and writes the text
    into the matching result dict. Every step is guarded: a slow/unloaded model
    or a single failed call never affects the deterministic results already in
    ``result_dicts``. Each explanation is logged to JSONL for fine-tuning.
    """
    if not _EXPLAINER_AVAILABLE or _explain_issue is None:
        return

    n = max(0, min(max_explanations, _MAX_EXPLANATIONS_CEILING))
    if n == 0 or not findings:
        return

    # The model lives in the agent process; if it hasn't finished loading we
    # skip enrichment entirely rather than blocking on a cold load.
    try:
        from agent.llm_backend import is_loaded

        if not is_loaded():
            logger.info("/assets/lod/audit: explain skipped — LLM not loaded")
            return
    except Exception:
        return

    try:
        from agent.finetuning_logger import log_explanation
    except Exception:
        log_explanation = None  # logging is optional

    # Index result dicts by identity of their finding so we can write back.
    by_finding = dict(zip(findings, result_dicts))
    ranked = sorted(findings, key=_saving_score, reverse=True)[:n]

    for f in ranked:
        issue_dict = {
            "rule_id": f.rule_id,
            "rule_name": f.rule_name,
            "rule_explanation": f.rule_explanation,
            "engine": registry_engine,  # stamp so the registry picks the template
            "asset_path": f.asset_path,
            "message": f.message,
            "severity": f.severity,
            "is_auto_fixable": f.auto_fixable,
            "current": f.current,
            "recommended": f.recommended,
            "snippet": f"Current: {f.current}\nRecommended: {f.recommended}",
        }
        started = time.perf_counter()
        try:
            explanation = _explain_issue(issue_dict)
        except Exception as e:  # noqa: BLE001 — never let one failure abort
            logger.warning(
                "/assets/lod/audit: explain failed for %s (%s): %s",
                f.asset_path,
                f.rule_id,
                e,
            )
            continue
        elapsed = round(time.perf_counter() - started, 2)

        target = by_finding.get(f)
        if target is not None:
            target["ai_guidance"] = explanation

        if log_explanation is not None:
            try:
                log_explanation(
                    rule_id=f.rule_id,
                    rule_name=f.rule_name,
                    rule_explanation=f.rule_explanation,
                    explanation_generated=explanation,
                    issue_payload=issue_dict,
                    generation_seconds=elapsed,
                )
            except Exception:  # noqa: BLE001 — best-effort logging
                pass


# Human-readable cause per resolve_tier reason code. Surfaced in the 403
# so the developer knows WHY the gate denied them instead of a bare
# "Forbidden" — the common case (key bound to another machine / never
# activated on this one / no key configured) is otherwise invisible
# without opening the Core's Docker logs.
_REASON_MESSAGES = {
    "empty_key": (
        "No license key is configured. Sign in or paste your Indie/Studio "
        "key in the launcher (Settings → License), then restart the Core."
    ),
    "key_not_found": (
        "This license key isn't active on this machine. A key is bound 1:1 "
        "to the first machine that activates it — if it's already in use on "
        "another computer, release it from shint.tools/account/devices or "
        "use your own key."
    ),
    "db_unavailable": (
        "Couldn't reach the license database. Make sure Docker Desktop and "
        "the ShintTools Core container are running, then try again."
    ),
}


async def _enforce_studio(api_key: str, route_label: str) -> str:
    """Tier-gate helper that returns the resolved tier or raises 403.

    Uses :func:`resolve_tier_detailed` so the 403 carries a specific,
    actionable reason (bound elsewhere / no key / DB down) rather than a
    generic Forbidden.
    """
    tier, reason = await resolve_tier_detailed(api_key)
    logger.info("%s: tier=%s reason=%s", route_label, tier, reason or "-")
    if tier != "studio":
        logger.info(
            "%s: denied tier=%s reason=%s — Studio required",
            route_label, tier, reason or "-",
        )
        # When the tier simply isn't high enough (valid key, lower plan)
        # there's no reason code — that's a genuine upgrade prompt. When a
        # reason IS set, the key didn't resolve at all, so explain why.
        hint = _REASON_MESSAGES.get(reason, "")
        detail = {
            "error": "LOD Auditor requires a Studio subscription.",
            "current_tier": tier,
            "required_tier": "studio",
        }
        if reason:
            detail["reason"] = reason
            detail["message"] = hint
        raise HTTPException(status_code=403, detail=detail)
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

    engine = _normalize_engine(payload.engine)
    assets_dicts = [_to_audit_dict(f) for f in payload.assets if f.asset_path]
    logger.info(
        "/assets/lod/audit: assets=%d profile=%s engine=%s explain=%s",
        len(assets_dicts),
        payload.profile,
        engine,
        payload.explain,
    )

    try:
        audit_response = audit_assets(
            assets_dicts, engine=engine, allowed_rules=None
        )
    except Exception as e:
        logger.error("/assets/lod/audit: error during audit: %s", e)
        return {
            "error": str(e),
            "time": round(time.perf_counter() - t0, 4),
            "summary": AuditSummary(),
            "results": [],
        }

    # Build the deterministic result list first. These are always returned in
    # full — LLM enrichment (below) is best-effort and never blocks or drops
    # them. Each dict pairs 1:1 with its Finding so we can attach ai_guidance
    # to the selected top-N afterwards.
    results: list[dict[str, Any]] = []
    for f in audit_response.results:
        results.append(
            {
                "asset_path": f.asset_path,
                "rule_id": f.rule_id,
                "rule_name": f.rule_name,
                "category": f.category,
                "severity": f.severity,
                "message": f.message,
                "current": f.current,
                "recommended": f.recommended,
                "auto_fixable": f.auto_fixable,
                "guidance": f.guidance,
                "ai_guidance": None,
                "engine": f.engine,
                "estimated_saving": {
                    "vram_mb": round(f.estimated_saving.vram_mb, 2),
                    "shader_instructions": f.estimated_saving.shader_instructions,
                },
            }
        )

    # Bounded LLM enrichment — Unreal only, opt-in, top-N by estimated saving.
    # Off by default; never runs for Unity (no unity6 LOD template) and never
    # blocks the deterministic results if the model is slow or not loaded.
    if payload.explain and engine == "unreal":
        _enrich_top_findings(
            findings=audit_response.results,
            result_dicts=results,
            registry_engine=_REGISTRY_ENGINE[engine],
            max_explanations=payload.max_explanations,
        )

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
    engine = _normalize_engine(payload.engine)
    assets_dicts = [_to_audit_dict(f) for f in payload.assets if f.asset_path]
    logger.info(
        "/assets/lod/report: assets=%d profile=%s engine=%s top_n=%d",
        len(assets_dicts),
        payload.profile,
        engine,
        payload.top_n,
    )

    try:
        audit_response = audit_assets(
            assets_dicts, engine=engine, allowed_rules=None
        )
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
