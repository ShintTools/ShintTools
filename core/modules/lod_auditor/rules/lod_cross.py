# core/modules/lod_auditor/rules/lod_cross.py
#
# Cross-asset detection rules: LX001 – LX003
#
# Unlike LT/LM/LD rules which inspect a single asset, these scan the full
# audit batch to find waste that's only visible when looking at relationships
# between assets (dead references, duplicates, orphans).
#
# Signature is different from single-asset rules:
#   check_lxXXX(assets: list[dict]) -> list[Finding]
#
# The orchestrator handles them as a separate batch.

from collections import defaultdict
from typing import Any

from lod_auditor.config import load_profile
from lod_auditor.schema import Finding, Saving
from lod_auditor.vram_model import estimate_texture_vram_mb, normalize_compression

# Thresholds are loaded from YAML — see config/thresholds_default.yaml.
THRESHOLDS = load_profile()


# ── LX001 ─────────────────────────────────────────────────────────────────────


def check_lx001_dead_textures(assets: list[dict]) -> list[Finding]:
    """LX001: Texture asset not referenced by any material in the batch.

    The plugin populates ``referenced_by_materials`` per texture. A zero
    means the texture is shipped but never sampled — pure VRAM waste.
    """
    findings: list[Finding] = []

    for asset in assets:
        if asset.get("asset_type") not in (
            "Texture2D",
            "Texture",
            "Texture2DArray",
            "TextureCube",
            "VolumeTexture",
        ):
            continue
        refs: int = asset.get("referenced_by_materials", -1)
        # -1 sentinel: plugin didn't compute references → skip rather than
        # firing on every texture in the batch.
        if refs != 0:
            continue

        width: int = asset.get("width", 0)
        height: int = asset.get("height", 0)
        compression_raw: str = asset.get("compression", "RGBA8")
        compression: str = normalize_compression(compression_raw)
        mips_enabled: bool = asset.get("mips_enabled", True)
        wasted_vram: float = estimate_texture_vram_mb(
            width, height, compression, with_mips=mips_enabled
        )

        findings.append(
            Finding(
                asset_path=asset["asset_path"],
                rule_id="LX001",
                category="Texture",
                severity="warning",
                message=(
                    f"Texture is never sampled by any material in the project. "
                    f"It still ships with the build and wastes {wasted_vram} MB."
                ),
                current={
                    "referenced_by_materials": 0,
                    "resident_vram_mb": wasted_vram,
                },
                recommended={"referenced_by_materials": ">=1 or delete"},
                estimated_saving=Saving(vram_mb=wasted_vram, shader_instructions=0),
                auto_fixable=False,
                guidance=(
                    "Confirm the texture isn't loaded dynamically by Blueprint "
                    "or C++ before deleting. If it's dynamic-only, mark it "
                    "explicitly with the 'NeverStream' or 'Editor' lod_group."
                ),
            )
        )
    return findings


# ── LX002 ─────────────────────────────────────────────────────────────────────


def check_lx002_dead_materials(assets: list[dict]) -> list[Finding]:
    """LX002: Material/MaterialInstance assigned to zero primitives.

    The plugin populates ``used_by_primitives`` per material. A zero means
    the asset is loaded into memory but never rendered.
    """
    findings: list[Finding] = []

    for asset in assets:
        if asset.get("asset_type") not in (
            "Material",
            "MaterialInstance",
            "MaterialInstanceConstant",
            "MaterialInstanceDynamic",
        ):
            continue
        used: int = asset.get("used_by_primitives", -1)
        if used != 0:
            continue

        findings.append(
            Finding(
                asset_path=asset["asset_path"],
                rule_id="LX002",
                category="Material",
                severity="info",
                message=(
                    "Material is not assigned to any primitive in the project. "
                    "It still cooks into the build and warms the shader cache."
                ),
                current={"used_by_primitives": 0},
                recommended={"used_by_primitives": ">=1 or delete"},
                estimated_saving=Saving(vram_mb=0.0, shader_instructions=0),
                auto_fixable=False,
                guidance=(
                    "Delete the material if obsolete, or convert it to a "
                    "Material Function if it's a reusable building block."
                ),
            )
        )
    return findings


# ── LX003 ─────────────────────────────────────────────────────────────────────


def check_lx003_duplicate_meshes(assets: list[dict]) -> list[Finding]:
    """LX003: Two or more meshes share an identical content hash.

    Requires the plugin to compute a ``content_hash`` per StaticMesh
    (e.g. SHA256 of vertex+index+UV buffers). Without the hash we skip
    silently — guessing duplicates from path/name is unreliable.
    """
    by_hash: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for asset in assets:
        if asset.get("asset_type") not in ("StaticMesh", "SkeletalMesh", "Mesh"):
            continue
        content_hash: str = asset.get("content_hash", "")
        if not content_hash:
            continue
        by_hash[content_hash].append(asset)

    findings: list[Finding] = []
    min_size_kb: float = THRESHOLDS["LX003_MIN_DUPLICATE_SIZE_KB"]

    for content_hash, duplicates in by_hash.items():
        if len(duplicates) < 2:
            continue

        # Sort so the "kept" asset is the alphabetically-first path.
        # Plugin can override this with a user-facing picker later.
        duplicates.sort(key=lambda a: a["asset_path"])
        keeper = duplicates[0]
        copies = duplicates[1:]

        single_size_kb: float = float(keeper.get("size_kb", 0.0))
        if single_size_kb < min_size_kb:
            continue

        total_saving_kb: float = single_size_kb * len(copies)
        total_saving_mb: float = round(total_saving_kb / 1024.0, 2)

        for copy in copies:
            findings.append(
                Finding(
                    asset_path=copy["asset_path"],
                    rule_id="LX003",
                    category="Mesh",
                    severity="info",
                    message=(
                        f"Duplicate of {keeper['asset_path']} "
                        f"(identical content hash). "
                        f"Removing this copy saves ~{total_saving_mb} MB."
                    ),
                    current={
                        "content_hash": content_hash,
                        "size_kb": single_size_kb,
                        "duplicate_of": keeper["asset_path"],
                    },
                    recommended={
                        "action": "redirector_to_keeper",
                        "keeper": keeper["asset_path"],
                    },
                    estimated_saving=Saving(
                        vram_mb=round(single_size_kb / 1024.0, 2),
                        shader_instructions=0,
                    ),
                    auto_fixable=False,
                    guidance=(
                        f"Replace references to this asset with "
                        f"{keeper['asset_path']} and delete this copy, "
                        "or merge into a Redirector so existing links keep "
                        "working."
                    ),
                )
            )
    return findings
