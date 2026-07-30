# core/modules/lod_auditor/recommended_filter.py
#
# Output-boundary filter for Finding.recommended.
#
# Rules build `recommended` for two different audiences at once: the fields a
# client can actually APPLY (compression, max_texture_size, …) and values that
# only exist to explain the analysis (vram_mb, confidence, width/height,
# advisory strings like "<= 2048", prose hints). Serializing both meant clients
# received keys they cannot act on, rendered them in the fix diff, and — for a
# typed client like Unity's `recommended` DTO — tried to deserialize analysis
# numbers into applicable-property slots.
#
# This module is the single place that decides what leaves the Core. Rules stay
# expressive; the contract is enforced once, here, instead of being re-derived
# at ~80 construction sites where it would inevitably drift.
#
# The whitelist is PER ENGINE because the two clients genuinely differ in what
# they can apply — the UE5 fixer registry (ShintLodFixerRegistry.cpp) handles a
# wider set than Unity's typed DTO. Filtering both down to Unity's set would
# silently disable working UE5 auto-fixes; filtering neither is the bug being
# fixed. Each engine gets exactly what it can act on.

from __future__ import annotations

from typing import Any

# ── Applicable-field whitelists ───────────────────────────────────────────────
#
# Unity — mirrors the typed DTOs in AssetOptimizer*ScannerData.cs verbatim:
#   textures : AssetOptimizerTexturesScannerOutputFileRecommendedData
#   meshes   : AssetOptimizerMeshesScannerOutputFileRecommendedData
#   materials: AssetOptimizerMaterialsScannerOutputFileRecommendedData
# A key absent there cannot be applied by the Unity client at all.
_UNITY_FIELDS: dict[str, dict[str, type]] = {
    "Texture": {
        "compression": str,
        "max_texture_size": int,
        "srgb": bool,
        "streaming": bool,
        "mips_enabled": bool,
    },
    "Mesh": {
        "import_uniform_scale": float,
    },
    "Material": {
        "blend_mode": str,
        "two_sided": bool,
    },
}

# UE5 — mirrors FShintLodFixerRegistry's recognised keys (the sets in
# CanApply + the per-key handlers in ApplyOne). Keeping this in step with the
# plugin is what makes "auto_fixable" mean the same thing on both engines.
_UNREAL_FIELDS: dict[str, dict[str, type]] = {
    "Texture": {
        "compression": str,
        "max_texture_size": int,
        "srgb": bool,
        "never_stream": bool,
        "mips_enabled": bool,
        "mip_gen": str,
        "lod_group": str,
    },
    "Mesh": {
        "import_uniform_scale": float,
        "build_scale": float,
        "recompute_normals": bool,
        "recompute_tangents": bool,
        "remove_degenerates": bool,
        "use_full_precision_uvs": bool,
        "generate_lightmap_uvs": bool,
        "nanite_enabled": bool,
        "complex_as_simple": bool,
        "has_simple_collision": bool,
        "fallback_percent": float,
        "lod_count": int,
        "screen_sizes": list,
        "lods": str,
        "triangle_ratio_band": str,
    },
    "Material": {
        "blend_mode": str,
        "two_sided": bool,
        "clear_usage_flags": list,
        "set_usage_flags": list,
    },
}

_FIELDS_BY_ENGINE: dict[str, dict[str, dict[str, type]]] = {
    "unity": _UNITY_FIELDS,
    "unreal": _UNREAL_FIELDS,
}

# Keys that mean exactly the same thing as a whitelisted field under a
# different name, per engine. Only unambiguous 1:1 equivalences belong here —
# anything needing interpretation is dropped instead of guessed at.
#   never_stream (UE5 vocabulary) == NOT streaming (Unity vocabulary)
_ALIASES: dict[str, dict[str, tuple[str, bool]]] = {
    # engine -> source_key -> (target_key, invert_bool)
    "unity": {"never_stream": ("streaming", True)},
    "unreal": {"streaming": ("never_stream", True)},
}


def _coerce(value: Any, expected: type) -> Any | None:
    """Return *value* as *expected*, or None when it isn't a real value.

    Advisory strings are the thing this exists to reject: a rule may set
    ``{"lod_count": "<= 4"}`` or ``{"max_texture_size": "align sizes"}`` to
    explain a target it can't express numerically. Those must never reach a
    client that would parse them as a property value (Unity's int field would
    take 0; UE5's Atoi would too, silently resizing a texture to nothing).
    """
    if value is None:
        return None

    if expected is bool:
        return bool(value) if isinstance(value, bool) else None

    if expected is int:
        # bool is an int subclass — reject it explicitly, it's never a size.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return int(value)

    if expected is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    if expected is str:
        if not isinstance(value, str):
            return None
        text = value.strip()
        # Comparators/prose are explanations, not applicable values.
        if not text or text[0] in "<>=≈" or " " in text:
            return None
        return text

    if expected is list:
        if not isinstance(value, (list, tuple)):
            return None
        items = [str(v) for v in value if str(v).strip()]
        return items or None

    return None


def filter_recommended(
    category: str, engine: str, recommended: dict[str, Any]
) -> dict[str, Any]:
    """Keep only the keys *engine*'s client can apply to a *category* asset.

    Unknown categories (Animation, Particle, Audio, Lighting — advisory-only
    families with no fixer) yield an empty dict: nothing there is applicable,
    and saying so lets the caller mark the finding non-auto-fixable.
    """
    if not recommended:
        return {}

    fields = _FIELDS_BY_ENGINE.get(
        (engine or "unreal").strip().lower(), _UNREAL_FIELDS
    ).get(category)
    if not fields:
        return {}

    aliases = _ALIASES.get((engine or "unreal").strip().lower(), {})
    out: dict[str, Any] = {}

    for key, value in recommended.items():
        target, invert = aliases.get(key, (key, False))
        expected = fields.get(target)
        if expected is None:
            continue
        coerced = _coerce(value, expected)
        if coerced is None:
            continue
        if invert:
            if not isinstance(coerced, bool):
                continue
            coerced = not coerced
        # An earlier explicit key wins over one arriving through an alias.
        out.setdefault(target, coerced)

    return out
