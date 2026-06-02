# core/modules/lod_auditor/rules/lod_meshes.py
#
# Mesh LOD rules: LD001 – LD003
#
# Each rule is a pure function:
#   check_ldXXX(asset: dict) -> Finding | None

from lod_auditor.schema import Finding, Saving

# ── Thresholds ────────────────────────────────────────────────────────────────

THRESHOLDS: dict = {
    # LD001 — minimum number of LOD levels before we flag the mesh
    "LD001_MIN_LOD_COUNT": 2,
    # LD003 — LOD0 triangle budget by mesh size class.
    # Each entry is (max_bounds_radius, max_triangles).
    # The list is checked in order; the first matching radius wins.
    # Units: UE5 world units (1 unit ≈ 1 cm by convention).
    "LD003_TRIANGLE_BUDGET": [
        (50.0, 2_000),  # very small props (coins, screws, small decor)
        (150.0, 8_000),  # small props (chairs, barrels, crates)
        (500.0, 25_000),  # medium props (cars, trees, room furniture)
        (float("inf"), 80_000),  # large / hero meshes (buildings, terrain chunks)
    ],
}


# ── LT001 ─────────────────────────────────────────────────────────────────────


def check_ld001(asset: dict) -> Finding | None:
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


def check_ld002(asset: dict) -> Finding | None:
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


def check_ld003(asset: dict) -> Finding | None:
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
        guidance=(
            f"Target <= {budget:,} triangles using the engine's mesh reduction "
            "tools (UE5 Simplygon / built-in auto-LOD). "
            "Review whether the mesh silhouette can be simplified without "
            "losing the intended visual fidelity at the closest view distance."
        ),
    )
