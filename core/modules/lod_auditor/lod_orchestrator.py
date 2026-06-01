# core/modules/lod_auditor/lod_orchestrator.py
#
# Entry point for the LOD Auditor core engine.
#
# audit_assets() receives the raw asset list from the plugin, dispatches
# each asset to the correct rule set based on asset_type, applies the
# tier filter, and returns a fully assembled AuditResponse.

from typing import Any

from lod_auditor.rules.lod_materials import check_lm001, check_lm002, check_lm003
from lod_auditor.rules.lod_meshes import check_ld001, check_ld002, check_ld003
from lod_auditor.rules.lod_textures import (
    check_lt001,
    check_lt002,
    check_lt003,
    check_lt004,
    check_lt005,
)
from lod_auditor.schema import AuditResponse, AuditSummary, Finding

# ── Rule registries ───────────────────────────────────────────────────────────
#
# Ordered lists so findings always appear in the same sequence regardless
# of dict iteration order.  Add new rules by appending here.

TEXTURE_RULES = [check_lt001, check_lt002, check_lt003, check_lt004, check_lt005]
MATERIAL_RULES = [check_lm001, check_lm002, check_lm003]
MESH_RULES = [check_ld001, check_ld002, check_ld003]

# ── Asset-type routing tables ─────────────────────────────────────────────────

_TEXTURE_ASSET_TYPES: frozenset[str] = frozenset(
    {"Texture2D", "Texture", "Texture2DArray", "TextureCube", "VolumeTexture"}
)
_MATERIAL_ASSET_TYPES: frozenset[str] = frozenset(
    {
        "Material",
        "MaterialInstance",
        "MaterialInstanceConstant",
        "MaterialInstanceDynamic",
    }
)
_MESH_ASSET_TYPES: frozenset[str] = frozenset({"StaticMesh", "SkeletalMesh", "Mesh"})


# ── Internal helpers ──────────────────────────────────────────────────────────


def _dispatch_asset(asset: dict[str, Any]) -> list[Finding]:
    """Run all rules applicable to *asset* and return their findings."""
    asset_type: str = asset.get("asset_type", "")

    if asset_type in _TEXTURE_ASSET_TYPES:
        rules = TEXTURE_RULES
    elif asset_type in _MATERIAL_ASSET_TYPES:
        rules = MATERIAL_RULES
    elif asset_type in _MESH_ASSET_TYPES:
        rules = MESH_RULES
    else:
        return []

    findings: list[Finding] = []
    for check_fn in rules:
        result = check_fn(asset)
        if result is not None:
            findings.append(result)

    return findings


def _compute_summary(findings: list[Finding], assets_audited: int) -> AuditSummary:
    """Aggregate per-finding numbers into a top-level summary."""
    total_vram_saved: float = sum(f.estimated_saving.vram_mb for f in findings)
    total_instructions_saved: int = sum(
        f.estimated_saving.shader_instructions for f in findings
    )
    auto_fixable_count: int = sum(1 for f in findings if f.auto_fixable)

    return AuditSummary(
        assets_audited=assets_audited,
        issues_found=len(findings),
        auto_fixable=auto_fixable_count,
        estimated_vram_saved_mb=round(total_vram_saved, 2),
        estimated_shader_instructions_saved=total_instructions_saved,
    )


# ── Public API ────────────────────────────────────────────────────────────────


def audit_assets(
    assets: list[dict[str, Any]],
    allowed_rules: frozenset[str] | None = None,
) -> AuditResponse:
    """Run all LOD rules on a list of raw asset dicts.

    Args:
        assets:        Asset metadata dicts as received from the plugin.
        allowed_rules: Frozenset of rule IDs the client's tier may see.
                       ``None`` means all rules are visible (Indie tier).

    Returns:
        AuditResponse with a summary and the full list of findings.
    """
    all_findings: list[Finding] = []

    for asset in assets:
        findings = _dispatch_asset(asset)

        if allowed_rules is not None:
            findings = [f for f in findings if f.rule_id in allowed_rules]

        all_findings.extend(findings)

    summary = _compute_summary(all_findings, len(assets))
    return AuditResponse(summary=summary, results=all_findings)
