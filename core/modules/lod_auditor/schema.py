# core/modules/lod_auditor/schema.py
#
# Contract v1 — LOD Auditor input/output Pydantic models.
#
# INPUT:  AuditRequest  → list of raw asset dicts (TextureAsset |
#                         MaterialAsset | MeshAsset discriminated
#                         by asset_type at the orchestrator level)
# OUTPUT: AuditResponse → AuditSummary + list[Finding]
#
# Plugins send asset_type values from their editor API; the orchestrator
# dispatches each dict to the correct rule set without re-validating
# the whole union here — keeps the route layer thin and avoids strict
# discriminated-union breakage when a new asset_type is added.

from typing import Any

from pydantic import BaseModel, Field

# Contract version. v1 = Part-1 fields (LD001-003, LT/LM/LX shipped rules).
# v2 = Part-2 additions below (geometry / UV / normals / shader stats). Every
# v2 field is optional with a safe default, so a v1 payload validates unchanged
# and Part-2 rules simply abstain when their fields are absent.
SCHEMA_VERSION = 2

# ── Input sub-models ──────────────────────────────────────────────────────────


class TextureSample(BaseModel):
    """One texture reference inside a material's sample list."""

    texture: str = ""
    shared_sampler: bool = False


class LodLevel(BaseModel):
    """Metadata for a single LOD level inside a mesh asset."""

    index: int = 0
    triangles: int = 0
    vertices: int = 0
    screen_size: float = 1.0
    # v2 — per-LOD draw composition (LD008 material consistency, LD009 UV
    # consistency). material_slots_used lists the slot indices this LOD draws.
    material_slots_used: list[int] = Field(default_factory=list)
    uv_channel_count: int = 0
    section_count: int = 1


# ── v2 mesh sub-models (all optional; rules abstain when absent) ───────────────


class UvChannelStats(BaseModel):
    """Per-UV-channel measurements (LW rules). index 0 = channel 0."""

    channel: int = 0
    overlap_ratio: float = 0.0  # 0-1 overlapped UV area
    max_stretch: float = 1.0  # >=1, worst-face UV/3D ratio skew
    avg_stretch: float = 1.0
    island_count: int = 0
    packing_efficiency: float = 1.0  # 0-1 shell area / 0-1 area
    outside_unit_ratio: float = 0.0  # 0-1 UV area outside [0,1]
    texel_density_avg: float = 0.0  # texels/cm at referenced tex size
    texel_density_cv: float = 0.0  # coefficient of variation


class NormalStats(BaseModel):
    """Normal / tangent measurements (LN rules)."""

    has_normals: bool = True
    zero_normal_count: int = 0
    nan_normal_count: int = 0
    has_tangents: bool = True
    mirrored_tangent_ratio: float = 0.0
    hard_edge_ratio: float = 0.0  # hard edges / total edges
    smoothing_group_count: int = 0
    recompute_normals: bool = False  # build setting
    recompute_tangents: bool = False
    tangent_space: str = ""  # "" | "legacy" — LN003 MikkTSpace mismatch marker


class CollisionStats(BaseModel):
    """Simple/complex collision measurements (LD011)."""

    has_simple_collision: bool = False
    primitive_count: int = 0
    complex_as_simple: bool = False
    complex_triangles: int = 0


# ── Input asset models (for documentation / plugin contract) ──────────────────
#
# These are NOT used for strict validation inside the route — the route
# receives list[dict] and the rules access fields via dict.get() with
# safe defaults.  They serve as the authoritative field-level contract
# that Raúl (UE5) and the Unity dev validate field by field.


class TextureAsset(BaseModel):
    """Fields the plugin must provide for every Texture2D asset."""

    asset_path: str
    asset_type: str = "Texture2D"
    # usage is inferred by the plugin (material pin / name suffix / compression)
    usage: str = "BaseColor"  # BaseColor | Normal | Mask | HDR | UI | Data
    width: int = 0
    height: int = 0
    # canonical BC* or UE5 TC_* — vram_model.normalize_compression handles both
    compression: str = "BC7"
    srgb: bool = True
    mips_enabled: bool = True
    mip_count: int = 0
    streaming: bool = True
    lod_group: str = "World"
    max_texture_size: int = 0
    referenced_by_materials: int = 1


class ShaderStats(BaseModel):
    """Engine-agnostic shader measurements (LS rules), filled by the client.

    Both UE5 (FMaterialResource stats) and Unity (ShaderUtil / Frame Debugger)
    fill the same shape; rules read only these fields so detection is neutral.
    """

    instruction_count: int = 0
    texture_fetch_count: int = 0
    branch_count: int = 0
    dynamic_branch_count: int = 0
    loop_count: int = 0
    max_loop_iterations: int = 0
    estimated_register_pressure: int = 0
    variant_count: int = 0
    half_precision_ratio: float = 0.0  # 0-1 of float ops in half precision
    dead_parameter_count: int = 0
    dead_code_ratio: float = 0.0  # engine-reported stripped-instruction delta
    expensive_op_counts: dict[str, int] = Field(default_factory=dict)
    dependent_texture_reads: int = 0


class MaterialAsset(BaseModel):
    """Fields the plugin must provide for every Material asset."""

    asset_path: str
    asset_type: str = "Material"
    is_material_instance: bool = False
    parent_material: str | None = None
    instruction_count: int = 0
    sampler_count: int = 0
    texture_samples: list[TextureSample] = Field(default_factory=list)
    used_by_primitives: int = 1
    blend_mode: str = "Opaque"  # Opaque | Masked | Translucent | Additive | Modulate
    # ── v2 additions (LM004-LM014, LR001-LR008) ──────────────────────────────
    base_pass_instructions: int = 0  # split of instruction_count
    vertex_shader_instructions: int = 0
    graph_node_count: int = 0
    graph_depth: int = 0
    function_call_depth: int = 0  # nested MaterialFunction / Sub Graph depth
    layer_count: int = 0
    static_switch_count: int = 0
    static_permutation_estimate: int = 0
    dynamic_parameter_count: int = 0
    uses_rvt: bool = False
    uses_wpo: bool = False
    uses_pdo: bool = False
    uses_scene_color: bool = False
    uses_depth_read: bool = False
    two_sided: bool = False
    is_decal: bool = False
    shading_model: str = "DefaultLit"
    usage_flags_unused: list[str] = Field(default_factory=list)  # LM012
    expensive_node_counts: dict[str, int] = Field(default_factory=dict)
    shader_stats: ShaderStats | None = None


class MeshAsset(BaseModel):
    """Fields the plugin must provide for every StaticMesh / SkeletalMesh."""

    asset_path: str
    asset_type: str = "StaticMesh"
    lod_count: int = 1
    lods: list[LodLevel] = Field(default_factory=list)
    bounds_radius: float = 100.0
    used_in_levels: int = 1
    # ── v2 geometry (LOD0 unless stated) ──────────────────────────────────────
    triangle_count: int = 0
    vertex_count: int = 0
    degenerate_triangle_count: int = 0
    duplicate_vertex_count: int = 0  # exact position + attribute dupes
    overlapping_vertex_count: int = 0  # within weld_epsilon, unwelded
    non_manifold_edge_count: int = 0
    open_edge_count: int = 0
    internal_face_ratio: float = 0.0  # 0-1, faces never visible from hull
    material_slot_count: int = 1
    section_count: int = 1  # draw sections at LOD0
    uv_channel_count: int = 1
    lightmap_uv_index: int = -1  # -1 = none
    uses_static_lighting: bool = False
    pivot_offset_ratio: float = 0.0  # |pivot - bounds_center| / bounds_radius
    import_uniform_scale: float = 1.0
    import_scale_nonuniform: bool = False
    has_negative_scale_instances: bool = False
    # per-UV-channel metrics (index 0 = channel 0)
    uv_channels: list[UvChannelStats] = Field(default_factory=list)
    normal_stats: NormalStats | None = None
    shadow_lod_index: int = -1  # -1 = follows render LOD
    collision: CollisionStats | None = None
    nanite_enabled: bool = False
    nanite_fallback_triangle_percent: float = 100.0
    # blend modes of the materials this mesh's slots reference — client fills
    # from the mesh's material slots so LD012/LD013 stay pure per-asset (no
    # orchestrator cross-join). Empty ⇒ the Nanite candidacy/compat rules abstain.
    used_material_blend_modes: list[str] = Field(default_factory=list)
    is_kit_piece: bool = False  # name-matched modular kit piece (LG010)


class AuditRequest(BaseModel):
    """Top-level request body for POST /audit/lods."""

    api_key: str = ""
    engine: str = "UE5"  # "UE5" | "Unity"
    project_name: str = ""
    assets: list[dict[str, Any]] = Field(default_factory=list)


# ── Output models ─────────────────────────────────────────────────────────────


class Saving(BaseModel):
    """Estimated resource saving if the fix is applied."""

    vram_mb: float = 0.0
    shader_instructions: int = 0
    # Build/package-size saving in MB — distinct from runtime VRAM. Used by
    # rules that shrink the cooked payload without changing GPU residency
    # (e.g. LT008 Oodle/RDO). Kept out of the VRAM totals on purpose.
    build_size_mb: float = 0.0


class Finding(BaseModel):
    """A single rule violation with before/after data and an optional fix."""

    asset_path: str
    rule_id: str  # e.g. "LT003"
    category: str  # "Texture" | "Material" | "Mesh"
    severity: str  # "warning" | "info"
    message: str
    # before / after: the plugin renders these as a diff for the user
    current: dict[str, Any]
    recommended: dict[str, Any]
    estimated_saving: Saving
    auto_fixable: bool
    guidance: str | None = None
    # ── Enrichment (filled by rule_metadata.enrich_lod_finding) ───────────
    # rule_name: short humanised title; rule_explanation: docstring grounding
    # for the LLM + UI tooltip; engine: normalised engine ("unreal"|"unity")
    # so the agent prompt registry resolves the right template.
    rule_name: str = ""
    rule_explanation: str = ""
    engine: str = ""
    # ai_guidance: optional LLM-generated guidance, attached only when the
    # caller requests bounded enrichment (Unreal-only, top-N findings).
    ai_guidance: str | None = None


class AuditSummary(BaseModel):
    """Aggregate numbers shown in the plugin's LOD Audit panel header."""

    assets_audited: int = 0
    issues_found: int = 0
    auto_fixable: int = 0
    estimated_vram_saved_mb: float = 0.0
    estimated_shader_instructions_saved: int = 0


class AuditResponse(BaseModel):
    """Full response body for POST /audit/lods."""

    summary: AuditSummary
    results: list[Finding]
