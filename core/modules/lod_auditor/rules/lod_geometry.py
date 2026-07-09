# core/modules/lod_auditor/rules/lod_geometry.py
#
# Mesh geometry rules: LG001 – LG015  (TDD Part 2 §14)
#
# Each rule is a pure function:
#   check_lgXXX(asset: dict, engine="unreal", thresholds=None) -> Finding | None
#
# All rules read Contract v2 mesh fields (schema.MeshAsset) and abstain when
# those fields are absent/zero-defaulted, so a v1 payload never false-positives.
# Category "Mesh"; dispatched for StaticMesh / SkeletalMesh.

import math

from lod_auditor.config import load_profile
from lod_auditor.guidance import guidance_for
from lod_auditor.schema import Finding, Saving
from lod_auditor.vram_model import mesh_buffer_mb

THRESHOLDS = load_profile()

# Fraction of triangle count used as a vertex-count proxy when only tris are
# known (indexed meshes average ~0.55 verts per triangle after welding).
_VERT_PER_TRI = 0.55


def _lod0_tris(asset: dict) -> int:
    """LOD0 triangle count from the explicit field or the first LOD entry."""
    tris = int(asset.get("triangle_count", 0) or 0)
    if tris:
        return tris
    lods = asset.get("lods", [])
    if lods:
        first = lods[0]
        first = first if isinstance(first, dict) else first.model_dump()
        return int(first.get("triangles", 0) or 0)
    return 0


def _conf(recommended: dict, level: str) -> dict:
    """Attach the §13.5 confidence marker to a recommended dict."""
    recommended["confidence"] = level
    return recommended


# ── LG001 ─────────────────────────────────────────────────────────────────────


def check_lg001(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LG001: LOD0 triangle count exceeds the absolute per-asset cap."""
    T = thresholds if thresholds is not None else THRESHOLDS
    if asset.get("nanite_enabled"):
        return None  # Nanite meshes are budgeted by LD013, not here
    tris = _lod0_tris(asset)
    if tris <= 0:
        return None
    budget: int = T["LG001_MAX_TRIANGLES"]
    if tris <= budget:
        return None
    error_cap: int = T["LG001_ERROR_TRIANGLES"]
    severity = "error" if tris > error_cap else "warning"
    excess_verts = int((tris - budget) * _VERT_PER_TRI)
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LG001",
        category="Mesh",
        severity=severity,
        message=(
            f"LOD0 has {tris:,} triangles — over the absolute cap of "
            f"{budget:,} for this profile ({tris - budget:,} over)."
        ),
        current={"triangle_count": tris},
        recommended=_conf(
            {"triangle_count": f"<= {budget:,}", "method": "reduction"}, "medium"
        ),
        estimated_saving=Saving(vram_mb=mesh_buffer_mb(excess_verts)),
        auto_fixable=True,
        guidance=guidance_for("LG001", engine, budget=budget),
    )


# ── LG002 ─────────────────────────────────────────────────────────────────────


def check_lg002(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LG002: Vertex count disproportionate to triangle count (split-heavy mesh)."""
    T = thresholds if thresholds is not None else THRESHOLDS
    verts = int(asset.get("vertex_count", 0) or 0)
    tris = _lod0_tris(asset)
    if verts <= 0 or tris <= 0:
        return None
    if verts <= T["LG002_MIN_VERTS"]:
        return None
    ratio = verts / max(tris * 0.5, 1.0)
    if ratio <= T["LG002_MAX_VERTEX_RATIO"]:
        return None
    expected_verts = int(tris * 0.5 * T["LG002_MAX_VERTEX_RATIO"])
    excess_verts = max(verts - expected_verts, 0)
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LG002",
        category="Mesh",
        severity="warning",
        message=(
            f"{verts:,} vertices for {tris:,} triangles "
            f"(ratio {ratio:.2f} > {T['LG002_MAX_VERTEX_RATIO']}). "
            "UV seams / hard edges are splitting vertices, inflating the buffer."
        ),
        current={"vertex_count": verts, "vertex_ratio": round(ratio, 2)},
        recommended=_conf(
            {
                "vertex_ratio": f"<= {T['LG002_MAX_VERTEX_RATIO']}",
                "hint": "reduce UV seams / soften hard edges",
            },
            "high",
        ),
        estimated_saving=Saving(vram_mb=mesh_buffer_mb(excess_verts)),
        auto_fixable=False,
        guidance=guidance_for("LG002", engine),
    )


# ── LG003 ─────────────────────────────────────────────────────────────────────


def check_lg003(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LG003: Vertex density (verts per cm²) far above the profile norm."""
    T = thresholds if thresholds is not None else THRESHOLDS
    verts = int(asset.get("vertex_count", 0) or 0)
    radius = float(asset.get("bounds_radius", 0.0) or 0.0)
    if verts <= 0 or radius <= 0:
        return None
    surface_area = 4.0 * math.pi * radius * radius  # sphere-area proxy (cm²)
    density = verts / max(surface_area, 1.0)
    cap = T["LG003_MAX_DENSITY"][-1][1]
    for radius_limit, density_cap in T["LG003_MAX_DENSITY"]:
        if radius <= radius_limit:
            cap = density_cap
            break
    if density <= cap:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LG003",
        category="Mesh",
        severity="info",
        message=(
            f"Vertex density {density:.2f} verts/cm² exceeds the norm "
            f"({cap} for this size class) — likely a scan / photogrammetry import."
        ),
        current={"vertex_density": round(density, 2)},
        recommended=_conf({"vertex_density": f"<= {cap}"}, "medium"),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LG003", engine),
    )


# ── LG004 ─────────────────────────────────────────────────────────────────────


def check_lg004(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LG004: Degenerate (zero-area) triangles in the mesh."""
    T = thresholds if thresholds is not None else THRESHOLDS
    degenerate = int(asset.get("degenerate_triangle_count", 0) or 0)
    if degenerate <= 0:
        return None
    tris = _lod0_tris(asset)
    ratio = degenerate / max(tris, 1)
    nanite = bool(asset.get("nanite_enabled"))
    severity = "error" if (ratio > T["LG004_ERROR_RATIO"] or nanite) else "warning"
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LG004",
        category="Mesh",
        severity=severity,
        message=(
            f"{degenerate:,} degenerate (zero-area) triangles "
            f"({ratio * 100:.2f}% of the mesh). They waste vertex work and "
            "break tangent computation" + (" and Nanite clusters." if nanite else ".")
        ),
        current={"degenerate_triangle_count": degenerate, "ratio": round(ratio, 4)},
        recommended=_conf({"degenerate_triangle_count": 0}, "high"),
        estimated_saving=Saving(),
        auto_fixable=True,
        guidance=guidance_for("LG004", engine),
    )


# ── LG005 ─────────────────────────────────────────────────────────────────────


def check_lg005(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LG005: Fully duplicate vertices (position + attributes) that should weld."""
    T = thresholds if thresholds is not None else THRESHOLDS
    dupes = int(asset.get("duplicate_vertex_count", 0) or 0)
    if dupes <= T["LG005_MIN_COUNT"]:
        return None
    verts = int(asset.get("vertex_count", 0) or 0)
    severity = (
        "warning" if (verts and dupes > verts * T["LG005_WARN_RATIO"]) else "info"
    )
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LG005",
        category="Mesh",
        severity=severity,
        message=(
            f"{dupes:,} fully duplicate vertices (identical position and "
            "attributes) — pure vertex-buffer waste that should be welded."
        ),
        current={"duplicate_vertex_count": dupes},
        recommended=_conf({"duplicate_vertex_count": 0}, "high"),
        estimated_saving=Saving(vram_mb=mesh_buffer_mb(dupes)),
        auto_fixable=True,
        guidance=guidance_for("LG005", engine),
    )


# ── LG006 ─────────────────────────────────────────────────────────────────────


def check_lg006(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LG006: Near-coincident unwelded vertices (heuristic; low confidence)."""
    T = thresholds if thresholds is not None else THRESHOLDS
    overlapping = int(asset.get("overlapping_vertex_count", 0) or 0)
    verts = int(asset.get("vertex_count", 0) or 0)
    if verts <= 0 or overlapping <= verts * T["LG006_RATIO"]:
        return None
    normal_stats = asset.get("normal_stats") or {}
    hard_edge_ratio = float(normal_stats.get("hard_edge_ratio", 1.0))
    if hard_edge_ratio >= T["LG006_MAX_HARD_EDGE_RATIO"]:
        return None  # likely intentional seams / hard edges, not import damage
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LG006",
        category="Mesh",
        severity="info",
        message=(
            f"{overlapping:,} near-coincident but unwelded vertices on a mesh "
            "with few hard edges — possible import damage worth a DCC weld pass."
        ),
        current={"overlapping_vertex_count": overlapping},
        recommended=_conf({"overlapping_vertex_count": "weld in DCC"}, "low"),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LG006", engine),
    )


# ── LG007 ─────────────────────────────────────────────────────────────────────


def check_lg007(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LG007: Non-manifold geometry (edges shared by >2 faces / bowtie verts)."""
    count = int(asset.get("non_manifold_edge_count", 0) or 0)
    if count <= 0:
        return None
    nanite = bool(asset.get("nanite_enabled"))
    static_lit = bool(asset.get("uses_static_lighting"))
    severity = "error" if (nanite or static_lit) else "warning"
    consumers = []
    if nanite:
        consumers.append("Nanite simplification")
    if static_lit:
        consumers.append("baked-GI lightmapping / mesh-collider cooking")
    tail = f" It degrades {', '.join(consumers)}." if consumers else ""
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LG007",
        category="Mesh",
        severity=severity,
        message=(
            f"{count:,} non-manifold edges (shared by more than two faces)." + tail
        ),
        current={"non_manifold_edge_count": count},
        recommended=_conf({"non_manifold_edge_count": 0}, "high"),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LG007", engine),
    )


# ── LG008 ─────────────────────────────────────────────────────────────────────


def check_lg008(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LG008: Open (boundary) edges on a mesh expected to be a closed hull."""
    T = thresholds if thresholds is not None else THRESHOLDS
    open_edges = int(asset.get("open_edge_count", 0) or 0)
    if open_edges <= T["LG008_MAX_OPEN_EDGES"]:
        return None
    if not (asset.get("uses_static_lighting") or asset.get("nanite_enabled")):
        return None  # planes / cards are legitimately open
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LG008",
        category="Mesh",
        severity="info",
        message=(
            f"{open_edges:,} open boundary edges on a closed-hull consumer "
            "(static lighting / Nanite) — risks light leaks and silhouette holes."
        ),
        current={"open_edge_count": open_edges},
        recommended=_conf({"open_edge_count": 0}, "medium"),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LG008", engine),
    )


# ── LG009 ─────────────────────────────────────────────────────────────────────


def check_lg009(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LG009: High ratio of interior faces never visible from the hull."""
    T = thresholds if thresholds is not None else THRESHOLDS
    ratio = float(asset.get("internal_face_ratio", 0.0) or 0.0)
    tris = _lod0_tris(asset)
    if ratio <= T["LG009_MAX_INTERNAL_RATIO"] or tris <= T["LG009_MIN_TRIS"]:
        return None
    buried = int(tris * ratio * _VERT_PER_TRI)
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LG009",
        category="Mesh",
        severity="warning",
        message=(
            f"{ratio * 100:.0f}% of faces are interior (never visible from the "
            "convex hull) — buried detail cooked into every LOD and shadow pass."
        ),
        current={"internal_face_ratio": round(ratio, 2)},
        recommended=_conf(
            {"internal_face_ratio": f"<= {T['LG009_MAX_INTERNAL_RATIO']}"}, "low"
        ),
        estimated_saving=Saving(vram_mb=mesh_buffer_mb(buried)),
        auto_fixable=False,
        guidance=guidance_for("LG009", engine),
    )


# ── LG010 ─────────────────────────────────────────────────────────────────────


def check_lg010(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LG010: Interior caps inside modular kit pieces that neighbours hide."""
    T = thresholds if thresholds is not None else THRESHOLDS
    if not asset.get("is_kit_piece"):
        return None
    ratio = float(asset.get("internal_face_ratio", 0.0) or 0.0)
    if ratio <= T["LG010_MAX_INTERNAL_RATIO"]:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LG010",
        category="Mesh",
        severity="info",
        message=(
            f"Modular kit piece with {ratio * 100:.0f}% interior faces — caps that "
            "adjacent pieces always hide. Remove them to cut per-instance cost."
        ),
        current={"internal_face_ratio": round(ratio, 2)},
        recommended=_conf(
            {"internal_face_ratio": f"<= {T['LG010_MAX_INTERNAL_RATIO']}"}, "low"
        ),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LG010", engine),
    )


# ── LG011 ─────────────────────────────────────────────────────────────────────


def check_lg011(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LG011: More UV channels than any material or lightmap consumer uses."""
    T = thresholds if thresholds is not None else THRESHOLDS
    channels = int(asset.get("uv_channel_count", 0) or 0)
    if channels <= 0:
        return None
    lm_idx = int(asset.get("lightmap_uv_index", -1))
    max_mat_ch = int(asset.get("max_used_uv_channel", -1))
    if max_mat_ch < 0 and lm_idx < 0:
        return None  # can't establish the used-channel count safely — abstain
    used = max(max_mat_ch + 1, lm_idx + 1, T["LG011_MIN_KEEP"])
    if channels <= used:
        return None
    excess = channels - used
    verts = int(asset.get("vertex_count", 0) or 0)
    # 8 bytes/vertex per UV channel (float2), across LOD0.
    vram = round(verts * 8 * excess / 1_048_576, 2)
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LG011",
        category="Mesh",
        severity="warning",
        message=(
            f"{channels} UV channels but only {used} are consumed — "
            f"{excess} unused channel(s) cost 8 bytes/vertex each across every LOD."
        ),
        current={"uv_channel_count": channels, "channels_used": used},
        recommended=_conf({"uv_channel_count": used}, "high"),
        estimated_saving=Saving(vram_mb=vram),
        auto_fixable=True,
        guidance=guidance_for("LG011", engine),
    )


# ── LG012 ─────────────────────────────────────────────────────────────────────


def check_lg012(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LG012: Too many draw sections / material slots at LOD0 (draw-call explosion)."""
    T = thresholds if thresholds is not None else THRESHOLDS
    sections = int(asset.get("section_count", 0) or 0)
    slots = int(asset.get("material_slot_count", 0) or 0)
    over_sections = sections > T["LG012_MAX_SECTIONS"]
    over_slots = slots > T["LG012_MAX_SLOTS"]
    if not (over_sections or over_slots):
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LG012",
        category="Mesh",
        severity="warning",
        message=(
            f"{sections} draw sections / {slots} material slots at LOD0 — each "
            "section is a separate draw call per instance per pass."
        ),
        current={"section_count": sections, "material_slot_count": slots},
        recommended=_conf(
            {
                "section_count": f"<= {T['LG012_MAX_SECTIONS']}",
                "hint": "merge slots that share a material",
            },
            "high",
        ),
        estimated_saving=Saving(),
        auto_fixable=True,
        guidance=guidance_for("LG012", engine),
    )


# ── LG013 ─────────────────────────────────────────────────────────────────────


def check_lg013(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LG013: Pivot far outside the mesh bounds (breaks culling / snapping)."""
    T = thresholds if thresholds is not None else THRESHOLDS
    offset = float(asset.get("pivot_offset_ratio", 0.0) or 0.0)
    if offset <= T["LG013_MAX_OFFSET_RATIO"]:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LG013",
        category="Mesh",
        severity="info",
        message=(
            f"Pivot is {offset:.1f}× the bounds radius from the bounds centre — "
            "hurts culling precision, socket math and modular snapping."
        ),
        current={"pivot_offset_ratio": round(offset, 2)},
        recommended=_conf({"pivot": "within bounds"}, "high"),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LG013", engine),
    )


# ── LG014 ─────────────────────────────────────────────────────────────────────


def check_lg014(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LG014: Import scale ≠ 1.0 or non-uniform (unit mismatch baked at import)."""
    T = thresholds if thresholds is not None else THRESHOLDS
    scale = float(asset.get("import_uniform_scale", 1.0))
    nonuniform = bool(asset.get("import_scale_nonuniform"))
    if abs(scale - 1.0) <= T["LG014_TOLERANCE"] and not nonuniform:
        return None
    reason = (
        "non-uniform import scale" if nonuniform else f"import scale {scale:g} ≠ 1.0"
    )
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LG014",
        category="Mesh",
        severity="warning",
        message=(
            f"{reason} — unit mismatch baked at import compounds transform errors "
            "and breaks physics mass."
        ),
        current={
            "import_uniform_scale": scale,
            "import_scale_nonuniform": nonuniform,
        },
        recommended=_conf({"import_uniform_scale": 1.0}, "high"),
        estimated_saving=Saving(),
        auto_fixable=True,
        guidance=guidance_for("LG014", engine),
    )


# ── LG015 ─────────────────────────────────────────────────────────────────────


def check_lg015(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LG015: Placed instances use negative scale (mirroring), breaking batching."""
    T = thresholds if thresholds is not None else THRESHOLDS
    if not asset.get("has_negative_scale_instances"):
        return None
    if int(asset.get("used_in_levels", 0) or 0) < T["LG015_MIN_LEVELS"]:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LG015",
        category="Mesh",
        severity="info",
        message=(
            "Mesh is placed with negative (mirrored) scale — flips winding and "
            "disables instanced-static batching with the positive copies."
        ),
        current={"has_negative_scale_instances": True},
        recommended=_conf(
            {"hint": "author a mirrored variant or use reverse-culling"}, "medium"
        ),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LG015", engine),
    )
