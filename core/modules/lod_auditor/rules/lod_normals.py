# core/modules/lod_auditor/rules/lod_normals.py
#
# Normal & tangent rules: LN001 – LN007  (TDD Part 2 §16)
#
#   check_lnXXX(asset, engine="unreal", thresholds=None) -> Finding | None
#
# All rules read asset["normal_stats"] (schema.NormalStats) and abstain when it
# is None. Category "Mesh".

from lod_auditor.config import load_profile
from lod_auditor.guidance import guidance_for
from lod_auditor.schema import Finding, Saving

THRESHOLDS = load_profile()


def _ns(asset: dict) -> dict | None:
    ns = asset.get("normal_stats")
    if ns is None:
        return None
    return ns if isinstance(ns, dict) else ns.model_dump()


def _conf(recommended: dict, level: str) -> dict:
    recommended["confidence"] = level
    return recommended


# ── LN001 ─────────────────────────────────────────────────────────────────────


def check_ln001(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LN001: Mesh imported without normals and normal recompute is off (faceted)."""
    ns = _ns(asset)
    if ns is None:
        return None
    if ns.get("has_normals", True) or ns.get("recompute_normals", False):
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LN001",
        category="Mesh",
        severity="error",
        message=(
            "Mesh has no normals and normal recompute is disabled — it will be "
            "lit as faceted garbage."
        ),
        current={"has_normals": False, "recompute_normals": False},
        recommended=_conf({"recompute_normals": True}, "high"),
        estimated_saving=Saving(),
        auto_fixable=True,
        guidance=guidance_for("LN001", engine),
    )


# ── LN002 ─────────────────────────────────────────────────────────────────────


def check_ln002(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LN002: Invalid (zero or NaN) normals in the mesh."""
    T = thresholds if thresholds is not None else THRESHOLDS
    ns = _ns(asset)
    if ns is None:
        return None
    invalid = int(ns.get("zero_normal_count", 0)) + int(ns.get("nan_normal_count", 0))
    if invalid <= 0:
        return None
    verts = int(asset.get("vertex_count", 0) or 0)
    severity = (
        "error" if (verts and invalid > verts * T["LN002_ERROR_RATIO"]) else "warning"
    )
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LN002",
        category="Mesh",
        severity=severity,
        message=(
            f"{invalid:,} invalid (zero-length or NaN) normals — they produce "
            "black shading artifacts and break tangent basis computation."
        ),
        current={
            "zero_normal_count": int(ns.get("zero_normal_count", 0)),
            "nan_normal_count": int(ns.get("nan_normal_count", 0)),
        },
        recommended=_conf({"invalid_normals": 0, "recompute_normals": True}, "high"),
        estimated_saving=Saving(),
        auto_fixable=True,
        guidance=guidance_for("LN002", engine),
    )


# ── LN003 ─────────────────────────────────────────────────────────────────────


def check_ln003(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LN003: Missing tangents on a normal-mapped mesh, or a MikkTSpace mismatch."""
    ns = _ns(asset)
    if ns is None:
        return None
    no_tangents = not ns.get("has_tangents", True) and bool(
        asset.get("has_normal_mapped_material")
    )
    legacy = ns.get("tangent_space", "") == "legacy"
    if not (no_tangents or legacy):
        return None
    reason = (
        "no tangents on a normal-mapped mesh"
        if no_tangents
        else "legacy tangent basis while the DCC baked MikkTSpace maps"
    )
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LN003",
        category="Mesh",
        severity="warning",
        message=f"Tangent problem: {reason} — normal maps will read wrong.",
        current={
            "has_tangents": ns.get("has_tangents", True),
            "tangent_space": ns.get("tangent_space", ""),
        },
        recommended=_conf({"recompute_tangents": True, "use_mikktspace": True}, "high"),
        estimated_saving=Saving(),
        auto_fixable=True,
        guidance=guidance_for("LN003", engine),
    )


# ── LN004 ─────────────────────────────────────────────────────────────────────


def check_ln004(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LN004: Hard-edge ratio so high the vertex buffer balloons."""
    T = thresholds if thresholds is not None else THRESHOLDS
    ns = _ns(asset)
    if ns is None:
        return None
    ratio = float(ns.get("hard_edge_ratio", 0.0))
    verts = int(asset.get("vertex_count", 0) or 0)
    if ratio <= T["LN004_MAX_RATIO"] or verts <= T["LN004_MIN_VERTS"]:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LN004",
        category="Mesh",
        severity="info",
        message=(
            f"{ratio * 100:.0f}% of edges are hard — each hard edge splits "
            "vertices, inflating the buffer; usually an import smoothing-angle "
            "accident."
        ),
        current={"hard_edge_ratio": round(ratio, 2)},
        recommended=_conf({"hard_edge_ratio": f"<= {T['LN004_MAX_RATIO']}"}, "medium"),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LN004", engine),
    )


# ── LN005 ─────────────────────────────────────────────────────────────────────


def check_ln005(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LN005: Single smoothing group on a hard-surface mesh (shading blobs)."""
    T = thresholds if thresholds is not None else THRESHOLDS
    ns = _ns(asset)
    if ns is None:
        return None
    groups = int(ns.get("smoothing_group_count", 0))
    hard = float(ns.get("hard_edge_ratio", 1.0))
    tris = int(asset.get("triangle_count", 0) or 0)
    if not (groups == 1 and hard < 0.01 and tris > T["LN005_MIN_TRIS"]):
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LN005",
        category="Mesh",
        severity="info",
        message=(
            "One smoothing group with no hard edges on a dense mesh — hard-surface "
            "detail will shade as rounded blobs."
        ),
        current={"smoothing_group_count": 1, "hard_edge_ratio": round(hard, 3)},
        recommended=_conf({"hint": "author smoothing groups / hard edges"}, "low"),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LN005", engine),
    )


# ── LN006 ─────────────────────────────────────────────────────────────────────


def check_ln006(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LN006: Normal recompute enabled on a mesh with valid authored normals."""
    ns = _ns(asset)
    if ns is None:
        return None
    if not (
        ns.get("recompute_normals", False)
        and ns.get("has_normals", True)
        and int(ns.get("zero_normal_count", 0)) == 0
    ):
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LN006",
        category="Mesh",
        severity="info",
        message=(
            "Normal recompute is on but the source has valid authored normals — "
            "the DCC's shading intent is being silently discarded."
        ),
        current={"recompute_normals": True, "has_normals": True},
        recommended=_conf({"recompute_normals": False}, "high"),
        estimated_saving=Saving(),
        auto_fixable=True,
        guidance=guidance_for("LN006", engine),
    )


# ── LN007 ─────────────────────────────────────────────────────────────────────
#
# ``mirrored_tangent_ratio`` ships in NormalStats and Unity's mesh scanner
# sends it today, but no rule read it until now. Engine-neutral: the risk
# (tangent.w-blind shaders showing a lighting seam along a mirrored UV shell)
# applies equally to any engine that reports the stat.


def check_ln007(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LN007: High mirrored-tangent ratio risks a lighting seam at the mirror line."""
    T = thresholds if thresholds is not None else THRESHOLDS
    ns = _ns(asset)
    if ns is None:
        return None
    if not ns.get("has_tangents", True):
        return None  # LN003 owns "no tangents at all"
    ratio = float(ns.get("mirrored_tangent_ratio", 0.0))
    if ratio <= T["LN007_MAX_MIRRORED_RATIO"]:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LN007",
        category="Mesh",
        severity="info",
        message=(
            f"{ratio * 100:.0f}% of tangents are mirrored (UV-mirrored shells) — "
            "a shader that ignores the tangent.w sign shows a lighting seam along "
            "the mirror line. Symmetric characters mirror by design; this only "
            "flags meshes where most of the surface is mirrored."
        ),
        current={"mirrored_tangent_ratio": round(ratio, 2)},
        recommended=_conf(
            {
                "hint": (
                    "confirm the shader reads tangent.w, or avoid mirroring "
                    "shells that carry directional surface detail"
                )
            },
            "medium",
        ),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LN007", engine),
    )
