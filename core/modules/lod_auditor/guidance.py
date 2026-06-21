# core/modules/lod_auditor/guidance.py
#
# Engine-aware fix guidance for LOD findings.
#
# Each rule used to inline a single hardcoded `guidance=(...)` string written
# in Unreal terms (Simplygon, "Create Material Instance", "re-cook",
# LightComplexity view-mode, ...). A Unity developer auditing their project got
# wrong-editor instructions. This module centralises every guidance string in
# one table keyed by rule_id and engine, so:
#
#   - rules call `guidance_for(rule_id, engine, **fmt)` instead of inlining text;
#   - adding a new engine is a data edit here, not a code change in ~25 rules;
#   - the wording stays out of the rule bodies (which keep only the detection).
#
# Resolution order per rule_id: exact engine ("unreal" | "unity") -> "_default".
# A missing entry returns None (guidance is optional on Finding).

from __future__ import annotations

# Engine keys are the *normalised* engine names the orchestrator threads down,
# i.e. "unreal" / "unity" (lowercase). The route maps "UE5"/"Unity"/etc. to
# these before calling audit_assets.
_DEFAULT = "_default"

# rule_id -> { engine | "_default": template_string }
# Templates may contain {placeholders} filled via guidance_for(..., **fmt).
LOD_GUIDANCE: dict[str, dict[str, str]] = {
    # ── Meshes ────────────────────────────────────────────────────────────
    "LD003": {
        "unreal": (
            "Target <= {budget:,} triangles using the engine's mesh reduction "
            "tools (UE5 Simplygon / built-in auto-LOD). Review whether the mesh "
            "silhouette can be simplified without losing the intended visual "
            "fidelity at the closest view distance."
        ),
        "unity": (
            "Target <= {budget:,} triangles. Add a LOD Group and generate "
            "reduced LODs with Unity's Mesh Simplification (or a DCC-baked LOD "
            "chain re-imported via the Model importer). Review whether the mesh "
            "silhouette can be simplified without losing fidelity at the closest "
            "view distance."
        ),
        _DEFAULT: (
            "Target <= {budget:,} triangles using your engine's mesh reduction "
            "tools. Review whether the mesh silhouette can be simplified without "
            "losing the intended visual fidelity at the closest view distance."
        ),
    },
    # ── Animations ────────────────────────────────────────────────────────
    "LA003": {
        "unreal": (
            "Re-import with a reduced sample rate, or use UE5's "
            "'Bake Animation Curve' to remove redundant curves that drive "
            "constants."
        ),
        "unity": (
            "Re-import with a reduced sample rate (Animation tab of the Model "
            "importer), and enable Optimal/Keyframe Reduction to drop redundant "
            "curves that drive constants."
        ),
        _DEFAULT: (
            "Re-import with a reduced sample rate, and remove redundant curves "
            "that drive constant values."
        ),
    },
    # ── Lighting ──────────────────────────────────────────────────────────
    "LL002": {
        "unreal": (
            "In UE5, inspect the LightComplexity view-mode. Shrink the "
            "AttenuationRadius (PointLight/SpotLight) so the falloff sphere "
            "doesn't overlap neighbors."
        ),
        "unity": (
            "Use the Scene view Overdraw draw mode and the Light Explorer "
            "(Window > Rendering > Light Explorer). Shrink each light's Range so "
            "its falloff sphere doesn't overlap neighbours."
        ),
        _DEFAULT: (
            "Reduce each light's attenuation radius / range so the falloff "
            "volume doesn't overlap neighbouring lights, and profile light "
            "overdraw."
        ),
    },
    # ── Materials ─────────────────────────────────────────────────────────
    "LM001": {
        "unreal": (
            "Move constant calculations to material parameters, remove redundant "
            "nodes, or merge texture samples. Use the Material Stats panel to "
            "identify expensive nodes."
        ),
        "unity": (
            "Move constant calculations to material properties, remove redundant "
            "nodes, or merge texture samples. Use the Shader Graph node preview / "
            "the Frame Debugger to identify expensive nodes."
        ),
        _DEFAULT: (
            "Move constant calculations to material parameters, remove redundant "
            "nodes, or merge texture samples to cut shader instruction count."
        ),
    },
    "LM003": {
        "unreal": (
            "Right-click the material -> Create Material Instance. Assign the "
            "instance to each primitive that references this material."
        ),
        "unity": (
            "Create a Material Variant (or share one Material and override "
            "per-renderer values with a MaterialPropertyBlock) instead of "
            "duplicating the material across primitives."
        ),
        _DEFAULT: (
            "Share a single base material and parameterise per-instance overrides "
            "instead of assigning a unique material to each primitive."
        ),
    },
    # ── Mobile ────────────────────────────────────────────────────────────
    "LMB001": {
        "unreal": (
            "Merge texture samples (e.g. pack Roughness/Metallic/AO into one "
            "RGB), or move some samples to a Material Parameter Collection."
        ),
        "unity": (
            "Merge texture samples (e.g. pack Roughness/Metallic/AO into one RGB "
            "mask texture), or move shared values into MaterialPropertyBlocks."
        ),
        _DEFAULT: (
            "Merge texture samples (e.g. pack Roughness/Metallic/AO into one RGB "
            "channel-mask) to stay within the mobile sampler budget."
        ),
    },
    "LMB002": {
        "unreal": (
            "Enable ASTC support in project settings and re-cook. ASTC_6x6 is "
            "the sweet spot for color textures on iOS A13+ and Adreno 6xx; older "
            "devices fall back to ETC2."
        ),
        "unity": (
            "Set the Android/iOS texture override to ASTC and re-import. ASTC "
            "6x6 is the sweet spot for colour textures on iOS A13+ and Adreno "
            "6xx; older devices fall back to ETC2."
        ),
        _DEFAULT: (
            "Use ASTC compression for mobile colour textures (ASTC_6x6 is a good "
            "default); fall back to ETC2 on older devices."
        ),
    },
    "LMB003": {
        "unreal": (
            "Replace SceneTexture/SceneColor with a baked equivalent or use a "
            "custom RT, or switch the material to Opaque with dithered alpha."
        ),
        "unity": (
            "Avoid screen-space reads (camera opaque/depth texture) on mobile: "
            "bake the effect, use a custom RenderTexture, or switch the material "
            "to Opaque with dithered alpha."
        ),
        _DEFAULT: (
            "Avoid screen-space texture reads on mobile: bake the effect, use a "
            "custom render target, or switch the material to Opaque with dithered "
            "alpha."
        ),
    },
}


def guidance_for(rule_id: str, engine: str, **fmt: object) -> str | None:
    """Return the fix-guidance string for *rule_id* tailored to *engine*.

    Resolution: exact engine match -> "_default" -> None. The chosen template
    is formatted with **fmt (e.g. budget=12000). Returns None when no entry
    exists for the rule, so callers can pass the result straight to
    ``Finding(guidance=...)``.
    """
    by_engine = LOD_GUIDANCE.get(rule_id)
    if not by_engine:
        return None
    template = by_engine.get(engine) or by_engine.get(_DEFAULT)
    if template is None:
        return None
    try:
        return template.format(**fmt) if fmt else template
    except (KeyError, IndexError):
        # A formatting placeholder wasn't supplied — return the raw template
        # rather than raising, so a guidance bug never breaks an audit.
        return template
