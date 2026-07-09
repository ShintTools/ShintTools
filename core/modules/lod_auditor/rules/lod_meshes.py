# core/modules/lod_auditor/rules/lod_meshes.py
#
# Mesh LOD rules: LD001 – LD003
#
# Each rule is a pure function:
#   check_ldXXX(asset: dict) -> Finding | None

from lod_auditor.config import load_profile
from lod_auditor.guidance import guidance_for
from lod_auditor.schema import Finding, Saving
from lod_auditor.vram_model import mesh_buffer_mb

# Thresholds are loaded from YAML — see config/thresholds_default.yaml.
THRESHOLDS = load_profile()

# Blend modes a Nanite section renders natively (LD012/LD013).
_NANITE_OK_BLEND = frozenset({"Opaque", "Masked"})
_NANITE_BAD_BLEND = frozenset({"Translucent", "Additive", "Modulate"})


# ── LT001 ─────────────────────────────────────────────────────────────────────


def check_ld001(asset: dict, engine: str = "unreal") -> Finding | None:
    """LD001: Mesh has no LOD chain — only LOD0 is present."""
    lod_count: int = asset.get("lod_count", 1)

    if lod_count >= THRESHOLDS["LD001_MIN_LOD_COUNT"]:
        return None

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LD001",
        category="Mesh",
        severity="warning",
        message=(
            "Mesh has no LOD chain. "
            "At distance the engine renders the full LOD0 poly count, "
            "causing significant GPU overdraw on large levels."
        ),
        current={"lod_count": lod_count},
        recommended={"lod_count": ">= 2"},
        estimated_saving=Saving(vram_mb=0.0, shader_instructions=0),
        auto_fixable=True,
        guidance=None,
    )


# ── LD002 ─────────────────────────────────────────────────────────────────────


def check_ld002(asset: dict, engine: str = "unreal") -> Finding | None:
    """LD002: LOD chain is not monotonically decreasing in triangles or screen size."""
    raw_lods: list = asset.get("lods", [])

    if len(raw_lods) < 2:
        return None

    # Normalise each entry to a plain dict
    lod_dicts: list[dict] = [
        lod if isinstance(lod, dict) else lod.model_dump() for lod in raw_lods
    ]

    violations: list[str] = []

    for i in range(1, len(lod_dicts)):
        prev = lod_dicts[i - 1]
        curr = lod_dicts[i]

        prev_tris: int = prev.get("triangles", 0)
        curr_tris: int = curr.get("triangles", 0)
        if curr_tris >= prev_tris:
            violations.append(
                f"LOD{i} triangles ({curr_tris:,}) >= LOD{i - 1} ({prev_tris:,})"
            )

        prev_ss: float = prev.get("screen_size", 1.0)
        curr_ss: float = curr.get("screen_size", 0.0)
        if curr_ss >= prev_ss:
            violations.append(
                f"LOD{i} screen_size ({curr_ss}) >= LOD{i - 1} ({prev_ss})"
            )

    if not violations:
        return None

    lod_snapshot: list[dict] = [
        {
            "index": lod.get("index"),
            "triangles": lod.get("triangles"),
            "screen_size": lod.get("screen_size"),
        }
        for lod in lod_dicts
    ]

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LD002",
        category="Mesh",
        severity="warning",
        message=(
            "LOD chain is not monotonically decreasing: "
            + "; ".join(violations)
            + ". The engine may skip LOD transitions or pick the wrong level."
        ),
        current={"lods": lod_snapshot},
        recommended={"lods": "strictly_decreasing_triangles_and_screen_size"},
        estimated_saving=Saving(vram_mb=0.0, shader_instructions=0),
        auto_fixable=True,
        guidance=None,
    )


# ── LD003 ─────────────────────────────────────────────────────────────────────


def check_ld003(asset: dict, engine: str = "unreal") -> Finding | None:
    """LD003: LOD0 triangle count exceeds the budget for the mesh's size class."""
    raw_lods: list = asset.get("lods", [])
    bounds_radius: float = float(asset.get("bounds_radius", 100.0))

    if not raw_lods:
        return None

    lod0: dict = (
        raw_lods[0] if isinstance(raw_lods[0], dict) else raw_lods[0].model_dump()
    )
    lod0_triangles: int = lod0.get("triangles", 0)

    # Walk the budget tiers until the radius fits
    budget: int = THRESHOLDS["LD003_TRIANGLE_BUDGET"][-1][1]
    for radius_limit, tri_limit in THRESHOLDS["LD003_TRIANGLE_BUDGET"]:
        if bounds_radius <= radius_limit:
            budget = tri_limit
            break

    if lod0_triangles <= budget:
        return None

    excess: int = lod0_triangles - budget

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LD003",
        category="Mesh",
        severity="warning",
        message=(
            f"LOD0 has {lod0_triangles:,} triangles; "
            f"budget for this size class (radius ≈ {bounds_radius:.0f} units): "
            f"{budget:,}. {excess:,} triangles over budget."
        ),
        current={"lod0_triangles": lod0_triangles, "bounds_radius": bounds_radius},
        recommended={"lod0_triangles": f"<= {budget}"},
        estimated_saving=Saving(vram_mb=0.0, shader_instructions=0),
        auto_fixable=False,
        guidance=guidance_for("LD003", engine, budget=budget),
    )


# ── Shared helpers for the LOD-chain completion rules (LD004–LD013) ────────────


def _lods(asset: dict) -> list[dict]:
    """Normalise the LOD list to plain dicts."""
    return [
        lod if isinstance(lod, dict) else lod.model_dump()
        for lod in asset.get("lods", [])
    ]


def _size_ladder_value(ladder: list, radius: float):
    """Walk a [[radius_limit, value], ...] ladder and return the value whose
    radius bucket contains *radius* (last bucket if none match)."""
    value = ladder[-1][1]
    for radius_limit, bucket_value in ladder:
        if radius <= radius_limit:
            return bucket_value
    return value


def _conf(recommended: dict, level: str) -> dict:
    recommended["confidence"] = level
    return recommended


# ── LD004 ─────────────────────────────────────────────────────────────────────


def check_ld004(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LD004: Too few LODs for the mesh's size class (refines LD001)."""
    T = thresholds if thresholds is not None else THRESHOLDS
    if asset.get("nanite_enabled"):
        return None  # Nanite replaces discrete chains (LD013 governs it)
    lods = _lods(asset)
    lod_count = asset.get("lod_count", len(lods)) or len(lods)
    if lod_count < 2:
        return None  # LD001 owns the "no chain at all" case
    radius = float(asset.get("bounds_radius", 100.0))
    expected = _size_ladder_value(T["LD004_EXPECTED_LODS"], radius)
    if lod_count >= expected:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LD004",
        category="Mesh",
        severity="warning",
        message=(
            f"Only {lod_count} LODs for a mesh this size (radius ≈ {radius:.0f}); "
            f"expected at least {expected}. Distant instances pay too much overdraw."
        ),
        current={"lod_count": lod_count, "size_class_radius": round(radius, 0)},
        recommended=_conf({"lod_count": expected}, "medium"),
        estimated_saving=Saving(),
        auto_fixable=True,
        guidance=guidance_for("LD004", engine),
    )


# ── LD005 ─────────────────────────────────────────────────────────────────────


def check_ld005(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LD005: More LODs than the profile ever selects (disk/memory/build waste)."""
    T = thresholds if thresholds is not None else THRESHOLDS
    lods = _lods(asset)
    lod_count = asset.get("lod_count", len(lods)) or len(lods)
    max_lods = T["LD005_MAX_LODS"]
    min_ss = T["LD005_MIN_SCREEN_SIZE"]

    over_cap = lod_count > max_lods
    # Two trailing LODs whose switch point is below the floor => never selected.
    tiny_tail = (
        len(lods) >= 2
        and lods[-1].get("screen_size", 1.0) < min_ss
        and lods[-2].get("screen_size", 1.0) < min_ss
    )
    if not (over_cap or tiny_tail):
        return None

    excess_verts = (
        sum(int(lod.get("vertices", 0)) for lod in lods[max_lods:]) if over_cap else 0
    )
    vram = mesh_buffer_mb(excess_verts)
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LD005",
        category="Mesh",
        severity="info",
        message=(
            f"{lod_count} LODs — more than the screen-size ladder selects. "
            "Trailing levels cost disk, memory and build time with no runtime use."
        ),
        current={"lod_count": lod_count},
        recommended=_conf({"lod_count": f"<= {max_lods}"}, "high"),
        estimated_saving=Saving(vram_mb=vram, build_size_mb=vram),
        auto_fixable=True,
        guidance=guidance_for("LD005", engine),
    )


# ── LD006 ─────────────────────────────────────────────────────────────────────


def check_ld006(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LD006: Adjacent-LOD triangle ratio outside the effective band."""
    T = thresholds if thresholds is not None else THRESHOLDS
    lods = _lods(asset)
    if len(lods) < 2:
        return None
    lo, hi = T["LD006_MIN_RATIO"], T["LD006_MAX_RATIO"]
    violations: list[str] = []
    for i in range(1, len(lods)):
        prev = int(lods[i - 1].get("triangles", 0))
        curr = int(lods[i].get("triangles", 0))
        if prev <= 0:
            continue
        ratio = curr / prev
        if ratio > hi:
            violations.append(
                f"LOD{i} keeps {ratio * 100:.0f}% of LOD{i - 1} (too shallow)"
            )
        elif ratio < lo:
            violations.append(
                f"LOD{i} keeps {ratio * 100:.0f}% of LOD{i - 1} (too steep)"
            )
    if not violations:
        return None
    snapshot = [
        {"index": lod.get("index", i), "triangles": lod.get("triangles")}
        for i, lod in enumerate(lods)
    ]
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LD006",
        category="Mesh",
        severity="warning",
        message="Reduction ratios out of band: " + "; ".join(violations) + ".",
        current={"lods": snapshot},
        recommended=_conf(
            {"triangle_ratio_band": [lo, hi], "target": T["LD006_TARGET_RATIO"]},
            "high",
        ),
        estimated_saving=Saving(),
        auto_fixable=True,
        guidance=guidance_for("LD006", engine),
    )


# ── LD007 ─────────────────────────────────────────────────────────────────────


def check_ld007(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LD007: Screen-size switch points misconfigured (gaps / bad LOD1 point)."""
    T = thresholds if thresholds is not None else THRESHOLDS
    lods = _lods(asset)
    if len(lods) < 2:
        return None
    violations: list[str] = []
    lod1_ss = float(lods[1].get("screen_size", 0.0))
    if lod1_ss > T["LD007_MAX_LOD1_SS"]:
        violations.append(f"LOD1 kicks in at {lod1_ss} (LOD0 effectively never shown)")
    elif lod1_ss < T["LD007_MIN_LOD1_SS"]:
        violations.append(f"LOD1 kicks in at {lod1_ss} (LOD0 shown at all distances)")
    for i in range(1, len(lods)):
        prev = float(lods[i - 1].get("screen_size", 1.0))
        curr = float(lods[i].get("screen_size", 0.0))
        if prev > 0 and curr / prev > T["LD007_MAX_STEP"]:
            violations.append(
                f"LOD{i} step is only {curr / prev:.2f}× (barely changes)"
            )
    if not violations:
        return None
    ladder = T["LD007_DEFAULT_LADDER"][: len(lods)]
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LD007",
        category="Mesh",
        severity="warning",
        message="Screen-size progression issues: " + "; ".join(violations) + ".",
        current={"screen_sizes": [lod.get("screen_size") for lod in lods]},
        recommended=_conf({"screen_sizes": ladder}, "high"),
        estimated_saving=Saving(),
        auto_fixable=True,
        guidance=guidance_for("LD007", engine),
    )


# ── LD008 ─────────────────────────────────────────────────────────────────────


def check_ld008(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LD008: A lower LOD draws more material slots/sections than the LOD above."""
    lods = _lods(asset)
    if len(lods) < 2:
        return None
    violations: list[str] = []
    for i in range(1, len(lods)):
        prev_slots = len(lods[i - 1].get("material_slots_used", []) or [])
        curr_slots = len(lods[i].get("material_slots_used", []) or [])
        prev_sec = int(lods[i - 1].get("section_count", 1))
        curr_sec = int(lods[i].get("section_count", 1))
        if prev_slots and curr_slots > prev_slots:
            violations.append(
                f"LOD{i} uses {curr_slots} slots vs {prev_slots} above it"
            )
        elif curr_sec > prev_sec:
            violations.append(f"LOD{i} has {curr_sec} sections vs {prev_sec} above it")
    if not violations:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LD008",
        category="Mesh",
        severity="warning",
        message=(
            "Draw composition grows along the chain: "
            + "; ".join(violations)
            + " — distant instances pay more draw calls than near ones."
        ),
        current={"violations": violations},
        recommended=_conf({"sections": "non-increasing along the chain"}, "high"),
        estimated_saving=Saving(),
        auto_fixable=True,
        guidance=guidance_for("LD008", engine),
    )


# ── LD009 ─────────────────────────────────────────────────────────────────────


def check_ld009(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LD009: A lower LOD dropped a UV channel a shared material still samples."""
    lods = _lods(asset)
    if len(lods) < 2:
        return None
    required = int(asset.get("max_used_uv_channel", -1))
    if required < 0:
        return None  # can't establish the required channel — abstain
    for i in range(1, len(lods)):
        ch = int(lods[i].get("uv_channel_count", 0))
        if ch and ch <= required:
            return Finding(
                asset_path=asset["asset_path"],
                rule_id="LD009",
                category="Mesh",
                severity="error",
                message=(
                    f"LOD{i} has {ch} UV channels but a material samples channel "
                    f"{required} — distant instances sample undefined UVs."
                ),
                current={
                    "lod": i,
                    "uv_channel_count": ch,
                    "required_channel": required,
                },
                recommended=_conf({"uv_channel_count": required + 1}, "high"),
                estimated_saving=Saving(),
                auto_fixable=True,
                guidance=guidance_for("LD009", engine),
            )
    return None


# ── LD010 ─────────────────────────────────────────────────────────────────────


def check_ld010(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LD010: Shadow rendering follows the render LOD on a high-poly mesh."""
    T = thresholds if thresholds is not None else THRESHOLDS
    lods = _lods(asset)
    lod_count = asset.get("lod_count", len(lods)) or len(lods)
    if asset.get("shadow_lod_index", -1) != -1 or lod_count < 2 or not lods:
        return None
    lod0_tris = int(lods[0].get("triangles", 0))
    if lod0_tris <= T["LD010_MIN_TRIS"]:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LD010",
        category="Mesh",
        severity="info",
        message=(
            f"Shadow passes use LOD0 ({lod0_tris:,} tris) — a dedicated higher "
            "shadow LOD is nearly free quality-wise and cuts shadow-depth cost."
        ),
        current={"shadow_lod_index": -1, "lod0_triangles": lod0_tris},
        recommended=_conf({"shadow_lod_index": 1}, "high"),
        estimated_saving=Saving(),
        auto_fixable=True,
        guidance=guidance_for("LD010", engine),
    )


# ── LD011 ─────────────────────────────────────────────────────────────────────


def check_ld011(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LD011: Collision disproportionate to the mesh (missing / over-budget / CaS)."""
    T = thresholds if thresholds is not None else THRESHOLDS
    collision = asset.get("collision")
    if collision is None:
        return None
    c = collision if isinstance(collision, dict) else collision.model_dump()
    complex_tris = int(c.get("complex_triangles", 0))
    if c.get("complex_as_simple") and complex_tris > T["LD011_MAX_COMPLEX_TRIS"]:
        return Finding(
            asset_path=asset["asset_path"],
            rule_id="LD011",
            category="Mesh",
            severity="error",
            message=(
                f"Complex-as-simple collision cooks the {complex_tris:,}-triangle "
                "render mesh into the physics engine — very expensive per query."
            ),
            current={"complex_as_simple": True, "complex_triangles": complex_tris},
            recommended=_conf({"complex_as_simple": False}, "high"),
            estimated_saving=Saving(),
            auto_fixable=True,
            guidance=guidance_for("LD011", engine),
        )
    prims = int(c.get("primitive_count", 0))
    if prims > T["LD011_MAX_PRIMS"]:
        return Finding(
            asset_path=asset["asset_path"],
            rule_id="LD011",
            category="Mesh",
            severity="warning",
            message=(
                f"{prims} simple-collision primitives (budget {T['LD011_MAX_PRIMS']}) "
                "— simplify the collision hull."
            ),
            current={"primitive_count": prims},
            recommended=_conf(
                {"primitive_count": f"<= {T['LD011_MAX_PRIMS']}"}, "medium"
            ),
            estimated_saving=Saving(),
            auto_fixable=False,
            guidance=guidance_for("LD011", engine),
        )
    if not c.get("has_simple_collision") and int(asset.get("used_in_levels", 0)) > 0:
        return Finding(
            asset_path=asset["asset_path"],
            rule_id="LD011",
            category="Mesh",
            severity="warning",
            message=(
                "Placed mesh has no simple collision — either it needs a collision "
                "hull or it should be marked no-collision explicitly."
            ),
            current={"has_simple_collision": False},
            recommended=_conf({"has_simple_collision": True}, "medium"),
            estimated_saving=Saving(),
            auto_fixable=True,
            guidance=guidance_for("LD011", engine),
        )
    return None


# ── LD012 ─────────────────────────────────────────────────────────────────────


def check_ld012(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LD012: Dense opaque static mesh that should have Nanite enabled (UE5 only)."""
    if engine == "unity":
        return None  # Unity 6 has no Nanite equivalent (§13.9)
    T = thresholds if thresholds is not None else THRESHOLDS
    if asset.get("nanite_enabled") or asset.get("asset_type") != "StaticMesh":
        return None
    lods = _lods(asset)
    lod0_tris = (
        int(lods[0].get("triangles", 0))
        if lods
        else int(asset.get("triangle_count", 0) or 0)
    )
    if lod0_tris <= T["LD012_MIN_TRIS"]:
        return None
    blends = asset.get("used_material_blend_modes", [])
    if not blends or not all(b in _NANITE_OK_BLEND for b in blends):
        return None  # unknown or translucent slots — not a clean Nanite candidate
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LD012",
        category="Mesh",
        severity="info",
        message=(
            f"Dense opaque static mesh ({lod0_tris:,} tris) with Nanite disabled — "
            "Nanite would replace the hand-authored LOD chain and cull better."
        ),
        current={"nanite_enabled": False, "lod0_triangles": lod0_tris},
        recommended=_conf({"nanite_enabled": True}, "medium"),
        estimated_saving=Saving(),
        auto_fixable=True,
        guidance=guidance_for("LD012", engine),
    )


# ── LD013 ─────────────────────────────────────────────────────────────────────


def check_ld013(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LD013: Nanite is enabled but misconfigured (heavy fallback / bad materials)."""
    if engine == "unity":
        return None  # Unity 6 has no Nanite equivalent (§13.9)
    T = thresholds if thresholds is not None else THRESHOLDS
    if not asset.get("nanite_enabled"):
        return None
    # Material leg (error): a translucent-class slot silently renders non-Nanite.
    blends = asset.get("used_material_blend_modes", [])
    bad = sorted({b for b in blends if b in _NANITE_BAD_BLEND})
    if bad:
        return Finding(
            asset_path=asset["asset_path"],
            rule_id="LD013",
            category="Mesh",
            severity="error",
            message=(
                f"Nanite mesh has {', '.join(bad)} material slot(s) — those slots "
                "silently fall back to non-Nanite rendering."
            ),
            current={"incompatible_materials": bad},
            recommended=_conf(
                {"hint": "move the slot to a non-Nanite section or change blend mode"},
                "high",
            ),
            estimated_saving=Saving(),
            auto_fixable=False,
            guidance=guidance_for("LD013", engine),
        )
    # Fallback leg (warning): fallback mesh too heavy for RT / complex collision.
    fallback = asset.get("nanite_fallback_triangle_percent")
    if fallback is not None and float(fallback) > T["LD013_MAX_FALLBACK_PCT"]:
        return Finding(
            asset_path=asset["asset_path"],
            rule_id="LD013",
            category="Mesh",
            severity="warning",
            message=(
                f"Nanite fallback keeps {float(fallback):.0f}% of triangles "
                f"(budget {T['LD013_MAX_FALLBACK_PCT']:.0f}%) — raytracing and "
                "complex-collision consumers get a near-LOD0 mesh."
            ),
            current={"nanite_fallback_triangle_percent": round(float(fallback), 1)},
            recommended=_conf(
                {"fallback_percent": f"<= {T['LD013_MAX_FALLBACK_PCT']:.0f}"}, "high"
            ),
            estimated_saving=Saving(),
            auto_fixable=True,
            guidance=guidance_for("LD013", engine),
        )
    return None
