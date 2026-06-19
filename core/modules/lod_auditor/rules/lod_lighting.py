# core/modules/lod_auditor/rules/lod_lighting.py
#
# Lighting / Lightmap LOD rules: LL001 – LL002
#
# Targets primitives with baked lighting data. Lightmaps are stored on
# the StaticMeshComponent (UE5) or MeshRenderer (Unity), but for the
# auditor we accept a single ``Lightmap`` asset type so the plugin can
# report whichever level fits its workflow.

from lod_auditor.config import load_profile
from lod_auditor.guidance import guidance_for
from lod_auditor.schema import Finding, Saving

THRESHOLDS = load_profile()

_DEFAULT_RESOLUTION_PER_M2 = 32  # texels per square meter (UE5 default)
_DEFAULT_MAX_LIGHTMAP_RESOLUTION = 256
_DEFAULT_OVERDRAW_THRESHOLD = 2.0  # avg overdraw per pixel before flagging


# ── LL001 ─────────────────────────────────────────────────────────────────────


def check_ll001(asset: dict, engine: str = "unreal") -> Finding | None:
    """LL001: Lightmap resolution is excessive for the primitive's surface area."""
    if asset.get("asset_type") != "Lightmap":
        return None

    resolution: int = asset.get("resolution", 0)
    surface_area_m2: float = float(asset.get("surface_area_m2", 0.0))
    if resolution == 0 or surface_area_m2 <= 0.0:
        return None

    texels_per_m2_target = THRESHOLDS.get(
        "LL001_RESOLUTION_PER_M2", _DEFAULT_RESOLUTION_PER_M2
    )
    max_resolution = THRESHOLDS.get(
        "LL001_MAX_LIGHTMAP_RESOLUTION", _DEFAULT_MAX_LIGHTMAP_RESOLUTION
    )

    # Texel density = (resolution^2) / surface_area_m2
    actual_texels_per_m2: float = (resolution * resolution) / surface_area_m2

    if (
        actual_texels_per_m2 <= texels_per_m2_target * 4
        and resolution <= max_resolution
    ):
        return None

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LL001",
        category="Lighting",
        severity="warning",
        message=(
            f"Lightmap is {resolution}x{resolution} for {surface_area_m2:.1f} m² "
            f"surface — {actual_texels_per_m2:.0f} texels/m² "
            f"(target: {texels_per_m2_target}). "
            "Excess texels increase build time and runtime VRAM with no visual gain."
        ),
        current={"resolution": resolution, "texels_per_m2": actual_texels_per_m2},
        recommended={
            "resolution": min(max_resolution, resolution // 2),
            "texels_per_m2": f"~{texels_per_m2_target}",
        },
        estimated_saving=Saving(vram_mb=0.0, shader_instructions=0),
        auto_fixable=True,
        guidance=None,
    )


# ── LL002 ─────────────────────────────────────────────────────────────────────


def check_ll002(asset: dict, engine: str = "unreal") -> Finding | None:
    """LL002: Light's draw distance / radius creates measurable overdraw."""
    if asset.get("asset_type") not in ("PointLight", "SpotLight", "RectLight"):
        return None

    overdraw: float = float(asset.get("avg_overdraw", 0.0))
    threshold = THRESHOLDS.get("LL002_OVERDRAW_THRESHOLD", _DEFAULT_OVERDRAW_THRESHOLD)

    if overdraw <= threshold:
        return None

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LL002",
        category="Lighting",
        severity="info",
        message=(
            f"Light averages {overdraw:.1f}x overdraw — "
            "many pixels lit by multiple lights at once. "
            "Reduce attenuation radius or convert to baked lighting if static."
        ),
        current={"avg_overdraw": overdraw},
        recommended={"avg_overdraw": f"<= {threshold}"},
        estimated_saving=Saving(vram_mb=0.0, shader_instructions=0),
        auto_fixable=False,
        guidance=guidance_for("LL002", engine),
    )
