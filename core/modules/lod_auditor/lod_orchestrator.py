# core/modules/lod_auditor/lod_orchestrator.py
#
# Entry point for the LOD Auditor core engine.
#
# audit_assets() receives the raw asset list from the plugin, dispatches
# each asset to the correct rule set based on asset_type, applies the
# tier filter, runs cross-asset detectors over the full batch, and
# returns a fully assembled AuditResponse.

import copy
import inspect
from typing import Any, Callable

from lod_auditor.config import load_profile
from lod_auditor.rules import lod_geometry as _geo
from lod_auditor.rules import lod_normals as _nrm
from lod_auditor.rules import lod_rendering as _rnd
from lod_auditor.rules import lod_shaders as _shd
from lod_auditor.rules import lod_uv as _uv
from lod_auditor.rules.lod_animations import check_la001, check_la002, check_la003
from lod_auditor.rules.lod_audio import check_lu001, check_lu002
from lod_auditor.rules.lod_cross import (
    check_lt015_streaming_pool,
    check_lx001_dead_textures,
    check_lx002_dead_materials,
    check_lx003_duplicate_meshes,
    check_lx004_unused_material_instance,
    check_lx005_duplicate_textures,
    check_lx006_same_source_multisize,
)
from lod_auditor.rules.lod_lighting import check_ll001, check_ll002
from lod_auditor.rules.lod_materials import (
    check_lm001,
    check_lm002,
    check_lm003,
    check_lm004,
    check_lm005,
    check_lm006,
    check_lm007,
    check_lm008,
    check_lm009,
    check_lm010,
    check_lm011,
    check_lm012,
    check_lm013,
    check_lm014,
)
from lod_auditor.rules.lod_meshes import (
    check_ld001,
    check_ld002,
    check_ld003,
    check_ld004,
    check_ld005,
    check_ld006,
    check_ld007,
    check_ld008,
    check_ld009,
    check_ld010,
    check_ld011,
    check_ld012,
    check_ld013,
)
from lod_auditor.rules.lod_mobile import (
    check_lmb001_sampler_count,
    check_lmb002_compression,
    check_lmb003_forbidden_nodes,
)
from lod_auditor.rules.lod_particles import check_lv001, check_lv002, check_lv003
from lod_auditor.rules.lod_textures import (
    check_lt001,
    check_lt002,
    check_lt003,
    check_lt004,
    check_lt005,
    check_lt006,
    check_lt007,
    check_lt008,
    check_lt009,
    check_lt010,
    check_lt013,
    check_lt014,
    check_lt016,
)
from lod_auditor.schema import AuditResponse, AuditSummary, Finding

# A rule detector — per-asset check_xxNNN(asset, engine[, thresholds]) or a
# cross-asset check_lxNNN(assets, engine[, thresholds]). The registries mix both
# arities, so the aggregate is typed loosely and each rule validates its own args.
RuleFn = Callable[..., Any]

# ── Rule registries ───────────────────────────────────────────────────────────
#
# Ordered lists so findings always appear in the same sequence regardless
# of dict iteration order.  Add new rules by appending here.

TEXTURE_RULES: list[RuleFn] = [
    check_lt001,
    check_lt002,
    check_lt003,
    check_lt004,
    check_lt005,
    check_lt006,
    check_lt007,
    check_lt008,
    check_lt009,
    check_lt010,
    check_lt013,
    check_lt014,
    check_lt016,
]
MATERIAL_RULES: list[RuleFn] = [
    check_lm001,
    check_lm002,
    check_lm003,
    check_lm004,
    check_lm005,
    check_lm006,
    check_lm007,
    check_lm008,
    check_lm009,
    check_lm010,
    check_lm011,
    check_lm012,
    check_lm013,
    check_lm014,
]
MESH_RULES: list[RuleFn] = [
    check_ld001,
    check_ld002,
    check_ld003,
    check_ld004,
    check_ld005,
    check_ld006,
    check_ld007,
    check_ld008,
    check_ld009,
    check_ld010,
    check_ld011,
    check_ld012,
    check_ld013,
]
# Part-2 mesh families (geometry / UV / normals) — dispatched with MESH_RULES.
GEOMETRY_RULES: list[RuleFn] = [
    _geo.check_lg001,
    _geo.check_lg002,
    _geo.check_lg003,
    _geo.check_lg004,
    _geo.check_lg005,
    _geo.check_lg006,
    _geo.check_lg007,
    _geo.check_lg008,
    _geo.check_lg009,
    _geo.check_lg010,
    _geo.check_lg011,
    _geo.check_lg012,
    _geo.check_lg013,
    _geo.check_lg014,
    _geo.check_lg015,
]
UV_RULES: list[RuleFn] = [
    _uv.check_lw001,
    _uv.check_lw002,
    _uv.check_lw003,
    _uv.check_lw004,
    _uv.check_lw005,
    _uv.check_lw006,
    _uv.check_lw007,
    _uv.check_lw008,
    _uv.check_lw009,
    _uv.check_lw010,
]
NORMAL_RULES: list[RuleFn] = [
    _nrm.check_ln001,
    _nrm.check_ln002,
    _nrm.check_ln003,
    _nrm.check_ln004,
    _nrm.check_ln005,
    _nrm.check_ln006,
]
# Part-2 material families (rendering cost / shader) — dispatched with MATERIAL_RULES.
RENDERING_RULES: list[RuleFn] = [
    _rnd.check_lr001,
    _rnd.check_lr002,
    _rnd.check_lr003,
    _rnd.check_lr004,
    _rnd.check_lr005,
    _rnd.check_lr006,
    _rnd.check_lr007,
    _rnd.check_lr008,
]
SHADER_RULES: list[RuleFn] = [
    _shd.check_ls001,
    _shd.check_ls002,
    _shd.check_ls003,
    _shd.check_ls004,
    _shd.check_ls005,
    _shd.check_ls006,
    _shd.check_ls007,
    _shd.check_ls008,
    _shd.check_ls009,
    _shd.check_ls010,
    _shd.check_ls011,
    _shd.check_ls012,
]
ANIM_RULES: list[RuleFn] = [check_la001, check_la002, check_la003]
PARTICLE_RULES: list[RuleFn] = [check_lv001, check_lv002, check_lv003]
AUDIO_RULES: list[RuleFn] = [check_lu001, check_lu002]
LIGHTING_RULES: list[RuleFn] = [check_ll001, check_ll002]

# Mobile rules dispatch by asset_type internally but are gated by the
# feature_level flag the asset carries — they're added to whichever
# category list matches their target asset type.
MOBILE_RULES_BY_TYPE: dict[str, list[RuleFn]] = {
    "Material": [
        check_lmb001_sampler_count,
        check_lmb003_forbidden_nodes,
    ],
    "Texture": [check_lmb002_compression],
}

# Cross-asset rules see the entire batch at once — distinct list.
CROSS_RULES: list[RuleFn] = [
    check_lx001_dead_textures,
    check_lx002_dead_materials,
    check_lx003_duplicate_meshes,
    check_lx004_unused_material_instance,
    check_lx005_duplicate_textures,
    check_lx006_same_source_multisize,
    check_lt015_streaming_pool,
]

# Findings for these rules are dropped when any of their suppressors fired on
# the same asset — one finding per root cause (§18.1 LM008).
_SUPPRESSED_BY: dict[str, list[str]] = {"LM008": ["LM001"]}

# ── Threshold injection ───────────────────────────────────────────────────────
#
# A rule "opts in" to per-request thresholds simply by declaring a
# ``thresholds`` keyword parameter. We detect that once at import via
# introspection, so adding the param to any future rule auto-enables override
# support without touching this dispatcher. Rules without it keep reading their
# module-level THRESHOLDS (the default profile) — behaviour unchanged.
_ALL_RULE_FNS: list[RuleFn] = (
    TEXTURE_RULES
    + MATERIAL_RULES
    + MESH_RULES
    + GEOMETRY_RULES
    + UV_RULES
    + NORMAL_RULES
    + RENDERING_RULES
    + SHADER_RULES
    + ANIM_RULES
    + PARTICLE_RULES
    + AUDIO_RULES
    + LIGHTING_RULES
    + CROSS_RULES
    + MOBILE_RULES_BY_TYPE["Material"]
    + MOBILE_RULES_BY_TYPE["Texture"]
)
# Aggregate every registered rule function — consumed by rule_metadata (docstring
# harvest) and validate_core_structure (metadata/guidance/threshold gates).
ALL_RULES = list(_ALL_RULE_FNS)
_THRESHOLD_AWARE: frozenset = frozenset(
    fn for fn in _ALL_RULE_FNS if "thresholds" in inspect.signature(fn).parameters
)

# Per-request override field -> threshold key it rewrites. The request exposes
# friendly names (e.g. "oversized_max_size"); _build_thresholds maps them onto
# the YAML threshold keys the rules actually read. Unknown/None overrides are
# ignored, so an older client that doesn't send them gets the profile defaults.
_OVERRIDE_TO_THRESHOLD: dict[str, str] = {
    "oversized_max_size": "LT003_GLOBAL_MAX_SIZE",
    "uncompressed_min_size": "LT007_UNCOMPRESSED_MIN_EDGE",
    "uncompressed_max_size": "LT007_UNCOMPRESSED_MAX_EDGE",
    "npot_min_size": "LT006_NPOT_MIN_EDGE",
    "streaming_min_size": "LT005_STREAMING_MIN_EDGE",
}


def _build_thresholds(
    profile: str = "default", overrides: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Resolve the effective threshold set for one audit run.

    Starts from the cached YAML profile (``default`` | ``mobile`` | …) and
    layers any per-request overrides on top. The profile dict is deep-copied
    before mutation because ``load_profile`` is ``lru_cache``-backed and hands
    back a shared object — writing to it would poison every later request.
    """
    thresholds: dict[str, Any] = copy.deepcopy(load_profile(profile))
    if overrides:
        for field, value in overrides.items():
            if value is None:
                continue
            key = _OVERRIDE_TO_THRESHOLD.get(field)
            if key is not None:
                thresholds[key] = value
    return thresholds


# ── Asset-type routing tables ─────────────────────────────────────────────────

_TEXTURE_ASSET_TYPES: frozenset[str] = frozenset(
    {"Texture2D", "Texture", "Texture2DArray", "TextureCube", "VolumeTexture"}
)
_MATERIAL_ASSET_TYPES: frozenset[str] = frozenset(
    {
        "Material",
        "MaterialInstance",
        "MaterialInstanceConstant",
        "MaterialInstanceDynamic",
    }
)
_MESH_ASSET_TYPES: frozenset[str] = frozenset({"StaticMesh", "SkeletalMesh", "Mesh"})
_ANIM_ASSET_TYPES: frozenset[str] = frozenset(
    {"AnimSequence", "AnimMontage", "BlendSpace", "SkeletalMesh"}
)
_PARTICLE_ASSET_TYPES: frozenset[str] = frozenset({"NiagaraSystem", "ParticleSystem"})
_AUDIO_ASSET_TYPES: frozenset[str] = frozenset({"SoundWave", "AudioClip", "Sound"})
_LIGHTING_ASSET_TYPES: frozenset[str] = frozenset(
    {"Lightmap", "PointLight", "SpotLight", "RectLight"}
)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _dispatch_asset(
    asset: dict[str, Any], engine: str, thresholds: dict[str, Any] | None = None
) -> list[Finding]:
    """Run all rules applicable to *asset* and return their findings.

    *engine* ("unreal" | "unity") is threaded to each rule so it can emit
    engine-appropriate guidance via lod_auditor.guidance.guidance_for.
    *thresholds* (when provided) is passed only to rules that declare a
    ``thresholds`` parameter; the rest read their module defaults.
    """
    asset_type: str = asset.get("asset_type", "")

    rules: list = []
    if asset_type in _TEXTURE_ASSET_TYPES:
        rules.extend(TEXTURE_RULES)
        rules.extend(MOBILE_RULES_BY_TYPE.get("Texture", []))
    if asset_type in _MATERIAL_ASSET_TYPES:
        rules.extend(MATERIAL_RULES)
        rules.extend(RENDERING_RULES)
        rules.extend(SHADER_RULES)
        rules.extend(MOBILE_RULES_BY_TYPE.get("Material", []))
    if asset_type in _MESH_ASSET_TYPES:
        rules.extend(MESH_RULES)
        rules.extend(GEOMETRY_RULES)
        rules.extend(UV_RULES)
        rules.extend(NORMAL_RULES)
    if asset_type in _ANIM_ASSET_TYPES:
        rules.extend(ANIM_RULES)
    if asset_type in _PARTICLE_ASSET_TYPES:
        rules.extend(PARTICLE_RULES)
    if asset_type in _AUDIO_ASSET_TYPES:
        rules.extend(AUDIO_RULES)
    if asset_type in _LIGHTING_ASSET_TYPES:
        rules.extend(LIGHTING_RULES)

    if not rules:
        return []

    findings: list[Finding] = []
    for check_fn in rules:
        if thresholds is not None and check_fn in _THRESHOLD_AWARE:
            result = check_fn(asset, engine, thresholds=thresholds)
        else:
            result = check_fn(asset, engine)
        if result is not None:
            findings.append(result)

    return _apply_suppression(findings)


def _apply_suppression(findings: list[Finding]) -> list[Finding]:
    """Drop a finding when any of its _SUPPRESSED_BY suppressors also fired on
    the same asset — one finding per root cause (§18.1 LM008)."""
    if not _SUPPRESSED_BY:
        return findings
    fired = {f.rule_id for f in findings}
    return [
        f
        for f in findings
        if not any(s in fired for s in _SUPPRESSED_BY.get(f.rule_id, ()))
    ]


def _run_cross_rules(
    assets: list[dict[str, Any]], engine: str, thresholds: dict[str, Any] | None = None
) -> list[Finding]:
    """Run every cross-asset detector against the full batch.

    Cross rules that declare a ``thresholds`` parameter (LX005, LT015) get the
    resolved profile threshold set so the mobile profile reaches them; the rest
    read their module-level defaults, exactly like the per-asset dispatcher.
    """
    findings: list[Finding] = []
    for cross_fn in CROSS_RULES:
        if thresholds is not None and cross_fn in _THRESHOLD_AWARE:
            findings.extend(cross_fn(assets, engine, thresholds=thresholds))
        else:
            findings.extend(cross_fn(assets, engine))
    return findings


def _compute_summary(findings: list[Finding], assets_audited: int) -> AuditSummary:
    """Aggregate per-finding numbers into a top-level summary."""
    total_vram_saved: float = sum(f.estimated_saving.vram_mb for f in findings)
    total_instructions_saved: int = sum(
        f.estimated_saving.shader_instructions for f in findings
    )
    auto_fixable_count: int = sum(1 for f in findings if f.auto_fixable)

    return AuditSummary(
        assets_audited=assets_audited,
        issues_found=len(findings),
        auto_fixable=auto_fixable_count,
        estimated_vram_saved_mb=round(total_vram_saved, 2),
        estimated_shader_instructions_saved=total_instructions_saved,
    )


# ── Public API ────────────────────────────────────────────────────────────────


def audit_assets(
    assets: list[dict[str, Any]],
    *,
    engine: str = "unreal",
    allowed_rules: frozenset[str] | None = None,
    profile: str = "default",
    overrides: dict[str, Any] | None = None,
) -> AuditResponse:
    """Run all LOD rules on a list of raw asset dicts.

    Args:
        assets:        Asset metadata dicts as received from the plugin.
        engine:        Normalised engine ("unreal" | "unity") used to tailor
                       fix guidance and stamp findings for the agent registry.
        allowed_rules: Frozenset of rule IDs the client's tier may see.
                       ``None`` means all rules are visible (Studio tier).
        profile:       Threshold profile name ("default" | "mobile" | …). Selects
                       which YAML the threshold-aware rules read.
        overrides:     Optional per-request threshold overrides (friendly field
                       names → values; see _OVERRIDE_TO_THRESHOLD). Layered on
                       top of the profile; ``None``/absent values are ignored.

    Returns:
        AuditResponse with a summary and the full list of findings, each
        enriched with rule_name / rule_explanation / engine.
    """
    from lod_auditor.rule_metadata import enrich_lod_finding

    thresholds = _build_thresholds(profile, overrides)
    all_findings: list[Finding] = []

    # Per-asset rules
    for asset in assets:
        findings = _dispatch_asset(asset, engine, thresholds)
        all_findings.extend(findings)

    # Cross-asset rules see the full batch in one pass
    all_findings.extend(_run_cross_rules(assets, engine, thresholds))

    # Apply tier filter once at the end
    if allowed_rules is not None:
        all_findings = [f for f in all_findings if f.rule_id in allowed_rules]

    # Enrich every finding with rule_name / rule_explanation / engine.
    for finding in all_findings:
        enrich_lod_finding(finding, engine)

    summary = _compute_summary(all_findings, len(assets))
    return AuditResponse(summary=summary, results=all_findings)
