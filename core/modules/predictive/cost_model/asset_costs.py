# core/modules/predictive/cost_model/asset_costs.py
#
# Per-asset memory/build cost formulas (Layer 1).
#
# Everything deterministic delegates to lod_auditor.vram_model — the same
# arithmetic the LOD Auditor ships, already battle-tested against the Unity
# format-name bugs (2.4.0-2.4.2). Confidence:
#   VRAM        → high  (block-compression math is exact; unmapped formats
#                        derive bytes/px from the client's own measurement)
#   build size  → medium (cooked payload ≈ GPU payload × package ratio; the
#                        ratio is a calibration target, not a constant of
#                        nature)

from __future__ import annotations

from typing import Any

from lod_auditor.vram_model import (
    estimate_texture_vram_mb,
    mesh_buffer_mb,
    resolve_texture_bpp,
)
from predictive.cost_model.prediction import Prediction

# Cooked-payload ratio for block-compressed texture data under the default
# lossless package compression (Oodle/LZ4). Band, not a scalar — M5
# calibration narrows it per compression setting.
_PACKAGE_RATIO_EXPECTED = 0.85
_PACKAGE_RATIO_MIN = 0.65
_PACKAGE_RATIO_MAX = 1.0

_TEXTURE_TYPES = frozenset(
    {"Texture2D", "Texture", "Texture2DArray", "TextureCube", "VolumeTexture"}
)
_MESH_TYPES = frozenset({"StaticMesh", "SkeletalMesh", "Mesh"})


def texture_vram(asset: dict[str, Any]) -> Prediction | None:
    """Exact VRAM cost of one texture asset, or None when undersized data."""
    width = int(asset.get("width", 0) or 0)
    height = int(asset.get("height", 0) or 0)
    if width <= 0 or height <= 0:
        return None
    compression = str(asset.get("compression", "RGBA8"))
    mips = bool(asset.get("mips_enabled", True))
    bpp = resolve_texture_bpp(
        compression, width, height, mips, asset.get("size_kb")
    )
    mb = estimate_texture_vram_mb(
        width, height, compression, with_mips=mips, bpp_override=bpp
    )
    return Prediction.exact(
        mb, "mb", f"{width}×{height} {compression} ({bpp:g} B/px, mips={mips})"
    )


def mesh_vram(asset: dict[str, Any]) -> Prediction | None:
    """Vertex-buffer VRAM cost of one mesh asset (LOD0 vertex count)."""
    verts = int(asset.get("vertex_count", 0) or 0)
    if verts <= 0:
        return None
    mb = mesh_buffer_mb(verts)
    return Prediction.exact(mb, "mb", f"{verts:,} verts × 32 B vertex stride")


def asset_vram(asset: dict[str, Any]) -> Prediction | None:
    """VRAM cost of one asset dict, dispatched by asset_type."""
    kind = str(asset.get("asset_type", ""))
    if kind in _TEXTURE_TYPES:
        return texture_vram(asset)
    if kind in _MESH_TYPES:
        return mesh_vram(asset)
    return None


def asset_build_mb(vram: Prediction, compression_cfg: str = "") -> Prediction:
    """Cooked build-size band derived from an asset's GPU payload.

    The GPU payload is what actually gets cooked; the package ratio models
    the lossless pass on top. ``compression_cfg`` (config.build.compression)
    is reserved for per-codec ratios once calibrated.
    """
    return Prediction.banded(
        vram.expected * _PACKAGE_RATIO_EXPECTED,
        vram.min * _PACKAGE_RATIO_MIN,
        vram.max * _PACKAGE_RATIO_MAX,
        "mb",
        "medium",
        f"GPU payload × {_PACKAGE_RATIO_MIN}–{_PACKAGE_RATIO_MAX} package ratio",
    )
