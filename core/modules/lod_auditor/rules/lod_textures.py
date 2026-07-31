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
from lod_auditor.schema import VRAM_SAVING_TOKEN, Finding, Saving
from lod_auditor.vram_model import (
    BYTES_PER_PIXEL,
    effective_texture_size,
    estimate_texture_vram_mb,
    normalize_compression,
    resolve_texture_bpp,
)

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


def check_lt001(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LT001: Compression format not optimal for the texture's declared usage."""
    T = thresholds if thresholds is not None else THRESHOLDS
    usage: str = asset.get("usage", "")
    compression_raw: str = asset.get("compression", "")
    compression: str = normalize_compression(compression_raw)

    expected_formats: dict = T["LT001_EXPECTED_FORMAT"]
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


def check_lt003(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LT003: Texture resolution exceeds the slot budget for its LOD group."""
    T = thresholds if thresholds is not None else THRESHOLDS
    lod_group: str = asset.get("lod_group", "World")
    compression_raw: str = asset.get("compression", "RGBA8")
    compression: str = normalize_compression(compression_raw)
    mips_enabled: bool = asset.get("mips_enabled", True)

    # Judge the texture the engine actually uploads, not the source file. A
    # 4096 source already capped to max_texture_size=2048 is a 2048 texture on
    # the GPU: flagging it as "4096, reduce to 2048" was both a false positive
    # and a 4x over-estimate of its cost.
    width, height = effective_texture_size(
        asset.get("width", 0), asset.get("height", 0), asset.get("max_texture_size", 0)
    )

    budget_map: dict = T["LT003_MAX_SIZE_BY_LOD_GROUP"]
    if lod_group not in budget_map:
        _logger.debug(
            "LT003: lod_group '%s' not in budget map for '%s' — using default %dpx",
            lod_group,
            asset.get("asset_path", "?"),
            T["LT003_DEFAULT_MAX_SIZE"],
        )
    budget: int = budget_map.get(lod_group, T["LT003_DEFAULT_MAX_SIZE"])

    # Optional global ceiling (per-request override): a project can cap every
    # LOD group at one size regardless of the per-group budget, e.g. "nothing
    # over 1024 on this mobile target". Absent in the YAML profiles — only the
    # request overrides inject it (see lod_orchestrator._build_thresholds).
    global_max = T.get("LT003_GLOBAL_MAX_SIZE")
    if global_max is not None:
        budget = min(budget, int(global_max))

    long_edge: int = max(width, height)
    if long_edge <= budget:
        return None

    # Resolve once at the current size: an unmapped format (Unity reports
    # "Automatic" unless a platform override is set) is priced from the
    # client's own measurement rather than guessed.
    bpp: float = resolve_texture_bpp(
        compression, width, height, mips_enabled, asset.get("size_kb")
    )

    current_vram: float = estimate_texture_vram_mb(
        width, height, compression, with_mips=mips_enabled, bpp_override=bpp
    )

    # Scale both dimensions uniformly to the budget
    scale: float = budget / long_edge
    recommended_width: int = max(1, int(width * scale))
    recommended_height: int = max(1, int(height * scale))
    recommended_vram: float = estimate_texture_vram_mb(
        recommended_width,
        recommended_height,
        compression,
        with_mips=mips_enabled,
        bpp_override=bpp,
    )
    vram_saved: float = max(0.0, round(current_vram - recommended_vram, 2))

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LT003",
        category="Texture",
        severity="warning",
        message=(
            (
                f"{width}×{height} texture in LOD group '{lod_group}' "
                f"exceeds the {budget} px slot budget. "
                if engine != "unity"
                else f"{width}×{height} texture exceeds the {budget} px "
                f"max-size budget. "
            )
            + f"Estimated saving: {VRAM_SAVING_TOKEN} MB VRAM."
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

    # Abstain when the client doesn't report the flag at all. Defaulting to
    # True made this fire on every Normal/Mask/HDR/Data texture from a client
    # that omits the field (the Unity collector does not send `srgb`), which
    # is a guaranteed false positive on an entire engine rather than a finding.
    if "srgb" not in asset or asset.get("srgb") is None:
        return None
    srgb: bool = bool(asset.get("srgb"))

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


def check_lt005(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LT005: Large texture with streaming disabled occupies VRAM permanently."""
    T = thresholds if thresholds is not None else THRESHOLDS
    streaming: bool = asset.get("streaming", True)
    compression_raw: str = asset.get("compression", "RGBA8")
    compression: str = normalize_compression(compression_raw)

    # Resident cost is what the GPU holds — the import-capped size, not source.
    width, height = effective_texture_size(
        asset.get("width", 0), asset.get("height", 0), asset.get("max_texture_size", 0)
    )

    min_edge: int = T["LT005_STREAMING_MIN_EDGE"]
    long_edge: int = max(width, height)

    if long_edge < min_edge or streaming:
        return None

    resident_vram: float = estimate_texture_vram_mb(
        width,
        height,
        compression,
        with_mips=True,
        bpp_override=resolve_texture_bpp(
            compression, width, height, True, asset.get("size_kb")
        ),
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

# Formats that already store the payload in fixed-size blocks. LT006 must not
# warn that NPOT "can disable block compression" about one of these.
_BLOCK_COMPRESSED_PREFIXES: tuple[str, ...] = ("BC", "ASTC", "ETC", "EAC", "PVRTC")
_BLOCK_COMPRESSED_FORMATS: frozenset[str] = frozenset(
    fmt
    for fmt in BYTES_PER_PIXEL
    if fmt.upper().startswith(_BLOCK_COMPRESSED_PREFIXES)
)


# ── LT006 ─────────────────────────────────────────────────────────────────────


def check_lt006(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LT006: Non-power-of-two texture wastes memory through GPU padding.

    UE5 pads NPOT textures up to the next power of two for the mip chain,
    so a 1500×1500 texture costs as much VRAM as 2048×2048. UI textures are
    exempt — they sample at fixed pixel sizes and NPOT is idiomatic there.
    """
    T = thresholds if thresholds is not None else THRESHOLDS
    lod_group: str = asset.get("lod_group", "World")
    compression: str = normalize_compression(asset.get("compression", "RGBA8"))
    mips_enabled: bool = asset.get("mips_enabled", True)

    # POT-ness is a property of the resident texture. A capped import can turn
    # an NPOT source into a POT upload (and vice versa), so judge the capped
    # dimensions — flagging the source would report padding that isn't there.
    width, height = effective_texture_size(
        asset.get("width", 0), asset.get("height", 0), asset.get("max_texture_size", 0)
    )

    if lod_group == "UI":
        return None

    # Unity's importer can scale an NPOT source to a power of two on import
    # (TextureImporter.npotScale). When it is set to anything but None the
    # upload is already POT and there is no padding to report — the source
    # resolution is not what the GPU holds. Absent field = no scaling, which
    # is UE5's behaviour and Unity's default for compressed textures.
    npot_scale: str = str(asset.get("npot_scale", "") or "").strip().lower()
    if npot_scale and npot_scale not in {"none", "0"}:
        return None

    min_edge: int = T["LT006_NPOT_MIN_EDGE"]
    if max(width, height) < min_edge:
        return None

    if _is_power_of_two(width) and _is_power_of_two(height):
        return None

    rec_width: int = _floor_pow2(width)
    rec_height: int = _floor_pow2(height)

    bpp: float = resolve_texture_bpp(
        compression, width, height, mips_enabled, asset.get("size_kb")
    )
    current_vram: float = estimate_texture_vram_mb(
        width, height, compression, with_mips=mips_enabled, bpp_override=bpp
    )
    recommended_vram: float = estimate_texture_vram_mb(
        rec_width, rec_height, compression, with_mips=mips_enabled, bpp_override=bpp
    )
    vram_saved: float = round(current_vram - recommended_vram, 2)

    # Two claims we must not make blindly. "Block compression is disabled" is
    # false for a texture already stored in a block format — the panel shows
    # the format one column away from the message. And a per-axis floor to POT
    # squashes any non-square texture (2048×1364 → 2048×1024), which is a
    # re-authoring decision, not a checkbox: say so instead of implying the
    # importer can do it.
    already_block_compressed: bool = compression in _BLOCK_COMPRESSED_FORMATS
    aspect_preserved: bool = width * rec_height == height * rec_width

    size = f"{width}×{height} (imported size)"
    if engine == "unity":
        head = f"{size} is not power-of-two — this wastes memory"
        head += (
            "."
            if already_block_compressed
            else " and can disable block compression."
        )
    else:
        head = f"{size} is not power-of-two — UE5 pads it on the GPU."

    tail = (
        f" Resize the source to {rec_width}×{rec_height} "
        f"(≈ {VRAM_SAVING_TOKEN} MB VRAM)."
    )
    if not aspect_preserved:
        tail += (
            " Note this changes the aspect ratio, so the art has to be re-authored "
            "or cropped — no importer setting can do it for you."
        )

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LT006",
        category="Texture",
        severity="warning",
        message=head + tail,
        current={"width": width, "height": height},
        recommended={"width": rec_width, "height": rec_height},
        estimated_saving=Saving(vram_mb=max(0.0, vram_saved), shader_instructions=0),
        # Source dimensions are not an importer property in either engine: the
        # fix is a DCC round-trip (or Unity's npotScale, which the collectors
        # do not expose yet). Advertising a "Fix" button here would resolve to
        # a no-op — see ASSET_OPTIMIZER_OUTPUT_CONTRACT §1.
        auto_fixable=False,
        guidance=None,
    )


# ── LT007 ─────────────────────────────────────────────────────────────────────


def check_lt007(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LT007: Large texture stored uncompressed burns VRAM (4 bpp vs 1).

    Mirrors the Unity "uncompressed" family: below the min edge it stays
    quiet (filters noise on small UI/lookup textures); below the max edge
    it is info; at/above the max edge it escalates to warning. The
    recommended replacement is BC7 — the safe general-purpose RGBA block
    format. (LOD findings stay within the warning/info convention — see
    test_orchestrator.test_findings_have_valid_severity_values.)
    """
    T = thresholds if thresholds is not None else THRESHOLDS
    compression: str = normalize_compression(asset.get("compression", "RGBA8"))
    mips_enabled: bool = asset.get("mips_enabled", True)

    # Only uncompressed payloads — normalize_compression collapses every
    # uncompressed UE5/Unity format onto "RGBA8".
    if compression != "RGBA8":
        return None

    # Price the compression win against the resident (import-capped) size.
    width, height = effective_texture_size(
        asset.get("width", 0), asset.get("height", 0), asset.get("max_texture_size", 0)
    )

    min_edge: int = T["LT007_UNCOMPRESSED_MIN_EDGE"]
    max_edge: int = T["LT007_UNCOMPRESSED_MAX_EDGE"]
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
            f"compress to {recommended} to save ≈ {VRAM_SAVING_TOKEN} MB VRAM."
        ),
        current={"compression": "RGBA8", "vram_mb": current_vram},
        recommended={"compression": recommended, "vram_mb": recommended_vram},
        estimated_saving=Saving(vram_mb=max(0.0, vram_saved), shader_instructions=0),
        auto_fixable=True,
        guidance=None,
    )


# ── LT008 ─────────────────────────────────────────────────────────────────────


def check_lt008(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LT008: Block-compressed texture has Oodle RDO off — larger package.

    RDO trades a little quality for a smaller on-disk payload; it does not
    change runtime VRAM, so the saving is reported as build_size_mb, never
    vram_mb. Fires only when the collector explicitly reports rdo_enabled
    is False — an absent field means an older client that doesn't send it
    yet, so the rule stays silent rather than guessing.
    """
    T = thresholds if thresholds is not None else THRESHOLDS
    rdo_enabled = asset.get("rdo_enabled", None)
    if rdo_enabled is not False:
        return None

    compression: str = normalize_compression(asset.get("compression", ""))
    if compression not in _RDO_FORMATS:
        return None

    # The cooked payload is the capped upload, not the source file.
    width, height = effective_texture_size(
        asset.get("width", 0), asset.get("height", 0), asset.get("max_texture_size", 0)
    )
    min_edge: int = T["LT008_RDO_MIN_EDGE"]
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


# ── Shared helper for the texture-completion rules (LT009–LT016) ───────────────


def _conf(recommended: dict, level: str) -> dict:
    recommended["confidence"] = level
    return recommended


# Groups that always minify (guaranteed shimmer without mips).
_MINIFYING_GROUPS = frozenset({"World", "Environment", "Terrain"})


# ── LT009 ─────────────────────────────────────────────────────────────────────


def check_lt009(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LT009: Missing mipmaps on a 3D-sampled texture (minification shimmer)."""
    T = thresholds if thresholds is not None else THRESHOLDS
    usage = asset.get("usage", "")
    if usage == "UI":
        return None  # UI renders at a fixed pixel size — mips are wasteful (LT002)
    width, height = effective_texture_size(
        asset.get("width", 0), asset.get("height", 0), asset.get("max_texture_size", 0)
    )
    mips_enabled = asset.get("mips_enabled", True)
    mip_count = int(asset.get("mip_count", 0) or 0)
    missing = (not mips_enabled) or (
        mip_count == 1 and width * height > T["LT009_MIN_PIXELS"]
    )
    if not missing:
        return None
    lod_group = asset.get("lod_group", "World")
    severity = "error" if lod_group in _MINIFYING_GROUPS else "warning"
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LT009",
        category="Texture",
        severity=severity,
        message=(
            f"{width}×{height} '{usage or lod_group}' texture has no mip chain — "
            "guaranteed minification shimmer and full-res sampling at distance "
            "(mips add ~33% VRAM but cut average sampled bandwidth)."
        ),
        current={"mips_enabled": bool(mips_enabled), "mip_count": mip_count},
        recommended=_conf({"mips_enabled": True}, "high"),
        estimated_saving=Saving(vram_mb=0.0),
        auto_fixable=True,
        guidance=None,
    )


# ── LT010 ─────────────────────────────────────────────────────────────────────


def check_lt010(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LT010: Texture LOD group inconsistent with the texture's usage."""
    if engine == "unity":
        return None  # texture LOD groups are a UE5 concept (§13.9)
    T = thresholds if thresholds is not None else THRESHOLDS
    usage = asset.get("usage", "")
    expected_map: dict = T["LT010_EXPECTED_GROUP"]
    expected = expected_map.get(usage)
    if not expected:
        return None
    lod_group = asset.get("lod_group", "")
    # Glob-ish substring match ("NormalMap" matches "WorldNormalMap").
    if any(token and token in lod_group for token in expected.split("|")):
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LT010",
        category="Texture",
        severity="warning",
        message=(
            f"'{usage}' texture is in LOD group '{lod_group or 'None'}' — expected a "
            f"'{expected}' group. Wrong group means wrong streaming priority and "
            "the wrong resolution budget."
        ),
        current={"lod_group": lod_group, "usage": usage},
        recommended=_conf({"lod_group": expected}, "high"),
        estimated_saving=Saving(),
        auto_fixable=True,
        guidance=None,
    )


# ── LT013 ─────────────────────────────────────────────────────────────────────


def check_lt013(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LT013: Single-channel masks that could pack into one RGBA texture."""
    T = thresholds if thresholds is not None else THRESHOLDS
    if asset.get("usage") not in ("Mask", "Data"):
        return None
    # The client precomputes the pack set via the material cross-join and sends
    # it as pack_candidates; per-asset we can't join, so we abstain without it.
    candidates = asset.get("pack_candidates", []) or []
    if len(candidates) < T["LT013_MIN_PACK_CANDIDATES"]:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LT013",
        category="Texture",
        severity="info",
        message=(
            f"{len(candidates)} single-channel mask/data textures on the same "
            "material could pack into one RGBA texture (4× fewer fetches)."
        ),
        current={"pack_candidates": list(candidates)},
        recommended=_conf({"packed_into": "single RGBA texture"}, "medium"),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=None,
    )


# ── LT014 ─────────────────────────────────────────────────────────────────────


def check_lt014(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LT014: A single texture exceeds the absolute per-asset VRAM ceiling."""
    T = thresholds if thresholds is not None else THRESHOLDS
    # The ceiling is about resident VRAM, so measure the capped upload size.
    width, height = effective_texture_size(
        asset.get("width", 0), asset.get("height", 0), asset.get("max_texture_size", 0)
    )
    if width <= 0 or height <= 0:
        return None
    compression = normalize_compression(asset.get("compression", "RGBA8"))
    mips = asset.get("mips_enabled", True)
    ceiling = T["LT014_MAX_SINGLE_TEXTURE_MB"]
    # Resolve once at the current size — this rule escalates to "error", so an
    # unmapped format guessed as RGBA8 would fire it on a texture that is
    # actually well under the ceiling.
    bpp = resolve_texture_bpp(compression, width, height, mips, asset.get("size_kb"))
    current_vram = estimate_texture_vram_mb(
        width, height, compression, with_mips=mips, bpp_override=bpp
    )
    if current_vram <= ceiling:
        return None
    # Largest max_texture_size that lands under the ceiling. The candidate is
    # evaluated through effective_texture_size because that is what the cap
    # actually does — it clamps the long edge and preserves aspect ratio.
    # Measuring square candidates instead over-stated a non-square texture's
    # post-fix cost by the aspect ratio (a 8192×1024 was priced as 8192×8192),
    # which under-reported the saving by the same factor.
    long_edge = max(width, height)
    target_edge = long_edge

    def _vram_at(cap: int) -> float:
        w, h = effective_texture_size(width, height, cap)
        return estimate_texture_vram_mb(
            w, h, compression, with_mips=mips, bpp_override=bpp
        )

    while target_edge > 1 and _vram_at(target_edge) > ceiling:
        target_edge //= 2
    recommended_vram = _vram_at(target_edge)
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LT014",
        category="Texture",
        severity="error",
        message=(
            f"{width}×{height} {compression} texture costs {current_vram} MB — over "
            f"the {ceiling} MB single-texture ceiling regardless of group."
        ),
        current={"max_texture_size": long_edge, "vram_mb": current_vram},
        recommended=_conf(
            {"max_texture_size": target_edge, "vram_mb": recommended_vram}, "high"
        ),
        estimated_saving=Saving(vram_mb=round(current_vram - recommended_vram, 2)),
        auto_fixable=True,
        guidance=None,
    )


# ── LT016 ─────────────────────────────────────────────────────────────────────


def check_lt016(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LT016: Always-resident UI/effects texture left in the streaming pool."""
    usage = asset.get("usage", "")
    lod_group = asset.get("lod_group", "")
    if not asset.get("streaming", False):
        return None
    if not (usage == "UI" or lod_group in ("UI", "Effects")):
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LT016",
        category="Texture",
        severity="info",
        message=(
            f"Always-resident '{usage or lod_group}' texture is in the streaming "
            "pool — it churns the pool with no benefit (it never streams out)."
        ),
        current={"streaming": True, "usage": usage, "lod_group": lod_group},
        recommended=_conf({"never_stream": True}, "high"),
        estimated_saving=Saving(),
        auto_fixable=True,
        guidance=None,
    )
