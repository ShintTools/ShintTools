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


def normalize_compression(raw: str) -> str:
    """Return the canonical format name for *raw*.

    Accepts UE5 TC_* names, Unity equivalents, or already-canonical
    BC*/RGBA8 strings.  Unknown values are returned unchanged so the
    caller can decide whether to treat them as RGBA8 or skip them.
    """
    return _FORMAT_ALIASES.get(raw, raw)


# ── VRAM estimator ────────────────────────────────────────────────────────────


def estimate_texture_vram_mb(
    width: int,
    height: int,
    fmt: str,
    with_mips: bool = True,
) -> float:
    """Estimate texture VRAM cost in megabytes.

    Args:
        width:     Texture width in pixels.
        height:    Texture height in pixels.
        fmt:       Format string — canonical (BC7, RGBA8, …) or UE5 TC_*.
        with_mips: Include the full mip chain cost (default True).

    Returns:
        Estimated VRAM in MB, rounded to 2 decimal places.

    Example:
        >>> estimate_texture_vram_mb(4096, 4096, "BC7")
        21.33
    """
    canonical = normalize_compression(fmt)
    bpp = BYTES_PER_PIXEL.get(canonical)
    if bpp is None:
        # Unrecognised format — fall back to uncompressed RGBA8. That is the
        # safe worst case, but it over-estimates a compressed texture up to 8×,
        # so leave a trace instead of failing silently. "Automatic" arrives
        # here whenever a Unity client reports the importer's platform setting
        # without an explicit per-platform override; the client should send the
        # resolved TextureFormat instead.
        _logger.warning(
            "VRAM estimate for unmapped texture format %r (canonical %r) — "
            "using the RGBA8 fallback, the figure may be too high.",
            fmt,
            canonical,
        )
        bpp = BYTES_PER_PIXEL["RGBA8"]
    base_bytes = width * height * bpp
    total_bytes = base_bytes * MIP_MULTIPLIER if with_mips else base_bytes
    return round(total_bytes / BYTES_PER_MB, 2)


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
