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
    check_lx007_mixed_pipeline,
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
    check_lm015,
    check_lm016,
    check_lm017,
    check_lm018,
    check_lm019,
    check_lm020,
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
from lod_auditor.recommended_filter import filter_recommended
from lod_auditor.schema import (
    VRAM_SAVING_TOKEN,
    AuditResponse,
    AuditSummary,
    Finding,
)
from lod_auditor.vram_model import (
    BYTES_PER_PIXEL,
    effective_texture_size,
    estimate_texture_vram_mb,
    is_analyzable_texture_format,
    normalize_compression,
    resolve_texture_bpp,
    texture_asset_vram_mb,
)

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
    # Unity-native levers — each abstains on any other engine.
    check_lm015,
    check_lm016,
    check_lm017,
    check_lm018,
    check_lm019,
    check_lm020,
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
    _geo.check_lg016,
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
    _uv.check_lw011,
]
NORMAL_RULES: list[RuleFn] = [
    _nrm.check_ln001,
    _nrm.check_ln002,
    _nrm.check_ln003,
    _nrm.check_ln004,
    _nrm.check_ln005,
    _nrm.check_ln006,
    _nrm.check_ln007,
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
    _shd.check_ls013,
    _shd.check_ls014,
    _shd.check_ls015,
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
    check_lx007_mixed_pipeline,
    check_lt015_streaming_pool,
]

# Findings for these rules are dropped when any of their suppressors fired on
# the same asset — one finding per root cause (§18.1 LM008).
_SUPPRESSED_BY: dict[str, list[str]] = {"LM008": ["LM001"]}

# Rules whose fix removes the asset outright rather than optimising it. Their
# saving is the asset's full cost, so _clamp_savings must not reconcile them
# against the resize/recompress model (which would cap a deletion at whatever
# a resize would have saved).
_REMOVAL_RULES: frozenset[str] = frozenset({"LX001", "LX005"})

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
        # Skip textures we cannot price honestly: palette-indexed payloads
        # (whose cost is the palette + index table, not width*height*bpp) and
        # unmapped formats the client sent no measurement for. Both would
        # otherwise be priced through the RGBA8 fallback — inventing a
        # baseline, and from it inventing savings, "uncompressed" verdicts and
        # resize recommendations for a texture nobody can characterise. No
        # issues, no fixes, no savings: they are left out of the audit.
        if not is_analyzable_texture_format(
            asset.get("compression", "") or "", asset.get("size_kb")
        ):
            return []
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


def _analyzable_assets(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop textures the audit cannot price (indexed / unmapped-unmeasured).

    Mirrors the guard in _dispatch_asset so cross-asset rules see the same
    world the per-asset pass did — otherwise an excluded texture would still
    surface through LX001 (dead), LX005 (duplicate) or LT015 (streaming pool).
    Non-texture assets pass through untouched.
    """
    kept: list[dict[str, Any]] = []
    for asset in assets:
        if asset.get("asset_type", "") in _TEXTURE_ASSET_TYPES and (
            not is_analyzable_texture_format(
                asset.get("compression", "") or "", asset.get("size_kb")
            )
        ):
            continue
        kept.append(asset)
    return kept


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


def _sanitize_recommended(findings: list[Finding], engine: str) -> None:
    """Reduce every finding's ``recommended`` to what *engine*'s client can apply.

    Rules build ``recommended`` for two audiences at once — applicable
    properties and analysis values (vram_mb, confidence, advisory strings).
    Only the former may cross the wire; see recommended_filter for why the
    whitelist is per-engine and why it lives at the boundary rather than at
    each rule.

    A finding whose recommendation filters down to nothing cannot be applied
    by definition, so ``auto_fixable`` is corrected to False. Leaving it True
    would have the client offer a "Fix" button that resolves to a no-op.
    """
    for finding in findings:
        finding.recommended = filter_recommended(
            finding.category, engine, finding.recommended
        )
        if not finding.recommended:
            finding.auto_fixable = False


def _clamp_savings(
    findings: list[Finding],
    assets: list[dict[str, Any]],
    raw_recommended: list[dict[str, Any]] | None = None,
) -> None:
    """Make per-asset savings physically coherent.

    *raw_recommended* is the findings' recommendations as the rules built
    them, parallel to *findings*, captured before _sanitize_recommended
    narrowed them to the client's applicable keys. The joint model is
    physics, not UI: it must reason about every change a rule proposes,
    including the ones no client can apply directly (LT006's POT resize).
    Reading the filtered dict instead made those findings look like
    no-op fixes, so the achievable total came out 0 and every one of their
    savings was scaled away.

    Three invariants, all previously violable:

    1. No saving is negative. A rule whose "after" estimate lands above its
       "before" (a resize that squares a long strip, an unmapped format priced
       differently at two sizes) would otherwise subtract from the totals.

    2. The savings claimed against one asset never exceed what that asset
       actually occupies — the direct cause of the negative "potential
       memory" figure in the panel, which renders as `current - claimed`.

    3. Overlapping optimisations are reconciled against their *joint* result,
       not summed. Rules price independently and each measures against the
       same baseline, so a 4K uncompressed texture collected a full "resize"
       saving AND a full "compress" saving — 128 MB claimed against an 85 MB
       texture. Capping at 85 MB satisfies (2) but still implies the texture
       ends up free. What actually happens is 2048 + BC7 = 5.33 MB resident,
       so the honest figure is 80 MB. This recomputes the texture's cost with
       every recommendation applied at once and distributes that real total
       across the contributing findings in proportion to their individual
       claims — preserving their relative weight (and the top-offenders
       ranking) while making both the parts and the sum true.

    Only texture VRAM has a well-defined joint model here — mesh and material
    savings are priced against buffers/instructions this function has no
    baseline for, so they are left alone beyond the non-negative rule.
    """
    for finding in findings:
        if finding.estimated_saving.vram_mb < 0:
            finding.estimated_saving.vram_mb = 0.0
        if finding.estimated_saving.build_size_mb < 0:
            finding.estimated_saving.build_size_mb = 0.0
        if finding.estimated_saving.shader_instructions < 0:
            finding.estimated_saving.shader_instructions = 0

    by_path: dict[str, dict[str, Any]] = {
        str(a.get("asset_path", "")): a for a in assets if a.get("asset_path")
    }

    proposals: list[dict[str, Any]] = (
        raw_recommended
        if raw_recommended is not None and len(raw_recommended) == len(findings)
        else [f.recommended for f in findings]
    )

    # Group every texture finding per asset — including the ones claiming no
    # VRAM (LT002/LT009 turning mips ON, which *adds* 33%). The joint state
    # must reflect everything we are telling the studio to do, or the reported
    # saving contradicts our own advice. Each entry carries the rule's own
    # proposal alongside the finding, since the finding's own dict has already
    # been narrowed to what the client can apply.
    per_asset: dict[str, list[tuple[Finding, dict[str, Any]]]] = {}
    for finding, proposal in zip(findings, proposals):
        if finding.category != "Texture":
            continue
        per_asset.setdefault(finding.asset_path, []).append((finding, proposal))

    for path, group in per_asset.items():
        claimants = [f for f, _ in group if f.estimated_saving.vram_mb > 0]
        if not claimants:
            continue
        asset = by_path.get(path)
        if asset is None:
            continue
        current = texture_asset_vram_mb(asset)
        if current <= 0:
            continue  # unpriceable asset — no honest baseline to reconcile against

        # Removing the asset and optimising it are alternative strategies, not
        # additive ones: deleting a dead 4K texture frees all of it, and the
        # "resize it" saving is then moot (and vice versa). Deletion dominates,
        # so it claims the asset's full cost and the optimisation findings on
        # the same asset drop to zero rather than being summed alongside it —
        # summing them was claiming 277 MB against an 85 MB texture.
        removals = [f for f in claimants if f.rule_id in _REMOVAL_RULES]
        if removals:
            share = round(current / len(removals), 2)
            for finding in removals:
                finding.estimated_saving.vram_mb = share
            for finding in claimants:
                if finding not in removals:
                    finding.estimated_saving.vram_mb = 0.0
            continue

        achievable = round(
            max(0.0, current - _post_fix_texture_vram(asset, group)), 2
        )
        claimed = sum(f.estimated_saving.vram_mb for f in claimants)
        if claimed <= achievable or claimed <= 0:
            continue

        scale = achievable / claimed
        for finding in claimants:
            finding.estimated_saving.vram_mb = round(
                finding.estimated_saving.vram_mb * scale, 2
            )
        # Rounding each share to 2dp leaves the parts off the total by a few
        # hundredths; settle the remainder on the largest share so the
        # per-finding figures still add up to the asset's real achievable
        # saving (the panel sums them and would otherwise drift past it).
        drift = round(
            achievable - sum(f.estimated_saving.vram_mb for f in claimants), 2
        )
        if drift:
            biggest = max(claimants, key=lambda f: f.estimated_saving.vram_mb)
            biggest.estimated_saving.vram_mb = max(
                0.0, round(biggest.estimated_saving.vram_mb + drift, 2)
            )


def _post_fix_texture_vram(
    asset: dict[str, Any], group: list[tuple[Finding, dict[str, Any]]]
) -> float:
    """Resident VRAM of *asset* with every recommendation in *group* applied.

    *group* pairs each finding with the recommendation its rule authored, not
    the filtered one the client receives — the physics of "what would this
    texture cost afterwards" does not care which properties a plugin happens
    to expose a button for.

    Four recommended fields move VRAM: max_texture_size, an explicit
    width/height resize (LT006's power-of-two target), compression and
    mips_enabled. Where several findings touch the same field the most
    aggressive value wins: this figure is the *potential* saving, i.e. the
    best case if the studio applies everything on offer.
    """
    width, height = effective_texture_size(
        asset.get("width", 0), asset.get("height", 0), asset.get("max_texture_size", 0)
    )
    fmt = asset.get("compression", "RGBA8") or "RGBA8"
    mips = bool(asset.get("mips_enabled", True))
    measured_kb = asset.get("size_kb")

    # Bytes-per-pixel of the payload as it is today, anchored at today's
    # dimensions. When it comes from the client's measurement (Unity reports
    # "Automatic" for any platform without an explicit override, so this is the
    # common path there), re-deriving it after a proposed downsize would spread
    # the same measured bytes over fewer pixels and price the resize as free —
    # which zeroed every size-based saving in the Unity pipeline.
    current_bpp = resolve_texture_bpp(fmt, width, height, mips, measured_kb)

    sizes = [
        int(rec["max_texture_size"])
        for _, rec in group
        if isinstance(rec.get("max_texture_size"), int) and rec["max_texture_size"] > 0
    ]
    if sizes:
        width, height = effective_texture_size(width, height, min(sizes))

    # An explicit target resolution (LT006 resizing to power-of-two) is not a
    # long-edge cap — it can change each axis independently — so it is applied
    # as a pair, keeping whichever proposal ends up smallest in area.
    resizes = [
        (int(rec["width"]), int(rec["height"]))
        for _, rec in group
        if isinstance(rec.get("width"), int)
        and isinstance(rec.get("height"), int)
        and rec["width"] > 0
        and rec["height"] > 0
    ]
    if resizes:
        target = min(resizes, key=lambda wh: wh[0] * wh[1])
        if target[0] * target[1] < width * height:
            width, height = target

    # Pick whichever recommended format is cheapest per pixel — rules can
    # disagree (LT001 wants the usage-correct format, LT007 any compression)
    # and the cheapest is the best case this "potential" figure represents.
    # A *proposed* format is a hypothesis, so it is priced from the model; the
    # measurement describes the format the texture has today and says nothing
    # about what another one would cost.
    for _, rec in group:
        proposed = rec.get("compression")
        if not isinstance(proposed, str) or not proposed:
            continue
        modelled = BYTES_PER_PIXEL.get(normalize_compression(proposed))
        if modelled is not None and modelled < current_bpp:
            current_bpp = modelled

    for _, rec in group:
        if isinstance(rec.get("mips_enabled"), bool):
            mips = rec["mips_enabled"]

    return estimate_texture_vram_mb(
        width, height, fmt, with_mips=mips, bpp_override=current_bpp
    )


def _render_saving_tokens(findings: list[Finding]) -> None:
    """Substitute VRAM_SAVING_TOKEN with each finding's final saving.

    Runs after _clamp_savings, so the figure quoted in the message is the same
    one the panel renders in its savings column. A rule cannot format this
    itself: at rule time it only knows what its own fix would save in
    isolation, which is not what the studio gets once the fix overlaps with
    the other findings on the same asset.
    """
    for finding in findings:
        if VRAM_SAVING_TOKEN in finding.message:
            finding.message = finding.message.replace(
                VRAM_SAVING_TOKEN, f"{finding.estimated_saving.vram_mb:g}"
            )


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

    # Cross-asset rules see the full batch in one pass — minus the textures
    # the per-asset pass already excluded as unpriceable, so an indexed
    # texture can't reappear through a duplicate/dead/streaming-pool finding.
    all_findings.extend(
        _run_cross_rules(_analyzable_assets(assets), engine, thresholds)
    )

    # Apply tier filter once at the end
    if allowed_rules is not None:
        all_findings = [f for f in all_findings if f.rule_id in allowed_rules]

    # Output boundary, in order: restrict recommendations to what this
    # engine's client can apply, then make the savings physically coherent.
    # Both run before the summary so the aggregate reflects what shipped.
    # The savings model keeps working from the rules' own proposals — what a
    # client can *apply* and what physically changes the texture are different
    # questions, and answering the second with the first zeroed out every
    # saving whose fix is not a plugin-side property (LT006's POT resize).
    proposals = [dict(f.recommended) for f in all_findings]
    _sanitize_recommended(all_findings, engine)
    _clamp_savings(all_findings, assets, proposals)
    _render_saving_tokens(all_findings)

    # Enrich every finding with rule_name / rule_explanation / engine.
    for finding in all_findings:
        enrich_lod_finding(finding, engine)

    summary = _compute_summary(all_findings, len(assets))
    return AuditResponse(summary=summary, results=all_findings)
