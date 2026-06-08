# core/modules/lod_auditor/rules/lod_textures.py
#
# Texture LOD rules: LT001 – LT005
#
# Each rule is a pure function:
#   check_ltXXX(asset: dict) -> Finding | None
#
# THRESHOLDS centralises every numeric/enum decision so values can be
# adjusted without touching rule logic.

import logging

from lod_auditor.config import load_profile
from lod_auditor.schema import Finding, Saving
from lod_auditor.vram_model import estimate_texture_vram_mb, normalize_compression

_logger = logging.getLogger("shinttools.lod_auditor")

# Thresholds are loaded from YAML — see config/thresholds_default.yaml.
# Profile can be switched at runtime: load_profile("mobile") swaps the
# cached values transparently across all rules.
THRESHOLDS = load_profile()

# Usages whose data is linear/non-perceptual — sRGB must be OFF
_DATA_USAGES: frozenset[str] = frozenset({"Normal", "Mask", "HDR", "Data"})

# Usages that are perceptual color — sRGB must be ON
_COLOR_USAGES: frozenset[str] = frozenset({"BaseColor", "UI"})

# Usages where a mip chain is required (3D rendered textures)
_MIPS_REQUIRED_USAGES: frozenset[str] = frozenset(
    {"BaseColor", "Normal", "Mask", "HDR", "Data"}
)

# Usages where mips are wasteful (UI always renders at a fixed pixel size)
_MIPS_WASTEFUL_USAGES: frozenset[str] = frozenset({"UI"})


# ── LT001 ─────────────────────────────────────────────────────────────────────


def check_lt001(asset: dict) -> Finding | None:
    """LT001: Compression format not optimal for the texture's declared usage."""
    usage: str = asset.get("usage", "")
    compression_raw: str = asset.get("compression", "")
    compression: str = normalize_compression(compression_raw)

    expected_formats: dict = THRESHOLDS["LT001_EXPECTED_FORMAT"]
    expected: str | None = expected_formats.get(usage)

    if not expected:
        if usage:
            _logger.debug(
                "LT001: usage '%s' not in expected-format map for '%s' — skipped",
                usage,
                asset.get("asset_path", "?"),
            )
        return None

    if compression == expected:
        return None

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LT001",
        category="Texture",
        severity="warning",
        message=(
            f"Usage '{usage}' expects {expected} compression, "
            f"but '{compression}' was found. "
            "Wrong format degrades quality or wastes VRAM."
        ),
        current={"compression": compression},
        recommended={"compression": expected},
        estimated_saving=Saving(vram_mb=0.0, shader_instructions=0),
        auto_fixable=True,
        guidance=None,
    )


# ── LT002 ─────────────────────────────────────────────────────────────────────


def check_lt002(asset: dict) -> Finding | None:
    """LT002: MIP chain configuration does not match the texture's usage."""
    usage: str = asset.get("usage", "")
    mips_enabled: bool = asset.get("mips_enabled", True)

    if usage in _MIPS_REQUIRED_USAGES and not mips_enabled:
        return Finding(
            asset_path=asset["asset_path"],
            rule_id="LT002",
            category="Texture",
            severity="warning",
            message=(
                f"'{usage}' texture has MIPs disabled. "
                "MIPs prevent shimmering and reduce average VRAM at distance "
                "(total cost with mips: +33 %, but avg sampled VRAM is lower)."
            ),
            current={"mips_enabled": False},
            recommended={"mips_enabled": True},
            estimated_saving=Saving(vram_mb=0.0, shader_instructions=0),
            auto_fixable=True,
            guidance=None,
        )

    if usage in _MIPS_WASTEFUL_USAGES and mips_enabled:
        return Finding(
            asset_path=asset["asset_path"],
            rule_id="LT002",
            category="Texture",
            severity="warning",
            message=(
                "UI texture has MIPs enabled — wastes ~33 % VRAM "
                "with no visual benefit (UI renders at a fixed pixel size)."
            ),
            current={"mips_enabled": True},
            recommended={"mips_enabled": False},
            estimated_saving=Saving(vram_mb=0.0, shader_instructions=0),
            auto_fixable=True,
            guidance=None,
        )

    return None


# ── LT003 ─────────────────────────────────────────────────────────────────────


def check_lt003(asset: dict) -> Finding | None:
    """LT003: Texture resolution exceeds the slot budget for its LOD group."""
    lod_group: str = asset.get("lod_group", "World")
    width: int = asset.get("width", 0)
    height: int = asset.get("height", 0)
    compression_raw: str = asset.get("compression", "RGBA8")
    compression: str = normalize_compression(compression_raw)
    mips_enabled: bool = asset.get("mips_enabled", True)

    budget_map: dict = THRESHOLDS["LT003_MAX_SIZE_BY_LOD_GROUP"]
    if lod_group not in budget_map:
        _logger.debug(
            "LT003: lod_group '%s' not in budget map for '%s' — using default %dpx",
            lod_group,
            asset.get("asset_path", "?"),
            THRESHOLDS["LT003_DEFAULT_MAX_SIZE"],
        )
    budget: int = budget_map.get(lod_group, THRESHOLDS["LT003_DEFAULT_MAX_SIZE"])

    long_edge: int = max(width, height)
    if long_edge <= budget:
        return None

    current_vram: float = estimate_texture_vram_mb(
        width, height, compression, with_mips=mips_enabled
    )

    # Scale both dimensions uniformly to the budget
    scale: float = budget / long_edge
    recommended_width: int = max(1, int(width * scale))
    recommended_height: int = max(1, int(height * scale))
    recommended_vram: float = estimate_texture_vram_mb(
        recommended_width, recommended_height, compression, with_mips=mips_enabled
    )
    vram_saved: float = round(current_vram - recommended_vram, 2)

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LT003",
        category="Texture",
        severity="warning",
        message=(
            f"{width}×{height} texture in LOD group '{lod_group}' "
            f"exceeds the {budget} px slot budget. "
            f"Estimated saving: {vram_saved} MB VRAM."
        ),
        current={"max_texture_size": long_edge, "vram_mb": current_vram},
        recommended={"max_texture_size": budget, "vram_mb": recommended_vram},
        estimated_saving=Saving(vram_mb=vram_saved, shader_instructions=0),
        auto_fixable=True,
        guidance=None,
    )


# ── LT004 ─────────────────────────────────────────────────────────────────────


def check_lt004(asset: dict) -> Finding | None:
    """LT004: sRGB flag does not match the texture's data type."""
    usage: str = asset.get("usage", "")
    srgb: bool = asset.get("srgb", True)

    if usage in _DATA_USAGES and srgb:
        return Finding(
            asset_path=asset["asset_path"],
            rule_id="LT004",
            category="Texture",
            severity="warning",
            message=(
                f"Data texture (usage='{usage}') has sRGB enabled. "
                "The shader will incorrectly gamma-decode the raw values, "
                "causing visible rendering artifacts."
            ),
            current={"srgb": True},
            recommended={"srgb": False},
            estimated_saving=Saving(vram_mb=0.0, shader_instructions=0),
            auto_fixable=True,
            guidance=None,
        )

    if usage in _COLOR_USAGES and not srgb:
        return Finding(
            asset_path=asset["asset_path"],
            rule_id="LT004",
            category="Texture",
            severity="warning",
            message=(
                f"Color texture (usage='{usage}') has sRGB disabled. "
                "Colors will appear too dark because the engine skips the "
                "gamma correction expected for perceptual color inputs."
            ),
            current={"srgb": False},
            recommended={"srgb": True},
            estimated_saving=Saving(vram_mb=0.0, shader_instructions=0),
            auto_fixable=True,
            guidance=None,
        )

    return None


# ── LT005 ─────────────────────────────────────────────────────────────────────


def check_lt005(asset: dict) -> Finding | None:
    """LT005: Large texture with streaming disabled occupies VRAM permanently."""
    width: int = asset.get("width", 0)
    height: int = asset.get("height", 0)
    streaming: bool = asset.get("streaming", True)
    compression_raw: str = asset.get("compression", "RGBA8")
    compression: str = normalize_compression(compression_raw)

    min_edge: int = THRESHOLDS["LT005_STREAMING_MIN_EDGE"]
    long_edge: int = max(width, height)

    if long_edge < min_edge or streaming:
        return None

    resident_vram: float = estimate_texture_vram_mb(
        width, height, compression, with_mips=True
    )

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LT005",
        category="Texture",
        severity="info",
        message=(
            f"{width}×{height} texture has streaming disabled — "
            f"it occupies {resident_vram} MB of VRAM permanently. "
            "Enable streaming so the engine unloads it when not visible."
        ),
        current={"streaming": False, "resident_vram_mb": resident_vram},
        recommended={"streaming": True},
        estimated_saving=Saving(vram_mb=0.0, shader_instructions=0),
        auto_fixable=True,
        guidance=None,
    )
