# core/modules/lod_auditor/rules/lod_uv.py
#
# UV / texel-density rules: LW001 – LW011  (TDD Part 2 §15)
#
#   check_lwXXX(asset, engine="unreal", thresholds=None) -> Finding | None
#
# All rules read asset["uv_channels"] (list[UvChannelStats]) and abstain when
# the list is empty. Channel-0 rules run on channel 0; lightmap rules run on
# the channel named by lightmap_uv_index. Category "Mesh".

from lod_auditor.config import load_profile
from lod_auditor.guidance import guidance_for
from lod_auditor.schema import Finding, Saving
from lod_auditor.vram_model import lightmap_mb

THRESHOLDS = load_profile()


def _channels(asset: dict) -> list[dict]:
    raw = asset.get("uv_channels", []) or []
    return [c if isinstance(c, dict) else c.model_dump() for c in raw]


def _channel(asset: dict, index: int) -> dict | None:
    for c in _channels(asset):
        if int(c.get("channel", -1)) == index:
            return c
    return None


def _conf(recommended: dict, level: str) -> dict:
    recommended["confidence"] = level
    return recommended


# ── LW001 ─────────────────────────────────────────────────────────────────────


def check_lw001(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LW001: Overlapping UV area in the texturing channel (channel 0)."""
    T = thresholds if thresholds is not None else THRESHOLDS
    ch = _channel(asset, 0)
    if ch is None:
        return None
    overlap = float(ch.get("overlap_ratio", 0.0))
    if overlap <= T["LW001_MAX_OVERLAP"]:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LW001",
        category="Mesh",
        severity="warning",
        message=(
            f"UV channel 0 has {overlap * 100:.0f}% overlapping area — shells "
            "receiving identical texel data, often an unintended stack/mirror."
        ),
        current={"channel": 0, "overlap_ratio": round(overlap, 3)},
        recommended=_conf({"overlap_ratio": f"<= {T['LW001_MAX_OVERLAP']}"}, "high"),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LW001", engine),
    )


# ── LW002 ─────────────────────────────────────────────────────────────────────


def check_lw002(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LW002: Overlap in a static-lit mesh's lightmap UV channel (bake artifact)."""
    T = thresholds if thresholds is not None else THRESHOLDS
    idx = int(asset.get("lightmap_uv_index", -1))
    if idx < 0 or not asset.get("uses_static_lighting"):
        return None
    ch = _channel(asset, idx)
    if ch is None:
        return None
    overlap = float(ch.get("overlap_ratio", 0.0))
    if overlap <= T["LW002_MAX_OVERLAP"]:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LW002",
        category="Mesh",
        severity="error",
        message=(
            f"Lightmap UV channel {idx} overlaps ({overlap * 100:.2f}%) on a "
            "static-lit mesh — produces black splotches at bake time."
        ),
        current={"channel": idx, "overlap_ratio": round(overlap, 4)},
        recommended=_conf({"overlap_ratio": 0}, "high"),
        estimated_saving=Saving(),
        auto_fixable=True,
        guidance=guidance_for("LW002", engine),
    )


# ── LW003 ─────────────────────────────────────────────────────────────────────


def check_lw003(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LW003: UV stretching — worst-face UV/3D aspect skew beyond tolerance."""
    T = thresholds if thresholds is not None else THRESHOLDS
    ch = _channel(asset, 0)
    if ch is None:
        return None
    max_stretch = float(ch.get("max_stretch", 1.0))
    avg_stretch = float(ch.get("avg_stretch", 1.0))
    if max_stretch <= T["LW003_MAX_STRETCH"] or avg_stretch <= T["LW003_AVG_STRETCH"]:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LW003",
        category="Mesh",
        severity="warning",
        message=(
            f"UV stretching: worst face {max_stretch:.1f}× skew "
            f"(avg {avg_stretch:.1f}×) — smeared texels regardless of resolution."
        ),
        current={
            "max_stretch": round(max_stretch, 2),
            "avg_stretch": round(avg_stretch, 2),
        },
        recommended=_conf({"max_stretch": f"<= {T['LW003_MAX_STRETCH']}"}, "high"),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LW003", engine),
    )


# ── LW004 ─────────────────────────────────────────────────────────────────────


def check_lw004(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LW004: Conformal UV distortion on a tiling/detail-mapped mesh (heuristic)."""
    T = thresholds if thresholds is not None else THRESHOLDS
    ch = _channel(asset, 0)
    if ch is None:
        return None
    # Heuristic gate: only meaningful on meshes that sample a tiling detail map.
    detail = "detail" in asset.get("asset_path", "").lower() or bool(
        asset.get("has_detail_texturing")
    )
    if not detail:
        return None
    avg_stretch = float(ch.get("avg_stretch", 1.0))
    if avg_stretch <= T["LW004_AVG_STRETCH"]:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LW004",
        category="Mesh",
        severity="info",
        message=(
            f"Conformal UV distortion (avg {avg_stretch:.2f}×) on a detail-mapped "
            "mesh — subtle smearing visible on tiling maps."
        ),
        current={"avg_stretch": round(avg_stretch, 2)},
        recommended=_conf({"avg_stretch": f"<= {T['LW004_AVG_STRETCH']}"}, "medium"),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LW004", engine),
    )


# ── LW005 ─────────────────────────────────────────────────────────────────────


def check_lw005(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LW005: Excessive UV shell count — mip seams and padding waste."""
    T = thresholds if thresholds is not None else THRESHOLDS
    ch = _channel(asset, 0)
    if ch is None:
        return None
    islands = int(ch.get("island_count", 0))
    tris = int(asset.get("triangle_count", 0) or 0)
    if tris <= 0:
        return None
    budget = T["LW005_MAX_ISLANDS_PER_10K"] * tris / 10000.0
    if islands <= budget:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LW005",
        category="Mesh",
        severity="info",
        message=(
            f"{islands:,} UV islands for {tris:,} triangles (budget ≈ "
            f"{budget:.0f}) — mip seams, poor packing and padding waste."
        ),
        current={"island_count": islands},
        recommended=_conf({"island_count": f"<= {budget:.0f}"}, "high"),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LW005", engine),
    )


# ── LW006 ─────────────────────────────────────────────────────────────────────


def check_lw006(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LW006: Low UV packing efficiency — texture/lightmap resolution wasted."""
    T = thresholds if thresholds is not None else THRESHOLDS
    idx = int(asset.get("lightmap_uv_index", -1))
    # Prefer the lightmap channel when the mesh is static-lit (auto-fixable +
    # a real VRAM saving); otherwise judge channel 0.
    is_lightmap = idx >= 0 and asset.get("uses_static_lighting")
    ch = _channel(asset, idx) if is_lightmap else _channel(asset, 0)
    if ch is None:
        return None
    eff = float(ch.get("packing_efficiency", 1.0))
    floor = (
        T["LW006_LIGHTMAP_MIN_EFFICIENCY"] if is_lightmap else T["LW006_MIN_EFFICIENCY"]
    )
    if eff >= floor:
        return None
    saving = Saving()
    if is_lightmap:
        res = int(asset.get("lightmap_resolution", 0) or 0)
        if res:
            shrunk = int(res * (eff / floor) ** 0.5)
            saving = Saving(vram_mb=max(lightmap_mb(res) - lightmap_mb(shrunk), 0.0))
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LW006",
        category="Mesh",
        severity="warning",
        message=(
            f"UV packing efficiency {eff * 100:.0f}% on the "
            f"{'lightmap' if is_lightmap else 'texturing'} channel — the resolution "
            "is paid for but not used."
        ),
        current={
            "channel": idx if is_lightmap else 0,
            "packing_efficiency": round(eff, 2),
        },
        recommended=_conf({"packing_efficiency": f">= {floor}"}, "high"),
        estimated_saving=saving,
        auto_fixable=bool(is_lightmap),
        guidance=guidance_for("LW006", engine),
    )


# ── LW007 ─────────────────────────────────────────────────────────────────────


def check_lw007(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LW007: Average texel density out of band for the mesh's LOD group."""
    T = thresholds if thresholds is not None else THRESHOLDS
    ch = _channel(asset, 0)
    if ch is None:
        return None
    density = float(ch.get("texel_density_avg", 0.0))
    if density <= 0:
        return None
    group = asset.get("lod_group", "_default")
    targets = T["LW007_TARGET_DENSITY"]
    target = targets.get(group, targets["_default"])
    if density > target * T["LW007_HIGH_FACTOR"]:
        severity, verdict = "warning", "above"
    elif density < target * T["LW007_LOW_FACTOR"]:
        severity, verdict = "info", "below"
    else:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LW007",
        category="Mesh",
        severity=severity,
        message=(
            f"Texel density {density:.1f} texels/cm is {verdict} the target "
            f"({target:.1f}) for the '{group}' group — texture resolution "
            f"{'wasted on this mesh' if verdict == 'above' else 'too low (blurry)'}."
        ),
        current={"texel_density_avg": round(density, 1), "target": target},
        recommended=_conf({"texel_density_avg": f"≈ {target}"}, "high"),
        estimated_saving=Saving(),
        auto_fixable=bool(verdict == "above"),
        guidance=guidance_for("LW007", engine),
    )


# ── LW008 ─────────────────────────────────────────────────────────────────────


def check_lw008(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LW008: High texel-density variance across the mesh (crisp/blurry patches)."""
    T = thresholds if thresholds is not None else THRESHOLDS
    ch = _channel(asset, 0)
    if ch is None:
        return None
    cv = float(ch.get("texel_density_cv", 0.0))
    if cv <= T["LW008_MAX_CV"] or int(asset.get("triangle_count", 0) or 0) <= 1000:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LW008",
        category="Mesh",
        severity="info",
        message=(
            f"Texel-density variance (CV {cv:.2f}) is high — some areas crisp, "
            "others blurry; visible on large props."
        ),
        current={"texel_density_cv": round(cv, 2)},
        recommended=_conf({"texel_density_cv": f"<= {T['LW008_MAX_CV']}"}, "medium"),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LW008", engine),
    )


# ── LW009 ─────────────────────────────────────────────────────────────────────


def check_lw009(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LW009: UV area outside the 0-1 range on a clamped or lightmap channel."""
    T = thresholds if thresholds is not None else THRESHOLDS
    idx = int(asset.get("lightmap_uv_index", -1))
    # Lightmap leg (warning) — reliable: any excursion corrupts the bake.
    if idx >= 0 and asset.get("uses_static_lighting"):
        ch = _channel(asset, idx)
        if ch and float(ch.get("outside_unit_ratio", 0.0)) > 0:
            ratio = float(ch.get("outside_unit_ratio", 0.0))
            return Finding(
                asset_path=asset["asset_path"],
                rule_id="LW009",
                category="Mesh",
                severity="warning",
                message=(
                    f"Lightmap channel {idx} has {ratio * 100:.0f}% of UV area "
                    "outside 0-1 — the bake samples garbage there."
                ),
                current={"channel": idx, "outside_unit_ratio": round(ratio, 3)},
                recommended=_conf({"outside_unit_ratio": 0}, "high"),
                estimated_saving=Saving(),
                auto_fixable=False,
                guidance=guidance_for("LW009", engine),
            )
    # Channel-0 leg (info) — only when the sampler is known to clamp; otherwise
    # tiling (wrap) UVs legitimately exceed 0-1, so we abstain to avoid noise.
    if asset.get("uv0_addressing") == "clamp":
        ch = _channel(asset, 0)
        if ch and float(ch.get("outside_unit_ratio", 0.0)) > T["LW009_INFO_RATIO"]:
            ratio = float(ch.get("outside_unit_ratio", 0.0))
            return Finding(
                asset_path=asset["asset_path"],
                rule_id="LW009",
                category="Mesh",
                severity="info",
                message=(
                    f"{ratio * 100:.0f}% of channel-0 UV area is outside 0-1 on a "
                    "clamp-addressed sampler — edge texels smear."
                ),
                current={"channel": 0, "outside_unit_ratio": round(ratio, 3)},
                recommended=_conf(
                    {"outside_unit_ratio": f"<= {T['LW009_INFO_RATIO']}"}, "high"
                ),
                estimated_saving=Saving(),
                auto_fixable=False,
                guidance=guidance_for("LW009", engine),
            )
    return None


# ── LW010 ─────────────────────────────────────────────────────────────────────


def check_lw010(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LW010: A consumer references a UV channel the mesh doesn't have."""
    channels = int(asset.get("uv_channel_count", 0) or 0)
    if channels <= 0:
        return None
    # Material leg — a material samples a channel index >= the mesh's count.
    max_mat_ch = int(asset.get("max_used_uv_channel", -1))
    if max_mat_ch >= channels:
        return Finding(
            asset_path=asset["asset_path"],
            rule_id="LW010",
            category="Mesh",
            severity="error",
            message=(
                f"A material samples UV channel {max_mat_ch} but the mesh only has "
                f"{channels} channel(s) — distant instances sample undefined UVs."
            ),
            current={"uv_channel_count": channels, "required_channel": max_mat_ch},
            recommended=_conf({"uv_channel_count": max_mat_ch + 1}, "high"),
            estimated_saving=Saving(),
            auto_fixable=False,
            guidance=guidance_for("LW010", engine),
        )
    # Lightmap leg — static-lit mesh with no lightmap channel.
    if (
        asset.get("uses_static_lighting")
        and int(asset.get("lightmap_uv_index", -1)) < 0
    ):
        return Finding(
            asset_path=asset["asset_path"],
            rule_id="LW010",
            category="Mesh",
            severity="error",
            message=(
                "Static-lit mesh has no lightmap UV channel — the bake has nowhere "
                "to store lighting."
            ),
            current={"uses_static_lighting": True, "lightmap_uv_index": -1},
            recommended=_conf({"generate_lightmap_uvs": True}, "high"),
            estimated_saving=Saving(),
            auto_fixable=True,
            guidance=guidance_for("LW010", engine),
        )
    return None


# ══════════════════════════════════════════════════════════════════════════════
# LW011 — Unity-only complement to LW009's lightmap leg.
#
# LW009's lightmap leg additionally requires ``uses_static_lighting`` before it
# trusts an outside-0-1 excursion as a real bake defect. Unity's mesh scanner
# never sends that flag, so the leg is permanently silent there even though
# ``outside_unit_ratio`` is real. lightmap_uv_index itself is the next best
# signal: the client only has a reason to report a lightmap channel index at
# all when the mesh carries a second UV set meant for baking, so treat that as
# enough to warrant a lower-confidence, info-level heads-up rather than staying
# silent on real data.
# ══════════════════════════════════════════════════════════════════════════════


def check_lw011(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LW011: Unity lightmap UV channel has area outside 0-1 (no static-lit signal)."""
    T = thresholds if thresholds is not None else THRESHOLDS
    if engine.strip().lower() != "unity":
        return None
    idx = int(asset.get("lightmap_uv_index", -1))
    if idx < 0:
        return None
    ch = _channel(asset, idx)
    if ch is None:
        return None
    ratio = float(ch.get("outside_unit_ratio", 0.0))
    if ratio <= T["LW011_MAX_OUTSIDE_RATIO"]:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LW011",
        category="Mesh",
        severity="info",
        message=(
            f"Lightmap UV channel {idx} has {ratio * 100:.0f}% of UV area outside "
            "0-1 — if this mesh contributes to baked lighting, the Progressive "
            "Lightmapper samples garbage there."
        ),
        current={"channel": idx, "outside_unit_ratio": round(ratio, 3)},
        recommended=_conf({"outside_unit_ratio": 0}, "medium"),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LW011", engine),
    )
