# core/modules/lod_auditor/rules/lod_mobile.py
#
# Mobile-specific feature/level rules: LMB001 – LMB003
#
# These only run when the audit request carries `feature_level: "Mobile"`.
# Mobile renderers (Vulkan / Metal on iOS / OpenGL ES on Android) have
# hard caps that desktop doesn't share — flagging assets that violate
# them prevents shader compile failures and runtime fallbacks.

from lod_auditor.config import load_profile
from lod_auditor.guidance import guidance_for
from lod_auditor.schema import Finding, Saving

THRESHOLDS = load_profile()

# OpenGL ES 3.1 guarantees 16 samplers per shader stage. Vulkan
# tile-based mobile GPUs also degrade past 8 active samplers per draw,
# so we cap below the spec for headroom.
_DEFAULT_MAX_SAMPLERS_MOBILE = 8

# Mobile-friendly compression formats (ETC2 / ASTC). UE5 packs ASTC into
# the same TC_* taxonomy; we accept canonical and TC_ names.
_MOBILE_COMPRESSION_FORMATS: frozenset[str] = frozenset(
    {"ASTC_4x4", "ASTC_6x6", "ASTC_8x8", "ETC2_RGB", "ETC2_RGBA", "BC7", "BC5"}
)

# Forward+/Mobile shading path can't render translucent objects with
# screen-space effects (refractions, SSR, planar reflections). Flag
# materials that combine Translucent with those nodes.
_FORBIDDEN_MOBILE_NODES: frozenset[str] = frozenset(
    {"SceneTexture", "SceneColor", "PlanarReflection", "ScreenPosition"}
)


def _is_mobile(asset: dict) -> bool:
    """Mobile rules only fire when the asset explicitly opts in.

    The plugin sets ``feature_level: "Mobile"`` at the asset dict level
    when the project targets mobile. Without that flag we skip silently
    so desktop scans don't drown in noise.
    """
    return asset.get("feature_level", "").lower() == "mobile"


# ── LMB001 ────────────────────────────────────────────────────────────────────


def check_lmb001_sampler_count(asset: dict, engine: str = "unreal") -> Finding | None:
    """LMB001: Mobile material exceeds the per-shader sampler cap."""
    if not _is_mobile(asset):
        return None
    if asset.get("asset_type") not in (
        "Material",
        "MaterialInstance",
        "MaterialInstanceConstant",
    ):
        return None

    sampler_count: int = asset.get("sampler_count", 0)
    budget = THRESHOLDS.get("LMB001_MAX_SAMPLERS_MOBILE", _DEFAULT_MAX_SAMPLERS_MOBILE)

    if sampler_count <= budget:
        return None

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LMB001",
        category="Mobile",
        severity="error",
        message=(
            f"Mobile material uses {sampler_count} samplers — "
            f"mobile GPUs cap at {budget} per shader stage. "
            "Will hit fallback path or fail to compile on some devices."
        ),
        current={"sampler_count": sampler_count, "feature_level": "Mobile"},
        recommended={"sampler_count": f"<= {budget}"},
        estimated_saving=Saving(vram_mb=0.0, shader_instructions=0),
        auto_fixable=False,
        guidance=guidance_for("LMB001", engine),
    )


# ── LMB002 ────────────────────────────────────────────────────────────────────


def check_lmb002_compression(asset: dict, engine: str = "unreal") -> Finding | None:
    """LMB002: Texture uses a desktop-only compression format on mobile."""
    if not _is_mobile(asset):
        return None
    if asset.get("asset_type") not in (
        "Texture2D",
        "Texture",
        "Texture2DArray",
        "TextureCube",
    ):
        return None

    compression: str = asset.get("compression", "")
    if not compression or compression in _MOBILE_COMPRESSION_FORMATS:
        return None

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LMB002",
        category="Mobile",
        severity="warning",
        message=(
            f"Texture uses '{compression}' compression — "
            "not supported by mobile GPUs. "
            "Engine will fall back to RGBA8 at runtime (4x VRAM)."
        ),
        current={"compression": compression},
        recommended={"compression": "ASTC_6x6 (color) or ETC2_RGBA"},
        estimated_saving=Saving(vram_mb=0.0, shader_instructions=0),
        auto_fixable=True,
        guidance=guidance_for("LMB002", engine),
    )


# ── LMB003 ────────────────────────────────────────────────────────────────────


def check_lmb003_forbidden_nodes(asset: dict, engine: str = "unreal") -> Finding | None:
    """LMB003: Translucent material on mobile uses screen-space nodes."""
    if not _is_mobile(asset):
        return None
    if asset.get("asset_type") not in (
        "Material",
        "MaterialInstance",
        "MaterialInstanceConstant",
    ):
        return None
    if asset.get("blend_mode", "Opaque") not in ("Translucent", "Additive"):
        return None

    used_nodes: list[str] = asset.get("material_nodes", [])
    forbidden_used = [n for n in used_nodes if n in _FORBIDDEN_MOBILE_NODES]
    if not forbidden_used:
        return None

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LMB003",
        category="Mobile",
        severity="error",
        message=(
            f"Translucent material uses screen-space node(s): "
            f"{', '.join(forbidden_used)}. "
            "Mobile forward renderer can't evaluate these — they output black."
        ),
        current={
            "blend_mode": asset.get("blend_mode"),
            "forbidden_nodes": forbidden_used,
        },
        recommended={"forbidden_nodes": "remove or switch to Opaque/Masked"},
        estimated_saving=Saving(vram_mb=0.0, shader_instructions=0),
        auto_fixable=False,
        guidance=guidance_for("LMB003", engine),
    )
