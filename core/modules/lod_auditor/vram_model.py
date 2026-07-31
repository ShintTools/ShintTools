# core/modules/lod_auditor/vram_model.py
#
# Texture VRAM estimator — pure arithmetic, zero external dependencies.
#
# Formula:
#   vram_mb = width * height * bytes_per_pixel * MIP_MULTIPLIER / BYTES_PER_MB
#
# Coefficient sources:
#   BYTES_PER_PIXEL — DirectX Block Compression spec
#     (learn.microsoft.com/windows/win32/direct3d11/
#      texture-block-compression-in-direct3d-11)
#   MIP_MULTIPLIER = 4/3 — geometric series: sum_{k=0}^{inf} (1/4)^k = 4/3
#     Each mip level is 1/4 the area of the previous; total = 4/3 × base.
#   BYTES_PER_MB = 1 048 576 (= 1024²)

import logging

_logger = logging.getLogger(__name__)

# ── Compression coefficients ──────────────────────────────────────────────────

# Bytes consumed per pixel for each canonical format.
BYTES_PER_PIXEL: dict[str, float] = {
    "RGBA8": 4.0,  # 32-bit uncompressed (4 channels × 8 bits)
    "BC1": 0.5,  # DXT1  — 4 bpp; RGB only, 1-bit alpha
    "BC3": 1.0,  # DXT5  — 8 bpp; RGB + full alpha
    "BC4": 0.5,  # ATI1  — 4 bpp; single channel (masks, AO)
    "BC5": 1.0,  # ATI2  — 8 bpp; two channels (normal maps XY)
    "BC6H": 1.0,  # HDR   — 8 bpp; signed/unsigned half-float
    "BC7": 1.0,  # BC7   — 8 bpp; high-quality RGBA
    # Uncompressed low-bpp formats (mostly Unity mobile import outputs).
    "RGB565": 2.0,  # 16-bit RGB, no alpha
    "RGBA4444": 2.0,  # 16-bit RGBA
    "R8": 1.0,  # 8-bit single channel
    # Mobile block formats — canonical bpp for the common block sizes. ASTC
    # varies with block size; these cover the import presets Unity emits by name.
    "ETC2_RGB": 0.5,  # 4 bpp
    "ETC2_RGBA": 1.0,  # 8 bpp
    "ETC2_RGBA1": 0.5,  # 4 bpp — punchthrough alpha, distinct from ETC2_RGBA
    "ETC_RGB4": 0.5,  # ETC1 — 4 bpp
    "EAC_R": 0.5,  # 4 bpp — single-channel EAC (used for ETC2 alpha too)
    "EAC_RG": 1.0,  # 8 bpp — two-channel EAC (normal maps)
    "ASTC_4x4": 1.0,  # 8.00 bpp
    "ASTC_5x5": 0.64,  # 5.12 bpp
    "ASTC_6x6": 0.4444,  # 3.56 bpp
    "ASTC_8x8": 0.25,  # 2.00 bpp
    "ASTC_10x10": 0.16,  # 1.28 bpp
    "ASTC_12x12": 0.111,  # 0.89 bpp
    "PVRTC_RGB2": 0.25,  # 2 bpp
    "PVRTC_RGBA2": 0.25,  # 2 bpp
    "PVRTC_RGB4": 0.5,  # 4 bpp
    "PVRTC_RGBA4": 0.5,  # 4 bpp
}

# Full mip chain adds 1/3 on top of the base-level cost.
MIP_MULTIPLIER: float = 4.0 / 3.0

BYTES_PER_MB: int = 1_048_576

# ── Format normalization ──────────────────────────────────────────────────────

# Maps UE5 TextureCompressionSettings (TC_*) and Unity equivalents to
# canonical BC* / RGBA8 names used by BYTES_PER_PIXEL.
# Canonical names pass through unchanged so callers don't need to branch.
_FORMAT_ALIASES: dict[str, str] = {
    # UE5 TC_* → canonical
    "TC_Default": "BC7",
    "TC_BC7": "BC7",
    "TC_Normalmap": "BC5",
    "TC_Grayscale": "BC4",
    "TC_Masks": "BC4",
    "TC_Alpha": "BC4",
    "TC_DistanceFieldFont": "BC4",
    "TC_HDR": "BC6H",
    "TC_HDR_F32": "BC6H",
    "TC_HalfFloat": "BC6H",
    "TC_LQ": "BC1",
    "TC_VectorDisplacementmap": "RGBA8",
    "TC_EditorIcon": "RGBA8",
    "TC_EncodedVelocity": "BC5",
    # Unity TextureFormat / import names → canonical. Without these, a Unity
    # "DXT1" fell through to the RGBA8 default (4 bpp) and every texture's VRAM
    # was over-estimated ~8×, producing savings larger than the source file and
    # negative "potential size" figures in the panel.
    "DXT1": "BC1",
    "DXT1Crunched": "BC1",
    "DXT5": "BC3",
    "DXT5Crunched": "BC3",
    "RGB24": "RGBA8",  # uploaded as 32-bit on the GPU
    "RGBA32": "RGBA8",
    "ARGB32": "RGBA8",
    "BGRA32": "RGBA8",
    "RGBAHalf": "BC6H",  # 8 bpp half-float equivalent for the estimate
    "RGB565": "RGB565",
    "RGBA4444": "RGBA4444",
    "ARGB4444": "RGBA4444",
    "Alpha8": "R8",
    "R8": "R8",
    "R16": "RGB565",  # 2 bytes/px
    "BC4": "BC4",
    "BC5": "BC5",
    "BC6H": "BC6H",
    "ETC2_RGB": "ETC2_RGB",
    "ETC2_RGBA8": "ETC2_RGBA",
    "ETC2_RGBA8Crunched": "ETC2_RGBA",
    "ETC2_RGBA1": "ETC2_RGBA1",
    "ETC_RGB4": "ETC_RGB4",
    "ETC1_RGB": "ETC_RGB4",
    "EAC_R": "EAC_R",
    "EAC_RG": "EAC_RG",
    "ASTC_4x4": "ASTC_4x4",
    "ASTC_5x5": "ASTC_5x5",
    "ASTC_6x6": "ASTC_6x6",
    "ASTC_8x8": "ASTC_8x8",
    "ASTC_10x10": "ASTC_10x10",
    "ASTC_12x12": "ASTC_12x12",
    "PVRTC_RGB2": "PVRTC_RGB2",
    "PVRTC_RGBA2": "PVRTC_RGBA2",
    "PVRTC_RGB4": "PVRTC_RGB4",
    "PVRTC_RGBA4": "PVRTC_RGBA4",
    # Unity TextureImporterFormat — the *importer* enum, whose member names
    # differ from the runtime TextureFormat enum above. The client reads
    # GetPlatformTextureSettings().format, so these are the names that
    # actually arrive over the wire; without them every compressed texture
    # fell back to RGBA8 and was reported ~8× its real size.
    "ETC2_RGB4": "ETC2_RGB",
    "ETC2_RGB4_PUNCHTHROUGH_ALPHA": "ETC2_RGBA1",
    "ETC_RGB4Crunched": "ETC_RGB4",
    "EAC_R_SIGNED": "EAC_R",
    "EAC_RG_SIGNED": "EAC_RG",
    "ASTC_RGB_4x4": "ASTC_4x4",
    "ASTC_RGB_5x5": "ASTC_5x5",
    "ASTC_RGB_6x6": "ASTC_6x6",
    "ASTC_RGB_8x8": "ASTC_8x8",
    "ASTC_RGB_10x10": "ASTC_10x10",
    "ASTC_RGB_12x12": "ASTC_12x12",
    "ASTC_RGBA_4x4": "ASTC_4x4",
    "ASTC_RGBA_5x5": "ASTC_5x5",
    "ASTC_RGBA_6x6": "ASTC_6x6",
    "ASTC_RGBA_8x8": "ASTC_8x8",
    "ASTC_RGBA_10x10": "ASTC_10x10",
    "ASTC_RGBA_12x12": "ASTC_12x12",
    # ASTC HDR shares the block layout (and therefore the bpp) of its LDR
    # counterpart — only the encoding of the payload differs.
    "ASTC_HDR_4x4": "ASTC_4x4",
    "ASTC_HDR_5x5": "ASTC_5x5",
    "ASTC_HDR_6x6": "ASTC_6x6",
    "ASTC_HDR_8x8": "ASTC_8x8",
    "ASTC_HDR_10x10": "ASTC_10x10",
    "ASTC_HDR_12x12": "ASTC_12x12",
    "RGB_PVRTC_2Bpp": "PVRTC_RGB2",
    "RGBA_PVRTC_2Bpp": "PVRTC_RGBA2",
    "RGB_PVRTC_4Bpp": "PVRTC_RGB4",
    "RGBA_PVRTC_4Bpp": "PVRTC_RGBA4",
    "RGB_ETC_4Bpp": "ETC_RGB4",
    "RGB_ETC2": "ETC2_RGB",
    "RGBA_ETC2": "ETC2_RGBA",
    # Uncompressed importer-enum spellings.
    "RGB16": "RGB565",
    "RGBA16": "RGBA4444",
    "RGB48": "RGBA8",
    "RGBA64": "RGBA8",
    "RG16": "RGB565",
    "RG32": "RGBA8",
    "RGBAFloat": "RGBA8",
    "RGBAHalf": "BC6H",
    "RHalf": "R8",
    "RFloat": "RGB565",
    "RGHalf": "RGB565",
    "RGFloat": "RGBA8",
    # canonical pass-through
    "RGBA8": "RGBA8",
    "BC1": "BC1",
    "BC3": "BC3",
    "BC4": "BC4",
    "BC5": "BC5",
    "BC6H": "BC6H",
    "BC7": "BC7",
}


# Unity's TextureImporterType, translated to the usage vocabulary the rules
# speak (UE5's). Only the values that genuinely assert what the texture is for
# are mapped: a rule keying off usage is claiming to know the texture's role,
# and Unity's "Default" asserts nothing — it is equally a base color, a
# roughness mask or a lookup table. Mapping it to BaseColor would have made
# LT001 demand BC7 and LT004 demand sRGB on every mask in the project.
#
# Without this table the whole usage-driven family (LT001 format-vs-usage,
# LT002/LT009 mips, LT004 sRGB) was silently inert on Unity: the collector
# sends "NormalMap", the rules look for "Normal", nothing matches, no finding
# is ever raised. A normal map stored as BC1 — common, and visibly wrong —
# went unreported for the entire engine.
#
# "Lightmap" is deliberately absent for the same reason: it names a role, but
# the format that role implies depends on the project's color space and on
# whether lighting is HDR or dLDR-encoded, so demanding BC6H would misfire on
# every mobile-encoded project.
_UNITY_USAGE_ALIASES: dict[str, str] = {
    "NormalMap": "Normal",
    "GUI": "UI",
    "Sprite": "UI",
    "Cursor": "UI",
    "Cookie": "Mask",
    "SingleChannel": "Mask",
}


def normalize_usage(raw: str) -> str:
    """Canonical usage name for *raw*, whichever engine's vocabulary it is in.

    Unrecognised values pass through unchanged, so a rule that keys off usage
    simply finds no match and abstains — the same behaviour as an absent
    field, and the right one for Unity's non-committal "Default".
    """
    if not raw:
        return ""
    return _UNITY_USAGE_ALIASES.get(raw.strip(), raw.strip())


def normalize_compression(raw: str) -> str:
    """Return the canonical format name for *raw*.

    Accepts UE5 TC_* names, Unity equivalents, or already-canonical
    BC*/RGBA8 strings.  Unknown values are returned unchanged so the
    caller can decide whether to treat them as RGBA8 or skip them.
    """
    return _FORMAT_ALIASES.get(raw, raw)


# ── Unsupported / non-analyzable formats ──────────────────────────────────────

# Palette-indexed and otherwise non-linear-addressable payloads. None of our
# optimisations apply to them: a palette's cost is driven by the palette + index
# table, not width*height*bpp, so every VRAM figure we could derive would be
# fiction — and a fictional baseline produces fictional savings and bogus
# "compress this" recommendations. They are skipped outright rather than
# guessed at (see is_analyzable_texture_format).
_INDEXED_FORMAT_TOKENS: tuple[str, ...] = (
    "INDEXED",
    "PALETTE",
    "PALETTIZED",
    "PAL4",
    "PAL8",
    "P8",
    "CI8",
    "CI4",
)

# Exact canonical/raw names that are indexed or otherwise unpriceable.
_UNSUPPORTED_FORMATS: frozenset[str] = frozenset(
    {
        "INDEXED",
        "INDEXED8",
        "INDEXED16",
        "PALETTE",
        "PALETTED",
        "PAL8",
        "PAL4",
        "P8",
        "CI8",
        "CI4",
        "BGRA8_INDEXED",
        "PNG8",
        "GIF",
    }
)


def is_indexed_format(fmt: str) -> bool:
    """True when *fmt* names a palette-indexed (or equivalent) texture payload.

    Matching is token-based and case-insensitive so engine-specific spellings
    ("TSF_P8", "TextureFormat.Indexed8", "PVRTC_Palette") are all caught
    without enumerating every vendor name.
    """
    if not fmt:
        return False
    upper = str(fmt).upper()
    if upper in _UNSUPPORTED_FORMATS:
        return True
    return any(token in upper for token in _INDEXED_FORMAT_TOKENS)


def is_analyzable_texture_format(
    fmt: str, measured_kb: float | None = None
) -> bool:
    """True when a texture's memory cost can be priced honestly.

    A format qualifies when it maps to a known bytes-per-pixel figure, or when
    the client measured the asset's real size (which lets resolve_texture_bpp
    back the figure out — this is how Unity's "Automatic" import setting is
    handled).

    Indexed formats never qualify. Neither does an unmapped format with no
    measurement: resolve_texture_bpp falls back to RGBA8 there, which
    over-states a compressed texture by up to 8x and makes every downstream
    number — the baseline, the saving, and the "this is uncompressed" verdict
    — wrong. Callers skip those assets instead of publishing a guess.
    """
    if is_indexed_format(fmt):
        return False
    if normalize_compression(fmt) in BYTES_PER_PIXEL:
        return True
    return bool(measured_kb and measured_kb > 0)


# ── VRAM estimator ────────────────────────────────────────────────────────────


# Plausibility window for a bytes-per-pixel figure derived from a client
# measurement: ASTC_12x12 is the thinnest real format at 0.111, RGBA8 the
# fattest common one at 4.0. Anything outside this is a bad measurement
# (wrong dimensions, a partially loaded asset, a streaming texture measured
# mid-eviction) and is discarded rather than trusted.
# Sanity band for a client-measured size, in bytes per pixel. It exists to
# reject a measurement that cannot be "bytes for these pixels" at all (a zero,
# or a client sending MB where KB was asked for), not to second-guess the
# engine's own accounting.
#
# The ceiling used to be 4.0 — one RGBA8 texel — which silently rejected every
# legitimate reading above it and fell back to the modelled 4.0. Real textures
# exceed it routinely: RGBAHalf is 8 B/px, RGBAFloat 16, and a Read/Write-
# enabled texture keeps a second CPU-side copy that Unity's
# Profiler.GetRuntimeMemorySizeLong counts (correctly — the project really is
# paying for it). Discarding those made the Core print a figure 43% below the
# engine's own, one column away from it in the panel.
_MIN_PLAUSIBLE_BPP: float = 0.1
_MAX_PLAUSIBLE_BPP: float = 32.0


def resolve_texture_bpp(
    fmt: str,
    width: int,
    height: int,
    with_mips: bool = True,
    measured_kb: float | None = None,
) -> float:
    """Bytes per pixel for *fmt*, falling back to the client's measurement.

    A mapped format always wins. Otherwise, if the caller supplied a size the
    client measured for the texture *at these dimensions*, back out the real
    bytes-per-pixel from it — that covers Unity's "Automatic" import setting,
    which is what the importer reports whenever a platform has no explicit
    override and which the Core cannot resolve on its own. Only if there is no
    usable measurement do we assume uncompressed RGBA8.

    Rules pricing a proposed resize should call this once with the asset's
    current dimensions and pass the result to ``estimate_texture_vram_mb`` as
    ``bpp_override`` for both the current and the proposed figure — deriving it
    again at the smaller size would inflate the bytes-per-pixel.
    """
    canonical = normalize_compression(fmt)
    bpp = BYTES_PER_PIXEL.get(canonical)
    if bpp is not None:
        return bpp

    if measured_kb and width > 0 and height > 0:
        pixels = width * height * (MIP_MULTIPLIER if with_mips else 1.0)
        derived = (measured_kb * 1024.0) / pixels
        if _MIN_PLAUSIBLE_BPP <= derived <= _MAX_PLAUSIBLE_BPP:
            _logger.debug(
                "Format %r unmapped — derived %.3f bytes/px from the client's "
                "%.1f KB measurement.",
                fmt,
                derived,
                measured_kb,
            )
            return derived
        _logger.warning(
            "Discarding the client's %.1f KB measurement for unmapped format "
            "%r at %dx%d — %.2f bytes/px is outside the plausible band "
            "[%.1f, %.1f]. The reported size will not match the client's.",
            measured_kb,
            fmt,
            width,
            height,
            derived,
            _MIN_PLAUSIBLE_BPP,
            _MAX_PLAUSIBLE_BPP,
        )

    # Nothing usable: assume uncompressed. That is the safe worst case, but it
    # over-estimates a compressed texture up to 8x, so leave a trace instead of
    # failing silently — a silent fallback here is what kept the Unity texture
    # sizes wrong across two separate rounds of this bug.
    _logger.warning(
        "VRAM estimate for unmapped texture format %r (canonical %r) with no "
        "usable size measurement — using the RGBA8 fallback, the figure may "
        "be too high.",
        fmt,
        canonical,
    )
    return BYTES_PER_PIXEL["RGBA8"]


def estimate_texture_vram_mb(
    width: int,
    height: int,
    fmt: str,
    with_mips: bool = True,
    bpp_override: float | None = None,
) -> float:
    """Estimate texture VRAM cost in megabytes.

    Args:
        width:        Texture width in pixels.
        height:       Texture height in pixels.
        fmt:          Format string — canonical (BC7, RGBA8, …) or UE5 TC_*.
        with_mips:    Include the full mip chain cost (default True).
        bpp_override: Bytes per pixel to use instead of looking *fmt* up, as
                      returned by ``resolve_texture_bpp``. Rules pricing a
                      resize resolve it once at the current dimensions and
                      reuse it for both figures.

    Returns:
        Estimated VRAM in MB, rounded to 2 decimal places.

    Example:
        >>> estimate_texture_vram_mb(4096, 4096, "BC7")
        21.33
    """
    bpp = (
        bpp_override
        if bpp_override is not None
        else resolve_texture_bpp(fmt, width, height, with_mips)
    )
    base_bytes = width * height * bpp
    total_bytes = base_bytes * MIP_MULTIPLIER if with_mips else base_bytes
    return round(total_bytes / BYTES_PER_MB, 2)


# ── Effective (engine-resident) texture size ──────────────────────────────────


def effective_texture_size(
    width: int, height: int, max_texture_size: int | None = 0
) -> tuple[int, int]:
    """Dimensions the engine actually uploads, after the import size cap.

    ``width``/``height`` are the *source* dimensions of the file on disk.
    Both engines let the importer clamp the resident texture below that:
    Unity's ``TextureImporterPlatformSettings.maxTextureSize`` and UE5's
    ``UTexture::MaxTextureSize`` (0 = uncapped in both). The GPU never sees
    anything larger, so every memory figure and every resize recommendation
    must be derived from the capped size — not from the source resolution.

    Reading the source instead was a live defect: a 4096 source with
    max_texture_size=2048 was reported as ~4096, priced 4x too high, and
    generated a "reduce it to 2048" recommendation for a texture that was
    already 2048 on the GPU.

    The cap applies to the long edge and preserves aspect ratio, matching
    both importers. Returns the input unchanged when there is no cap or the
    texture is already within it.
    """
    try:
        w = int(width or 0)
        h = int(height or 0)
        cap = int(max_texture_size or 0)
    except (TypeError, ValueError):
        return (0, 0)

    if w <= 0 or h <= 0:
        return (max(w, 0), max(h, 0))

    long_edge = max(w, h)
    if cap <= 0 or long_edge <= cap:
        return (w, h)

    scale = cap / long_edge
    return (max(1, int(round(w * scale))), max(1, int(round(h * scale))))


# Bytes per pixel at or above which a payload is an uncompressed 32-bit
# texture. Every block format tops out at 1.0 (BC7/BC3/ASTC_4x4) and the
# 16-bit uncompressed formats sit at 2.0, so 3.0 separates the classes with
# room for the rounding in a client's measurement.
_UNCOMPRESSED_BPP_FLOOR: float = 3.0


def is_effectively_uncompressed(asset: dict) -> bool:
    """True when the texture's resident payload is uncompressed 32-bit.

    The declared format answers this whenever it is one the Core maps. When
    it is not, the client's measurement still does: four bytes per pixel is
    uncompressed no matter what the importer setting happens to be called.

    That fallback is not an edge case. Unity's
    TextureImporterPlatformSettings.format reports "Automatic" for any
    platform without an explicit override — the default state on Standalone —
    so a plain format-string comparison made the single largest saving in the
    tool ("this is uncompressed, compress it") invisible on every Standalone
    scan, while the same texture on Android, where an override is normally
    set, reported the full saving. Same bytes, same texture, two answers.
    """
    fmt = asset.get("compression", "") or ""
    canonical = normalize_compression(fmt)
    mapped = BYTES_PER_PIXEL.get(canonical)
    if mapped is not None:
        return canonical == "RGBA8"

    measured_kb = asset.get("size_kb")
    if not measured_kb or is_indexed_format(fmt):
        return False

    width, height = effective_texture_size(
        asset.get("width", 0), asset.get("height", 0), asset.get("max_texture_size", 0)
    )
    if width <= 0 or height <= 0:
        return False

    mips = bool(asset.get("mips_enabled", True))
    pixels = width * height * (MIP_MULTIPLIER if mips else 1.0)
    return (measured_kb * 1024.0) / pixels >= _UNCOMPRESSED_BPP_FLOOR


def texture_asset_vram_mb(asset: dict) -> float:
    """Current resident VRAM of a texture asset, in MB — the one baseline.

    Every rule that prices a texture saving, and the orchestrator's
    per-asset savings clamp, resolve the asset's current cost through this
    function so they can never disagree with each other. It applies the
    import size cap (see effective_texture_size) and resolves
    bytes-per-pixel once at those dimensions.

    Returns 0.0 for an asset whose format cannot be priced honestly
    (indexed, or unmapped with no measurement) — callers treat that as
    "no baseline", not as "free".
    """
    fmt = asset.get("compression", "RGBA8") or "RGBA8"
    measured_kb = asset.get("size_kb")
    if not is_analyzable_texture_format(fmt, measured_kb):
        return 0.0

    width, height = effective_texture_size(
        asset.get("width", 0), asset.get("height", 0), asset.get("max_texture_size", 0)
    )
    if width <= 0 or height <= 0:
        return 0.0

    mips = bool(asset.get("mips_enabled", True))
    bpp = resolve_texture_bpp(fmt, width, height, mips, measured_kb)
    return estimate_texture_vram_mb(
        width, height, fmt, with_mips=mips, bpp_override=bpp
    )


# ── Mesh buffer estimator (Part-2 LG/LD rules) ────────────────────────────────

# Bytes per vertex for a typical static-mesh vertex buffer:
#   position float3 (12) + packed normal (4) + packed tangent (4)
#   + UV0 half2 (4) + vertex color (4) + a second UV half2 (4) = 32.
# A representative average; rules that need an exact per-channel figure (e.g.
# LG011's 8 B/vertex/UV-channel) compute it inline. Used for "excess geometry"
# VRAM estimates (LG001/LG002/LG005/LG009, LD005 trailing-LOD savings).
MESH_VERTEX_STRIDE_BYTES: int = 32

# Bytes per lightmap texel. UE5 stores each lightmap as a pair of low-bpp
# textures (AB coefficients); ~2 B/texel amortised is a defensible estimate.
LIGHTMAP_BYTES_PER_TEXEL: float = 2.0


def mesh_buffer_mb(vertex_count: int) -> float:
    """Estimate the vertex-buffer VRAM cost of *vertex_count* vertices in MB.

    Pure arithmetic (MESH_VERTEX_STRIDE_BYTES × verts). Callers pass a vertex
    delta (excess/duplicate/removed verts) to price a geometry saving.
    """
    if vertex_count <= 0:
        return 0.0
    return round(vertex_count * MESH_VERTEX_STRIDE_BYTES / BYTES_PER_MB, 2)


def lightmap_mb(resolution: int, with_mips: bool = True) -> float:
    """Estimate the VRAM cost of a square lightmap of edge *resolution* in MB.

    Monotonic in resolution² — used by LW006 to price the win from repacking a
    lightmap to a smaller resolution once packing efficiency improves.
    """
    if resolution <= 0:
        return 0.0
    base_bytes = resolution * resolution * LIGHTMAP_BYTES_PER_TEXEL
    total_bytes = base_bytes * MIP_MULTIPLIER if with_mips else base_bytes
    return round(total_bytes / BYTES_PER_MB, 2)
