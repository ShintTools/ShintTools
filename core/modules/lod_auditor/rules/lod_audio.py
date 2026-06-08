# core/modules/lod_auditor/rules/lod_audio.py
#
# Audio LOD rules: LU001 – LU002
#
# Targets SoundWave (UE5) and AudioClip (Unity). Both engines store
# uncompressed PCM by default — a quick win is enabling OGG/Vorbis
# encoding on long clips and streaming on anything > 5 s.

from lod_auditor.config import load_profile
from lod_auditor.schema import Finding, Saving

THRESHOLDS = load_profile()

# Defaults if the loaded profile doesn't define these. SoundWave and
# AudioClip both share the same threshold space because the underlying
# decode cost is identical.
_DEFAULT_COMPRESSION_MIN_DURATION_SEC = 2.0
_DEFAULT_STREAMING_MIN_DURATION_SEC = 5.0

_PCM_FORMATS: frozenset[str] = frozenset({"PCM", "Uncompressed", "WAV"})
_COMPRESSED_FORMATS: frozenset[str] = frozenset({"OGG", "Vorbis", "ADPCM", "Opus"})


# ── LU001 ─────────────────────────────────────────────────────────────────────


def check_lu001(asset: dict) -> Finding | None:
    """LU001: Long audio clip stored as uncompressed PCM."""
    if asset.get("asset_type") not in ("SoundWave", "AudioClip", "Sound"):
        return None

    duration_sec: float = float(asset.get("duration_sec", 0.0))
    compression: str = asset.get("compression_format", "")
    min_duration = THRESHOLDS.get(
        "LU001_COMPRESSION_MIN_DURATION_SEC",
        _DEFAULT_COMPRESSION_MIN_DURATION_SEC,
    )

    if duration_sec < min_duration:
        return None
    if compression not in _PCM_FORMATS:
        return None

    raw_size_mb: float = float(asset.get("size_mb", 0.0))
    # OGG Vorbis at quality 4 typically lands ~12 % of uncompressed PCM.
    estimated_saving_mb: float = round(raw_size_mb * 0.88, 2)

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LU001",
        category="Audio",
        severity="warning",
        message=(
            f"{duration_sec:.1f} s clip is stored as {compression} "
            f"({raw_size_mb} MB). OGG/Vorbis would save ~{estimated_saving_mb} MB."
        ),
        current={"compression_format": compression, "size_mb": raw_size_mb},
        recommended={"compression_format": "OGG"},
        estimated_saving=Saving(vram_mb=estimated_saving_mb, shader_instructions=0),
        auto_fixable=True,
        guidance=None,
    )


# ── LU002 ─────────────────────────────────────────────────────────────────────


def check_lu002(asset: dict) -> Finding | None:
    """LU002: Long audio clip loaded entirely into memory (streaming disabled)."""
    if asset.get("asset_type") not in ("SoundWave", "AudioClip", "Sound"):
        return None

    duration_sec: float = float(asset.get("duration_sec", 0.0))
    streaming: bool = asset.get("streaming", False)
    min_duration = THRESHOLDS.get(
        "LU002_STREAMING_MIN_DURATION_SEC",
        _DEFAULT_STREAMING_MIN_DURATION_SEC,
    )

    if duration_sec < min_duration or streaming:
        return None

    raw_size_mb: float = float(asset.get("size_mb", 0.0))

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LU002",
        category="Audio",
        severity="info",
        message=(
            f"{duration_sec:.1f} s clip has streaming disabled — "
            f"the full {raw_size_mb} MB stays resident in RAM. "
            "Streaming decodes from disk in chunks for clips longer than 5 s."
        ),
        current={"streaming": False, "resident_size_mb": raw_size_mb},
        recommended={"streaming": True},
        estimated_saving=Saving(vram_mb=0.0, shader_instructions=0),
        auto_fixable=True,
        guidance=None,
    )
