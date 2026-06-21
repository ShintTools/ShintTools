# core/modules/lod_auditor/rules/lod_animations.py
#
# Animation LOD rules: LA001 – LA003
#
# Each rule is a pure function:
#   check_laXXX(asset: dict) -> Finding | None

from lod_auditor.config import load_profile
from lod_auditor.guidance import guidance_for
from lod_auditor.schema import Finding, Saving

# Thresholds are loaded from YAML — see config/thresholds_default.yaml.
THRESHOLDS = load_profile()

_VALID_COMPRESSION_SOURCES: frozenset[str] = frozenset(
    {"Mocap", "Keyframed", "Procedural", "Additive"}
)


# ── LA001 ─────────────────────────────────────────────────────────────────────


def check_la001(asset: dict, engine: str = "unreal") -> Finding | None:
    """LA001: Animation Sequence compression not optimal for its source type."""
    source: str = asset.get("anim_source", "")
    compression: str = asset.get("compression_format", "")

    if source not in _VALID_COMPRESSION_SOURCES:
        return None

    expected: str = THRESHOLDS["LA001_EXPECTED_COMPRESSION"][source]

    if compression == expected:
        return None

    raw_size_kb: float = float(asset.get("raw_size_kb", 0.0))
    compressed_size_kb: float = float(asset.get("compressed_size_kb", raw_size_kb))
    # Heuristic: ACL_Custom typically reduces another 40 % over Automatic;
    # if the asset is uncompressed we approximate against raw_size_kb.
    estimated_saving_kb: float = round(compressed_size_kb * 0.4, 2)
    estimated_saving_mb: float = round(estimated_saving_kb / 1024.0, 2)

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LA001",
        category="Animation",
        severity="warning",
        message=(
            f"'{source}' animation uses '{compression}' — "
            f"{expected} typically saves ~40 % on disk "
            f"(estimated {estimated_saving_mb} MB)."
        ),
        current={"compression_format": compression, "size_kb": compressed_size_kb},
        recommended={"compression_format": expected},
        estimated_saving=Saving(vram_mb=estimated_saving_mb, shader_instructions=0),
        auto_fixable=True,
        guidance=None,
    )


# ── LA002 ─────────────────────────────────────────────────────────────────────


def check_la002(asset: dict, engine: str = "unreal") -> Finding | None:
    """LA002: Skeletal Mesh has no LOD chain (mirror of LD001 for skeletal)."""
    if asset.get("asset_type") != "SkeletalMesh":
        return None

    lod_count: int = asset.get("lod_count", 1)
    if lod_count >= THRESHOLDS["LA002_MIN_LOD_COUNT"]:
        return None

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LA002",
        category="Animation",
        severity="warning",
        message=(
            "SkeletalMesh has no LOD chain. "
            "Full poly count + bone count renders at every distance — "
            "skeletal evaluation is the most expensive per-frame cost in UE5."
        ),
        current={"lod_count": lod_count},
        recommended={"lod_count": ">= 2"},
        estimated_saving=Saving(vram_mb=0.0, shader_instructions=0),
        auto_fixable=True,
        guidance=None,
    )


# ── LA003 ─────────────────────────────────────────────────────────────────────


def check_la003(asset: dict, engine: str = "unreal") -> Finding | None:
    """LA003: Animation has excessive curve count or keyframe density."""
    if asset.get("asset_type") != "AnimSequence":
        return None

    curve_count: int = asset.get("curve_count", 0)
    key_count: int = asset.get("key_count", 0)
    duration_sec: float = float(asset.get("duration_sec", 1.0))

    violations: list[str] = []
    if curve_count > THRESHOLDS["LA003_MAX_CURVES"]:
        violations.append(
            f"{curve_count} curves (budget: {THRESHOLDS['LA003_MAX_CURVES']})"
        )

    keys_per_sec: float = key_count / max(duration_sec, 0.01)
    if keys_per_sec > THRESHOLDS["LA003_MAX_KEYS_PER_SECOND"]:
        violations.append(
            f"{keys_per_sec:.0f} keys/sec "
            f"(budget: {THRESHOLDS['LA003_MAX_KEYS_PER_SECOND']})"
        )

    if not violations:
        return None

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LA003",
        category="Animation",
        severity="info",
        message=(
            "Animation has excessive data density: "
            + "; ".join(violations)
            + ". Often the source FBX captured at 60+ fps when 30 is enough."
        ),
        current={
            "curve_count": curve_count,
            "key_count": key_count,
            "duration_sec": duration_sec,
        },
        recommended={
            "curve_count": f"<= {THRESHOLDS['LA003_MAX_CURVES']}",
            "keys_per_second": f"<= {THRESHOLDS['LA003_MAX_KEYS_PER_SECOND']}",
        },
        estimated_saving=Saving(vram_mb=0.0, shader_instructions=0),
        auto_fixable=False,
        guidance=guidance_for("LA003", engine),
    )
