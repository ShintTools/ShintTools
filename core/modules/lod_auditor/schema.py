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


class MeshAsset(BaseModel):
    """Fields the plugin must provide for every StaticMesh / SkeletalMesh."""

    asset_path: str
    asset_type: str = "StaticMesh"
    lod_count: int = 1
    lods: list[LodLevel] = Field(default_factory=list)
    bounds_radius: float = 100.0
    used_in_levels: int = 1


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
