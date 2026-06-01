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
    bpp = BYTES_PER_PIXEL.get(canonical, BYTES_PER_PIXEL["RGBA8"])
    base_bytes = width * height * bpp
    total_bytes = base_bytes * MIP_MULTIPLIER if with_mips else base_bytes
    return round(total_bytes / BYTES_PER_MB, 2)
