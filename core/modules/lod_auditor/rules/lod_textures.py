# core/modules/lod_auditor/rules/lod_textures.py
#
# Texture LOD rules: LT001 – LT008
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


def check_lt001(asset: dict, engine: str = "unreal") -> Finding | None:
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


def check_lt002(asset: dict, engine: str = "unreal") -> Finding | None:
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


def check_lt003(asset: dict, engine: str = "unreal") -> Finding | None:
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


def check_lt004(asset: dict, engine: str = "unreal") -> Finding | None:
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


def check_lt005(asset: dict, engine: str = "unreal") -> Finding | None:
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


# ── Power-of-two helpers (LT006) ───────────────────────────────────────────────


def _is_power_of_two(n: int) -> bool:
    """True for 1, 2, 4, 8, … (and only those). 0/negatives are not POT."""
    return n > 0 and (n & (n - 1)) == 0


def _floor_pow2(n: int) -> int:
    """Largest power of two <= n (min 1). Used to suggest a POT downsize."""
    if n < 1:
        return 1
    return 1 << (n.bit_length() - 1)


# RDO (rate-distortion optimisation) only applies to block-compressed formats;
# uncompressed and HDR payloads have nothing for it to shrink.
_RDO_FORMATS: frozenset[str] = frozenset({"BC1", "BC3", "BC4", "BC5", "BC7"})


# ── LT006 ─────────────────────────────────────────────────────────────────────


def check_lt006(asset: dict, engine: str = "unreal") -> Finding | None:
    """LT006: Non-power-of-two texture wastes memory through GPU padding.

    UE5 pads NPOT textures up to the next power of two for the mip chain,
    so a 1500×1500 texture costs as much VRAM as 2048×2048. UI textures are
    exempt — they sample at fixed pixel sizes and NPOT is idiomatic there.
    """
    width: int = asset.get("width", 0)
    height: int = asset.get("height", 0)
    lod_group: str = asset.get("lod_group", "World")
    compression: str = normalize_compression(asset.get("compression", "RGBA8"))
    mips_enabled: bool = asset.get("mips_enabled", True)

    if lod_group == "UI":
        return None

    min_edge: int = THRESHOLDS["LT006_NPOT_MIN_EDGE"]
    if max(width, height) < min_edge:
        return None

    if _is_power_of_two(width) and _is_power_of_two(height):
        return None

    rec_width: int = _floor_pow2(width)
    rec_height: int = _floor_pow2(height)

    current_vram: float = estimate_texture_vram_mb(
        width, height, compression, with_mips=mips_enabled
    )
    recommended_vram: float = estimate_texture_vram_mb(
        rec_width, rec_height, compression, with_mips=mips_enabled
    )
    vram_saved: float = round(current_vram - recommended_vram, 2)

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LT006",
        category="Texture",
        severity="warning",
        message=(
            f"{width}×{height} is not power-of-two — UE5 pads it on the GPU. "
            f"Resize to {rec_width}×{rec_height} to drop the padding "
            f"(≈ {vram_saved} MB VRAM)."
        ),
        current={"width": width, "height": height},
        recommended={"width": rec_width, "height": rec_height},
        estimated_saving=Saving(vram_mb=max(0.0, vram_saved), shader_instructions=0),
        auto_fixable=True,
        guidance=None,
    )


# ── LT007 ─────────────────────────────────────────────────────────────────────


def check_lt007(asset: dict, engine: str = "unreal") -> Finding | None:
    """LT007: Large texture stored uncompressed burns VRAM (4 bpp vs 1).

    Mirrors the Unity "uncompressed" family: below the min edge it stays
    quiet (filters noise on small UI/lookup textures); below the max edge
    it is info; at/above the max edge it escalates to warning. The
    recommended replacement is BC7 — the safe general-purpose RGBA block
    format. (LOD findings stay within the warning/info convention — see
    test_orchestrator.test_findings_have_valid_severity_values.)
    """
    width: int = asset.get("width", 0)
    height: int = asset.get("height", 0)
    compression: str = normalize_compression(asset.get("compression", "RGBA8"))
    mips_enabled: bool = asset.get("mips_enabled", True)

    # Only uncompressed payloads — normalize_compression collapses every
    # uncompressed UE5/Unity format onto "RGBA8".
    if compression != "RGBA8":
        return None

    min_edge: int = THRESHOLDS["LT007_UNCOMPRESSED_MIN_EDGE"]
    max_edge: int = THRESHOLDS["LT007_UNCOMPRESSED_MAX_EDGE"]
    long_edge: int = max(width, height)
    if long_edge < min_edge:
        return None

    recommended: str = "BC7"
    current_vram: float = estimate_texture_vram_mb(
        width, height, "RGBA8", with_mips=mips_enabled
    )
    recommended_vram: float = estimate_texture_vram_mb(
        width, height, recommended, with_mips=mips_enabled
    )
    vram_saved: float = round(current_vram - recommended_vram, 2)

    severity: str = "warning" if long_edge >= max_edge else "info"

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LT007",
        category="Texture",
        severity=severity,
        message=(
            f"{width}×{height} texture is uncompressed (RGBA8) — "
            f"compress to {recommended} to save ≈ {vram_saved} MB VRAM."
        ),
        current={"compression": "RGBA8", "vram_mb": current_vram},
        recommended={"compression": recommended, "vram_mb": recommended_vram},
        estimated_saving=Saving(vram_mb=max(0.0, vram_saved), shader_instructions=0),
        auto_fixable=True,
        guidance=None,
    )


# ── LT008 ─────────────────────────────────────────────────────────────────────


def check_lt008(asset: dict, engine: str = "unreal") -> Finding | None:
    """LT008: Block-compressed texture has Oodle RDO off — larger package.

    RDO trades a little quality for a smaller on-disk payload; it does not
    change runtime VRAM, so the saving is reported as build_size_mb, never
    vram_mb. Fires only when the collector explicitly reports rdo_enabled
    is False — an absent field means an older client that doesn't send it
    yet, so the rule stays silent rather than guessing.
    """
    rdo_enabled = asset.get("rdo_enabled", None)
    if rdo_enabled is not False:
        return None

    compression: str = normalize_compression(asset.get("compression", ""))
    if compression not in _RDO_FORMATS:
        return None

    width: int = asset.get("width", 0)
    height: int = asset.get("height", 0)
    min_edge: int = THRESHOLDS["LT008_RDO_MIN_EDGE"]
    if max(width, height) < min_edge:
        return None

    # RDO typically shaves ~15 % off the compressed payload. We model VRAM,
    # so reuse the resident-size arithmetic as a payload proxy and report it
    # strictly as a build-size saving.
    payload_mb: float = estimate_texture_vram_mb(
        width, height, compression, with_mips=True
    )
    build_saved: float = round(payload_mb * 0.15, 2)

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LT008",
        category="Texture",
        severity="info",
        message=(
            f"{width}×{height} {compression} texture has Oodle RDO disabled — "
            f"enable it to shave ≈ {build_saved} MB off the package "
            "(build size only; runtime VRAM is unchanged)."
        ),
        current={"rdo_enabled": False},
        recommended={"rdo_enabled": True},
        estimated_saving=Saving(
            vram_mb=0.0, shader_instructions=0, build_size_mb=build_saved
        ),
        auto_fixable=True,
        guidance=None,
    )
