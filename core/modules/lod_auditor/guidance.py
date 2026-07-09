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
    # ══ Part 2 — geometry (LG) ═══════════════════════════════════════════════
    "LG001": {
        "unreal": (
            "Reduce LOD0 to <= {budget:,} triangles with the engine's mesh "
            "reduction, or enable Nanite so density stops mattering."
        ),
        "unity": (
            "Reduce LOD0 to <= {budget:,} triangles via the Model importer's "
            "Mesh Simplification or a DCC-baked LOD0."
        ),
        _DEFAULT: "Reduce LOD0 to <= {budget:,} triangles with mesh reduction.",
    },
    "LG004": {
        "unreal": (
            "Remove zero-area triangles: re-import after a DCC cleanup, or run "
            "the Mesh Editor / a geometry-clean commandlet to weld and compact."
        ),
        "unity": (
            "Remove zero-area triangles in the DCC and re-import; Unity has no "
            "in-editor degenerate-cleanup, so fix at source."
        ),
        _DEFAULT: "Remove zero-area (degenerate) triangles in your DCC.",
    },
    "LG007": {
        "unreal": (
            "Repair non-manifold edges in your DCC (weld/rebuild the shell). "
            "They degrade Nanite simplification, distance fields and Chaos."
        ),
        "unity": (
            "Repair non-manifold edges in your DCC. They degrade Unity's "
            "baked-GI lightmapper and PhysX mesh-collider cooking."
        ),
        _DEFAULT: "Repair non-manifold edges (bowties / >2-face edges) in the DCC.",
    },
    "LG008": {
        "unreal": (
            "Close the hull in your DCC if the mesh is static-lit or Nanite — "
            "open edges leak light and hole the silhouette at distance."
        ),
        "unity": (
            "Close the hull in your DCC if the mesh contributes to baked GI — "
            "open edges leak under the Progressive Lightmapper."
        ),
        _DEFAULT: "Close the hull in your DCC on lighting/hull-critical meshes.",
    },
    "LG011": {
        "unreal": (
            "Remove the trailing unused UV channels in the Static Mesh editor "
            "(Build Settings) or re-import without them."
        ),
        "unity": (
            "Remove the extra UV sets in the DCC and re-import — Unity keeps "
            "every imported UV channel, so drop them at source."
        ),
        _DEFAULT: "Remove UV channels no material or lightmap consumes.",
    },
    "LG014": {
        "unreal": (
            "Set Import Uniform Scale back to 1.0 and bake the scale into the "
            "mesh on reimport."
        ),
        "unity": (
            "Set the Model importer's Scale Factor to 1 and re-import (bake the "
            "scale in the DCC if needed)."
        ),
        _DEFAULT: "Normalise import scale to 1.0 and bake the scale into the mesh.",
    },
    "LG015": {
        "unreal": (
            "Author a mirrored mesh variant or enable Reverse Culling instead "
            "of negative-scaling instances."
        ),
        "unity": (
            "Author a mirrored mesh variant — negative scale breaks GPU "
            "Instancing / SRP Batcher."
        ),
        _DEFAULT: "Avoid negative instance scale; author a mirrored variant.",
    },
    # ══ Part 2 — UV (LW) ═════════════════════════════════════════════════════
    "LW002": {
        "unreal": (
            "Regenerate lightmap UVs (Build Settings > Generate Lightmap UVs) "
            "so no shells overlap."
        ),
        "unity": (
            "Re-enable Generate Lightmap UVs on the Model importer (writes UV2) "
            "so no shells overlap."
        ),
        _DEFAULT: "Regenerate the lightmap UV channel so no shells overlap.",
    },
    "LW006": {
        "unreal": (
            "Re-pack the shells (or regenerate lightmap UVs) so they fill the "
            "0-1 space; then the resolution buys real texel coverage."
        ),
        "unity": (
            "Re-pack the shells in the DCC (or regenerate Lightmap UVs) to fill "
            "0-1; Unity's UV2 packing follows the importer."
        ),
        _DEFAULT: "Re-pack UV shells to fill 0-1 so the resolution isn't wasted.",
    },
    "LW007": {
        "unreal": (
            "Bring texel density toward the group target — usually by clamping "
            "the referenced texture's Max Texture Size."
        ),
        "unity": (
            "Bring texel density toward the target — clamp the texture's Max "
            "Size override for the platform."
        ),
        _DEFAULT: (
            "Adjust the referenced texture size so texel density matches the "
            "target for this asset class."
        ),
    },
    "LW010": {
        "unreal": (
            "Generate the missing UV channel (lightmap: Generate Lightmap UVs; "
            "material: add the channel in the DCC)."
        ),
        "unity": (
            "Generate the missing UV set (lightmap: Generate Lightmap UVs → "
            "UV2; material: add it in the DCC)."
        ),
        _DEFAULT: "Provide the UV channel the consumer samples.",
    },
    # ══ Part 2 — normals (LN) ════════════════════════════════════════════════
    "LN001": {
        "unreal": (
            "Enable Recompute Normals in Build Settings, or re-import with "
            "authored normals."
        ),
        "unity": (
            "Set the Model importer Normals to Calculate, or re-import with "
            "authored normals."
        ),
        _DEFAULT: "Recompute or import valid normals so shading isn't faceted.",
    },
    "LN003": {
        "unreal": (
            "Enable Recompute Tangents + Use MikkTSpace in Build Settings so "
            "normal maps read correctly."
        ),
        "unity": (
            "Set the Model importer Tangents to Calculate (MikkTSpace) so "
            "normal maps read correctly."
        ),
        _DEFAULT: "Recompute tangents with MikkTSpace for correct normal maps.",
    },
    # ══ Part 2 — LOD chain (LD) ══════════════════════════════════════════════
    "LD007": {
        "unreal": (
            "Set sensible LOD ScreenSize transitions (a halving ladder is a "
            "good default) in the Static Mesh editor."
        ),
        "unity": (
            "Set the LOD Group's per-level transition heights to a sensible "
            "ladder (a halving progression works well)."
        ),
        _DEFAULT: "Fix the LOD screen-size transitions to a well-spaced ladder.",
    },
    "LD010": {
        "unreal": (
            "Assign a dedicated (higher) shadow LOD so shadow-depth passes stop "
            "paying full LOD0 cost."
        ),
        "unity": (
            "Unity has no per-mesh shadow LOD; reduce shadow cost via Shadow "
            "Distance / cascades or a custom LOD Group callback."
        ),
        _DEFAULT: "Use a higher-index LOD for shadow rendering.",
    },
    "LD011": {
        "unreal": (
            "Add simple collision (K-DOP/convex) and turn off complex-as-simple "
            "on high-poly meshes."
        ),
        "unity": (
            "Add a primitive collider (or a Convex Mesh Collider) instead of a "
            "non-convex Mesh Collider on the render mesh."
        ),
        _DEFAULT: "Give the mesh proportionate simple collision.",
    },
    "LD012": {
        "unreal": (
            "Enable Nanite on this dense opaque static mesh and remove the "
            "hand-authored LOD chain."
        ),
        "unity": "Not applicable on Unity — there is no Nanite equivalent.",
        _DEFAULT: "Consider virtualized geometry for dense opaque static meshes.",
    },
    "LD013": {
        "unreal": (
            "Lower the Nanite fallback triangle percent, and move translucent "
            "slots to a non-Nanite section."
        ),
        "unity": "Not applicable on Unity — there is no Nanite equivalent.",
        _DEFAULT: "Reconcile the virtualized-geometry config with its consumers.",
    },
    # ══ Part 2 — material (LM) ═══════════════════════════════════════════════
    "LM004": {
        "unreal": (
            "Share wrap samplers and pack channels to fit the sampler budget "
            "(16 is the hard D3D limit)."
        ),
        "unity": (
            "Reuse a Sampler State node across Sample Texture 2D nodes and pack "
            "channels to cut sampler count."
        ),
        _DEFAULT: "Share samplers and pack channels to stay within budget.",
    },
    "LM007": {
        "unreal": (
            "Reduce material layers or bake the lower layers — each layer "
            "multiplies base-pass cost."
        ),
        "unity": (
            "Reduce HDRP Layered Lit layers (URP has no layering) — each layer "
            "multiplies base-pass cost."
        ),
        _DEFAULT: "Reduce material layers; each multiplies base-pass cost.",
    },
    "LM011": {
        "unreal": (
            "Collapse static switches into quality-level branches or split the "
            "material to cut the permutation count."
        ),
        "unity": (
            "Collapse Shader Graph Boolean Keywords or split the shader to cut "
            "compiled variant count."
        ),
        _DEFAULT: "Reduce static switches/keywords to cut the permutation count.",
    },
    "LM012": {
        "unreal": (
            "Uncheck the unused bUsedWith* usage flags — each checked flag "
            "doubles the compiled permutation set."
        ),
        "unity": (
            "No per-material usage flags on Unity; manage shader stripping via "
            "per-SRP settings instead."
        ),
        _DEFAULT: "Disable usage flags no referencing component needs.",
    },
    "LM013": {
        "unreal": (
            "Bake or gate the flagged expensive nodes (SceneColor, Noise, …) "
            "behind quality switches."
        ),
        "unity": (
            "Bake or gate the flagged Shader Graph nodes (Scene Color, Custom "
            "Function, …) behind keywords."
        ),
        _DEFAULT: "Bake or quality-gate the flagged expensive material nodes.",
    },
    "LM014": {
        "unreal": (
            "Reduce World Position Offset / vertex-shader work, or limit it to "
            "low-vertex meshes."
        ),
        "unity": (
            "Reduce the Vertex Position (WPO) work on the master stack, or "
            "limit it to low-vertex meshes."
        ),
        _DEFAULT: "Reduce vertex-shader (WPO) cost or restrict to low-vertex meshes.",
    },
    # ══ Part 2 — rendering (LR) ══════════════════════════════════════════════
    "LR001": {
        "unreal": (
            "Move the scene-color/depth read to a translucent pass, or remove "
            "it, to keep early-Z for opaque geometry."
        ),
        "unity": (
            "Move the Scene Color/Depth read to a transparent material, or "
            "remove it, to preserve early-Z."
        ),
        _DEFAULT: "Avoid scene reads in opaque materials so early-Z is preserved.",
    },
    "LR006": {
        "unreal": (
            "Clear Two Sided on solid geometry (keep it only for foliage/thin "
            "cards) to halve rasteriser work."
        ),
        "unity": (
            "Set Render Face back to Front on solid geometry (Both is only for "
            "foliage/thin cards)."
        ),
        _DEFAULT: "Disable two-sided rendering on solid geometry.",
    },
    "LR007": {
        "unreal": (
            "Limit World Position Offset to low-poly meshes and avoid it on "
            "Nanite (it disables the fast path)."
        ),
        "unity": (
            "Limit the Vertex Position (WPO) block to low-poly meshes — it runs "
            "per vertex."
        ),
        _DEFAULT: "Restrict world-position-offset to low-vertex meshes.",
    },
    # ══ Part 2 — shader (LS) ═════════════════════════════════════════════════
    "LS001": {
        "unreal": (
            "Cut instruction count: precompute constants, remove redundant "
            "nodes, use the Material Stats / Platform Stats panel."
        ),
        "unity": (
            "Cut instruction count: precompute constants, prune Shader Graph "
            "nodes, check the Frame Debugger per-pass stats."
        ),
        _DEFAULT: "Reduce shader instructions by precomputing and pruning work.",
    },
    "LS010": {
        "unreal": (
            "Delete the unbound material parameters — declared but never read."
        ),
        "unity": "Delete the unused Shader Graph properties — never read.",
        _DEFAULT: "Delete shader parameters that are declared but never read.",
    },
    # ══ Part 2 — texture (LT) ════════════════════════════════════════════════
    "LT009": {
        "unreal": (
            "Set MipGenSettings to FromTextureGroup and recompress so the "
            "texture gets a mip chain."
        ),
        "unity": "Enable Generate Mip Maps on the Texture importer and re-import.",
        _DEFAULT: "Enable mipmaps on 3D-sampled textures to stop shimmer.",
    },
    "LT010": {
        "unreal": (
            "Assign the correct Texture Group so streaming priority and the "
            "resolution budget match the usage."
        ),
        "unity": (
            "Set the correct Texture Type + per-platform override so the "
            "resolution budget matches the usage."
        ),
        _DEFAULT: "Put the texture in the group that matches its usage.",
    },
    "LT016": {
        "unreal": (
            "Set NeverStream on always-resident UI/effects textures so they "
            "stop churning the streaming pool."
        ),
        "unity": (
            "Enable Non-Streaming on always-resident UI/effects textures so "
            "they stop churning the pool."
        ),
        _DEFAULT: "Mark always-resident UI/effects textures non-streaming.",
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
