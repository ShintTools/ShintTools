# core/modules/lod_auditor/rules/lod_rendering.py
#
# Rendering-cost rules: LR001 – LR008  (TDD Part 2 §18.3)
#
#   check_lrXXX(asset, engine="unreal", thresholds=None) -> Finding | None
#
# Validate blend-mode / pipeline cost interactions that the LM instruction
# budgets alone don't see. Category "Material". All high confidence; every
# recommended dict carries a one-line cost rationale (the primary feeder for
# bounded LLM enrichment, since the fix is architectural, not a property write).

from lod_auditor.config import load_profile
from lod_auditor.guidance import guidance_for
from lod_auditor.schema import Finding, Saving

THRESHOLDS = load_profile()


def _prims(asset: dict) -> int:
    """used_by_primitives, treating the -1 'not computed' sentinel as 0."""
    n = int(asset.get("used_by_primitives", -1))
    return n if n >= 0 else 0


# UE5-only concepts. Unity has no Material Instance, no material usage flags,
# no Material Layers and no Runtime Virtual Texture, so these rules describe
# machinery that does not exist there. They stayed quiet on Unity only because
# the collector sent none of their inputs — an accident, not a decision: the
# moment a Unity payload carries used_by_primitives (which the collector spec
# now asks for), LM003 would start telling Unity users to convert a material
# into an Unreal Material Instance. Gate on the concept, not on the data.
def _unreal_only(engine: str) -> bool:
    return engine.strip().lower() not in {"unity"}


def _rec(recommended: dict, rationale: str) -> dict:
    recommended["rationale"] = rationale
    recommended["confidence"] = "high"
    return recommended


# ── LR001 ─────────────────────────────────────────────────────────────────────


def check_lr001(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LR001: Opaque material reads scene color/depth, forfeiting early-Z."""
    if asset.get("blend_mode") != "Opaque":
        return None
    if not (asset.get("uses_scene_color") or asset.get("uses_depth_read")):
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LR001",
        category="Material",
        severity="warning",
        message=(
            "Opaque material samples scene color/depth — it must run after the "
            "scene-color resolve, breaking early-Z for everything behind it."
        ),
        current={
            "blend_mode": "Opaque",
            "uses_scene_color": bool(asset.get("uses_scene_color")),
            "uses_depth_read": bool(asset.get("uses_depth_read")),
        },
        recommended=_rec(
            {"hint": "move to a translucent pass or remove the scene read"},
            "opaque scene reads defeat early-Z",
        ),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LR001", engine),
    )


# ── LR002 ─────────────────────────────────────────────────────────────────────


def check_lr002(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LR002: Widely-used Masked material on mobile (HZB / early-Z cost on TBDR)."""
    T = thresholds if thresholds is not None else THRESHOLDS
    if T.get("profile") != "mobile":
        return None  # masked cost only material on tile-based deferred GPUs
    if asset.get("blend_mode") != "Masked" or _prims(asset) <= T["LR002_MIN_PRIMS"]:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LR002",
        category="Material",
        severity="warning",
        message=(
            f"Masked material used by {_prims(asset)} primitives on mobile — "
            "alpha-test defeats the TBDR early-Z / HZB fast path."
        ),
        current={"blend_mode": "Masked", "used_by_primitives": _prims(asset)},
        recommended=_rec(
            {"hint": "use dithered opaque or reduce masked coverage"},
            "masked breaks TBDR early-Z",
        ),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LR002", engine),
    )


# ── LR003 ─────────────────────────────────────────────────────────────────────


def check_lr003(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LR003: Translucent material reads depth (per-pixel fetch × overdraw)."""
    T = thresholds if thresholds is not None else THRESHOLDS
    if asset.get("blend_mode") != "Translucent" or not asset.get("uses_depth_read"):
        return None
    budget = T["LM001_BUDGET_BY_BLEND_MODE"].get(
        "Translucent", T["LM001_DEFAULT_BUDGET"]
    )
    instructions = int(asset.get("instruction_count", 0) or 0)
    over_budget = instructions > budget
    severity = "error" if over_budget else "warning"
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LR003",
        category="Material",
        severity=severity,
        message=(
            "Translucent material fetches scene depth per pixel"
            + (f" and is over the {budget}-instruction budget" if over_budget else "")
            + " — cost multiplies with overdraw."
        ),
        current={"blend_mode": "Translucent", "instruction_count": instructions},
        recommended=_rec(
            {"hint": "remove the depth read or split the effect"},
            "per-pixel depth fetch scales with overdraw",
        ),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LR003", engine),
    )


# ── LR004 ─────────────────────────────────────────────────────────────────────


def check_lr004(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LR004: Additive material on many primitives (fill-rate stacking)."""
    T = thresholds if thresholds is not None else THRESHOLDS
    if asset.get("blend_mode") != "Additive" or _prims(asset) <= T["LR004_MAX_PRIMS"]:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LR004",
        category="Material",
        severity="info",
        message=(
            f"Additive material on {_prims(asset)} primitives — overlapping sheets "
            "stack fill-rate cost (classic VFX overdraw)."
        ),
        current={"blend_mode": "Additive", "used_by_primitives": _prims(asset)},
        recommended=_rec(
            {"hint": "reduce overlap / particle count"},
            "additive overdraw is fill-rate bound",
        ),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LR004", engine),
    )


# ── LR005 ─────────────────────────────────────────────────────────────────────


def check_lr005(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LR005: Expensive decal material (DBuffer decals pay per covered pixel)."""
    T = thresholds if thresholds is not None else THRESHOLDS
    if not asset.get("is_decal"):
        return None
    instructions = int(asset.get("instruction_count", 0) or 0)
    if instructions <= T["LR005_MAX_INSTRUCTIONS"]:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LR005",
        category="Material",
        severity="warning",
        message=(
            f"Decal material with {instructions} instructions (budget "
            f"{T['LR005_MAX_INSTRUCTIONS']}) — DBuffer decals pay per covered pixel."
        ),
        current={"is_decal": True, "instruction_count": instructions},
        recommended=_rec(
            {"instruction_count": f"<= {T['LR005_MAX_INSTRUCTIONS']}"},
            "decal cost is per covered pixel",
        ),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LR005", engine),
    )


# ── LR006 ─────────────────────────────────────────────────────────────────────


def check_lr006(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LR006: Two-sided opaque material (doubles rasteriser work)."""
    T = thresholds if thresholds is not None else THRESHOLDS
    if not (asset.get("two_sided") and asset.get("blend_mode") == "Opaque"):
        return None
    if _prims(asset) <= T["LR006_MIN_PRIMS"]:
        return None
    # Auto-fix (clear two_sided) is only safe when the referencer scan proved
    # there are no foliage / thin-geo consumers. Unknown => don't auto-fix.
    thin = asset.get("has_thin_geo_consumers")
    fixable = thin is False
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LR006",
        category="Material",
        severity="info",
        message=(
            "Two-sided opaque material doubles rasteriser work — often a foliage "
            "import artefact left on solid geometry."
        ),
        current={"two_sided": True, "blend_mode": "Opaque"},
        recommended=_rec(
            {"two_sided": False}, "two-sided doubles rasteriser invocations"
        ),
        estimated_saving=Saving(),
        auto_fixable=fixable,
        guidance=guidance_for("LR006", engine),
    )


# ── LR007 ─────────────────────────────────────────────────────────────────────


def check_lr007(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LR007: World-Position-Offset on a heavy or Nanite mesh referencer."""
    if not _unreal_only(engine):
        return None
    T = thresholds if thresholds is not None else THRESHOLDS
    if not asset.get("uses_wpo"):
        return None
    worst_verts = int(asset.get("max_referencer_vertex_count", 0) or 0)
    nanite_ref = bool(asset.get("has_nanite_referencer"))
    if worst_verts <= T["LR007_MIN_VERTS"] and not nanite_ref:
        return None
    reason = (
        "a Nanite mesh (WPO disables the Nanite fast path)"
        if nanite_ref
        else f"a {worst_verts:,}-vertex mesh"
    )
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LR007",
        category="Material",
        severity="warning",
        message=f"World Position Offset drives {reason} — heavy per-vertex cost.",
        current={"uses_wpo": True, "max_referencer_vertex_count": worst_verts},
        recommended=_rec(
            {"hint": "limit WPO to low-poly meshes / bound the displacement"},
            "WPO runs per vertex and disables Nanite",
        ),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LR007", engine),
    )


# ── LR008 ─────────────────────────────────────────────────────────────────────


def check_lr008(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LR008: Pixel Depth Offset disables early-Z for every covered pixel."""
    if not _unreal_only(engine):
        return None
    T = thresholds if thresholds is not None else THRESHOLDS
    if not asset.get("uses_pdo") or _prims(asset) <= T["LR008_MIN_PRIMS"]:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LR008",
        category="Material",
        severity="warning",
        message=(
            f"Pixel Depth Offset on a material used by {_prims(asset)} primitives — "
            "disables early-Z for every covered pixel."
        ),
        current={"uses_pdo": True, "used_by_primitives": _prims(asset)},
        recommended=_rec(
            {"hint": "limit PDO usage / covered area"},
            "PDO forfeits early-Z on covered pixels",
        ),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LR008", engine),
    )
