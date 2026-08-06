# core/api/routes/lod_audit.py
#
# LOD Auditor endpoints:
#   POST /assets/lod/audit   — full audit, returns per-finding details
#   POST /assets/lod/report  — aggregated view (folder summary + top offenders)
#
# Both endpoints share the same scan and tier gate.

import asyncio
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from api.database import analysis_results, resolve_tier_detailed
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("shinttools.lod_audit")

router = APIRouter()


# Optional: LLM explainer for detailed guidance on each violation
_EXPLAINER_AVAILABLE = False
_explain_issue = None

if os.getenv("SHINTTOOLS_AGENT_ENABLED") == "1":
    try:
        from modules.agent.explainer import explain_issue as _explain

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

    # Contract v2 adds ~40 optional mesh/material/shader fields (schema.py).
    # extra="allow" forwards any of them through model_dump() to the rules
    # without re-declaring each here — rules read via dict.get(), so a field
    # the client sends but this model doesn't name still reaches its detector.
    # A handful of the most-used v2 scalars are named below for readability.
    model_config = ConfigDict(extra="allow")

    asset_path: str = ""
    asset_type: str = ""
    feature_level: str = ""  # "" | "Mobile" — gates the LMB* rules

    # ── Textures
    usage: str = ""
    compression: str = ""
    width: int = 0
    height: int = 0
    # Tri-state on purpose: None means "the collector did not report this",
    # which is not the same as False. Declaring a bool default here re-injected
    # it into every payload and destroyed the distinction the rules rely on —
    # srgb defaulting to True fired LT004 on every Normal/Mask/HDR texture in
    # a Unity project (its collector does not send the field), and streaming
    # defaulting to False reported "streaming disabled" for any client that
    # omits it. _to_audit_dict drops the Nones so each rule falls back to its
    # own documented default instead.
    srgb: bool | None = None
    mips_enabled: bool | None = None
    streaming: bool | None = None
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
    # ── Meshes (Contract v2 — most-used scalars; the rest pass via extra="allow")
    triangle_count: int = 0
    vertex_count: int = 0
    material_slot_count: int = 1
    uv_channel_count: int = 1
    lightmap_uv_index: int = -1
    uses_static_lighting: bool = False
    nanite_enabled: bool = False
    used_in_levels: int = 1

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
    # Assistant contract §7. Clients that split a large project into chained
    # batches echo back the id the FIRST batch returned; every later batch then
    # appends to that same analysis instead of creating its own. Without this
    # a 900-asset audit produced six separate analyses and the assistant could
    # only ever resolve the last ~150 assets — silently, which is worse than
    # not resolving at all. Empty = start a new analysis.
    analysis_id: str = ""
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

    # ── Per-request threshold overrides (Studio knobs) ───────────────────────
    # Optional. Each layers over the selected `profile` for this one request;
    # None = use the profile default. Friendly names map to threshold keys in
    # lod_orchestrator._OVERRIDE_TO_THRESHOLD.
    oversized_max_size: int | None = None  # global px ceiling for LT003
    uncompressed_min_size: int | None = None  # LT007 min edge (below = silent)
    uncompressed_max_size: int | None = None  # LT007 warn-escalation edge
    npot_min_size: int | None = None  # LT006 min edge
    streaming_min_size: int | None = None  # LT005 min edge

    assets: list[LodAssetFile] = Field(default_factory=list)

    def threshold_overrides(self) -> dict[str, int]:
        """Collect the non-None override knobs into the dict audit_assets wants."""
        raw = {
            "oversized_max_size": self.oversized_max_size,
            "uncompressed_min_size": self.uncompressed_min_size,
            "uncompressed_max_size": self.uncompressed_max_size,
            "npot_min_size": self.npot_min_size,
            "streaming_min_size": self.streaming_min_size,
        }
        return {k: v for k, v in raw.items() if v is not None}


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
    # A field the collector never sent must stay absent, not arrive as None —
    # rules read through dict.get(key, default) and would otherwise receive
    # None instead of their own documented fallback.
    return {k: v for k, v in asset_dict.items() if v is not None}


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
        from modules.agent.llm_backend import is_loaded, lod_adapter

        if not is_loaded():
            logger.info("/assets/lod/audit: explain skipped — LLM not loaded")
            return
    except Exception:
        return

    try:
        from modules.agent.finetuning_logger import log_explanation
    except Exception:
        log_explanation = None  # logging is optional

    # Index result dicts by identity of their finding so we can write back.
    by_finding = dict(zip(findings, result_dicts))
    ranked = sorted(findings, key=_saving_score, reverse=True)[:n]

    # Hold the shared llama lock for the whole batch: llama-cpp is not
    # reentrant-safe, and without the lock a concurrent /agent/explain
    # could race these generations (this path historically skipped it).
    from modules.agent.llm_backend import _LLAMA_LOCK

    with _LLAMA_LOCK:
        # Apply the LOD LoRA adapter (if configured) for the whole enrichment
        # batch and detach it on exit — set once, clear once. Outside this block
        # the Deep Code Validator keeps serving the unmodified Coder. A no-op when
        # no adapter is configured (plain Coder, today's behaviour).
        with lod_adapter() as lora_applied:
            if lora_applied:
                logger.info(
                    "/assets/lod/audit: LOD LoRA adapter active for enrichment"
                )
            _explain_ranked(
                ranked=ranked,
                by_finding=by_finding,
                registry_engine=registry_engine,
                explain_issue=_explain_issue,
                log_explanation=log_explanation,
            )

        # The enrichment prompts evicted the explainer's shared KV prefix
        # (~900 tokens), so the NEXT Explain click would re-pay the full
        # prefill. Re-prime it now, at the tail of an already-long request,
        # instead of on the user's next interaction. Best-effort.
        if ranked:
            try:
                from modules.agent.explainer import warmup

                warmup()
            except Exception:
                logger.debug("post-enrichment explainer re-warm failed", exc_info=True)


def _explain_ranked(
    *,
    ranked: list,
    by_finding: dict,
    registry_engine: str,
    explain_issue,
    log_explanation,
) -> None:
    """Run the explainer over the pre-ranked findings and write back guidance.

    Split out of :func:`_enrich_top_findings` so the LoRA-adapter context wraps
    exactly the generation work and nothing else. ``explain_issue`` is passed in
    (already None-checked by the caller) so this helper stays self-contained.
    """
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
            explanation = explain_issue(issue_dict)
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


async def _persist_audit(
    summary: dict[str, Any],
    results: list[dict[str, Any]],
    engine: str,
    existing_id: str = "",
) -> str:
    """Store an audit so the assistant can resolve it as a ``context_ref``.

    Mirrors ``validate._persist_result``: best-effort, never blocks the
    response, and the id is returned even when the write fails — it is then
    simply unresolvable, which the assistant reports honestly instead of
    answering about the wrong scan.

    The LOD audit was the one scan surface that produced no ``analysis_id``,
    which left the assistant's own flagship example ("Viewing: LOD Audit —
    40 findings") ungrounded: the panel had a context to show but nothing to
    send. Additive per contract §7.

    ``existing_id`` makes a chained multi-batch audit resolve as ONE analysis.
    Large projects are scanned in batches of 150 by the clients, so without it
    each batch became its own analysis and only the final one was reachable —
    the assistant would then answer about the last 150 assets while appearing
    to speak for the whole project.
    """
    if existing_id:
        try:
            await analysis_results.update_one(
                {"analysis_id": existing_id},
                {
                    "$push": {"issues": {"$each": results}},
                    "$inc": {
                        f"summary.{k}": v
                        for k, v in summary.items()
                        if isinstance(v, (int, float)) and not isinstance(v, bool)
                    },
                },
            )
        except Exception:  # noqa: BLE001 — best-effort, mirrors validate.py
            pass
        return existing_id

    analysis_id = f"an-{uuid.uuid4().hex[:12]}"
    try:
        await analysis_results.insert_one(
            {
                "analysis_id": analysis_id,
                "report_type": "lod_audit",
                "engine": engine,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "summary": summary,
                "issues": results,
            }
        )
    except Exception:  # noqa: BLE001 — best-effort, mirrors validate.py
        pass
    return analysis_id


# Studio gate + reason messages moved to api/tier_guard.py when the
# Predictive Profiler needed the identical gate. Thin wrapper kept so the
# call sites stay unchanged; passing the module-global resolver preserves the
# monkeypatch seam tests rely on (api.routes.lod_audit.resolve_tier_detailed).
async def _enforce_studio(api_key: str, route_label: str) -> str:
    from api.tier_guard import enforce_studio

    return await enforce_studio(
        api_key, route_label, "LOD Auditor", resolver=resolve_tier_detailed
    )


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
    await _enforce_studio(payload.api_key, "/assets/lod/audit")

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
            assets_dicts,
            engine=engine,
            allowed_rules=None,
            profile=payload.profile,
            overrides=payload.threshold_overrides(),
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
    #
    # Runs in a worker thread: each explanation is 20-40 s of blocking CPU
    # inference, and up to 10 of them run back-to-back — inline in this async
    # endpoint they would starve the event loop for minutes, so /health would
    # time out and the plugin's connection indicator would flip to
    # "disconnected" mid-audit.
    if payload.explain and engine == "unreal":
        await asyncio.to_thread(
            _enrich_top_findings,
            findings=audit_response.results,
            result_dicts=results,
            registry_engine=_REGISTRY_ENGINE[engine],
            max_explanations=payload.max_explanations,
        )

    logger.info("/assets/lod/audit: completed with %d findings", len(results))

    summary = {
        "assets_audited": audit_response.summary.assets_audited,
        "issues_found": audit_response.summary.issues_found,
        "auto_fixable": audit_response.summary.auto_fixable,
        "estimated_vram_saved_mb": round(
            audit_response.summary.estimated_vram_saved_mb, 2
        ),
        "estimated_shader_instructions_saved": (
            audit_response.summary.estimated_shader_instructions_saved
        ),
    }

    return {
        "error": "",
        "time": round(time.perf_counter() - t0, 4),
        "profile": payload.profile,
        "summary": summary,
        "results": results,
        "analysis_id": await _persist_audit(
            summary, results, engine, payload.analysis_id
        ),
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
            assets_dicts,
            engine=engine,
            allowed_rules=None,
            profile=payload.profile,
            overrides=payload.threshold_overrides(),
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
