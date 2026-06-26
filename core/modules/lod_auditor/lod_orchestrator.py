# core/modules/lod_auditor/lod_orchestrator.py
#
# Entry point for the LOD Auditor core engine.
#
# audit_assets() receives the raw asset list from the plugin, dispatches
# each asset to the correct rule set based on asset_type, applies the
# tier filter, runs cross-asset detectors over the full batch, and
# returns a fully assembled AuditResponse.

from typing import Any

from lod_auditor.rules.lod_animations import check_la001, check_la002, check_la003
from lod_auditor.rules.lod_audio import check_lu001, check_lu002
from lod_auditor.rules.lod_cross import (
    check_lx001_dead_textures,
    check_lx002_dead_materials,
    check_lx003_duplicate_meshes,
)
from lod_auditor.rules.lod_lighting import check_ll001, check_ll002
from lod_auditor.rules.lod_materials import check_lm001, check_lm002, check_lm003
from lod_auditor.rules.lod_meshes import check_ld001, check_ld002, check_ld003
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
)
from lod_auditor.schema import AuditResponse, AuditSummary, Finding

# ── Rule registries ───────────────────────────────────────────────────────────
#
# Ordered lists so findings always appear in the same sequence regardless
# of dict iteration order.  Add new rules by appending here.

TEXTURE_RULES = [
    check_lt001,
    check_lt002,
    check_lt003,
    check_lt004,
    check_lt005,
    check_lt006,
    check_lt007,
    check_lt008,
]
MATERIAL_RULES = [check_lm001, check_lm002, check_lm003]
MESH_RULES = [check_ld001, check_ld002, check_ld003]
ANIM_RULES = [check_la001, check_la002, check_la003]
PARTICLE_RULES = [check_lv001, check_lv002, check_lv003]
AUDIO_RULES = [check_lu001, check_lu002]
LIGHTING_RULES = [check_ll001, check_ll002]

# Mobile rules dispatch by asset_type internally but are gated by the
# feature_level flag the asset carries — they're added to whichever
# category list matches their target asset type.
MOBILE_RULES_BY_TYPE = {
    "Material": [
        check_lmb001_sampler_count,
        check_lmb003_forbidden_nodes,
    ],
    "Texture": [check_lmb002_compression],
}

# Cross-asset rules see the entire batch at once — distinct list.
CROSS_RULES = [
    check_lx001_dead_textures,
    check_lx002_dead_materials,
    check_lx003_duplicate_meshes,
]

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


def _dispatch_asset(asset: dict[str, Any], engine: str) -> list[Finding]:
    """Run all rules applicable to *asset* and return their findings.

    *engine* ("unreal" | "unity") is threaded to each rule so it can emit
    engine-appropriate guidance via lod_auditor.guidance.guidance_for.
    """
    asset_type: str = asset.get("asset_type", "")

    rules: list = []
    if asset_type in _TEXTURE_ASSET_TYPES:
        rules.extend(TEXTURE_RULES)
        rules.extend(MOBILE_RULES_BY_TYPE.get("Texture", []))
    if asset_type in _MATERIAL_ASSET_TYPES:
        rules.extend(MATERIAL_RULES)
        rules.extend(MOBILE_RULES_BY_TYPE.get("Material", []))
    if asset_type in _MESH_ASSET_TYPES:
        rules.extend(MESH_RULES)
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
        result = check_fn(asset, engine)
        if result is not None:
            findings.append(result)

    return findings


def _run_cross_rules(assets: list[dict[str, Any]], engine: str) -> list[Finding]:
    """Run every cross-asset detector against the full batch."""
    findings: list[Finding] = []
    for cross_fn in CROSS_RULES:
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
) -> AuditResponse:
    """Run all LOD rules on a list of raw asset dicts.

    Args:
        assets:        Asset metadata dicts as received from the plugin.
        engine:        Normalised engine ("unreal" | "unity") used to tailor
                       fix guidance and stamp findings for the agent registry.
        allowed_rules: Frozenset of rule IDs the client's tier may see.
                       ``None`` means all rules are visible (Studio tier).

    Returns:
        AuditResponse with a summary and the full list of findings, each
        enriched with rule_name / rule_explanation / engine.
    """
    from lod_auditor.rule_metadata import enrich_lod_finding

    all_findings: list[Finding] = []

    # Per-asset rules
    for asset in assets:
        findings = _dispatch_asset(asset, engine)
        all_findings.extend(findings)

    # Cross-asset rules see the full batch in one pass
    all_findings.extend(_run_cross_rules(assets, engine))

    # Apply tier filter once at the end
    if allowed_rules is not None:
        all_findings = [f for f in all_findings if f.rule_id in allowed_rules]

    # Enrich every finding with rule_name / rule_explanation / engine.
    for finding in all_findings:
        enrich_lod_finding(finding, engine)

    summary = _compute_summary(all_findings, len(assets))
    return AuditResponse(summary=summary, results=all_findings)
