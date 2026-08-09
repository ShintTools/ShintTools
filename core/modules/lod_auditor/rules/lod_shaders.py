# core/modules/lod_auditor/rules/lod_shaders.py
#
# Shader rules: LS001 – LS015  (TDD Part 2 §19)
#
#   check_lsXXX(asset, engine="unreal", thresholds=None) -> Finding | None
#
# Engine-agnostic: every rule reads only asset["shader_stats"] (schema.ShaderStats)
# — a neutral shape both UE5 and Unity fill from their own compiled-shader APIs.
# Rules abstain when shader_stats is None, so materials-only payloads keep working.
# Findings attach to the material asset (category "Material") — no new asset_type.
#
# LS013-LS015 break that pattern on purpose: Unity has no shader-stats scanner
# at all (no ShaderUtil/Frame Debugger collector shipped), so shader_stats is
# always None for a Unity payload and LS001-LS012 never fire there. The only
# real shader signal Unity sends is `shading_model` (the assigned shader's
# name/path) on the material asset itself — these three classify it by name.

from lod_auditor.config import load_profile
from lod_auditor.guidance import guidance_for
from lod_auditor.schema import Finding, Saving

THRESHOLDS = load_profile()


def _ss(asset: dict) -> dict | None:
    ss = asset.get("shader_stats")
    if ss is None:
        return None
    return ss if isinstance(ss, dict) else ss.model_dump()


def _conf(recommended: dict, level: str) -> dict:
    recommended["confidence"] = level
    return recommended


# ── LS001 ─────────────────────────────────────────────────────────────────────


def check_ls001(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LS001: Shader instruction count over the pipeline-neutral budget."""
    T = thresholds if thresholds is not None else THRESHOLDS
    ss = _ss(asset)
    if ss is None:
        return None
    count = int(ss.get("instruction_count", 0))
    budget = T["LS001_MAX_INSTRUCTIONS"]
    if count <= budget:
        return None
    severity = "error" if count > T["LS001_ERROR_INSTRUCTIONS"] else "warning"
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LS001",
        category="Material",
        severity=severity,
        message=(
            f"Shader has {count} instructions (budget {budget}) — "
            f"{count - budget} over."
        ),
        current={"instruction_count": count},
        recommended=_conf({"instruction_count": f"<= {budget}"}, "high"),
        estimated_saving=Saving(shader_instructions=count - budget),
        auto_fixable=False,
        guidance=guidance_for("LS001", engine),
    )


# ── LS002 ─────────────────────────────────────────────────────────────────────


def check_ls002(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LS002: Texture fetch count over budget."""
    T = thresholds if thresholds is not None else THRESHOLDS
    ss = _ss(asset)
    if ss is None:
        return None
    fetches = int(ss.get("texture_fetch_count", 0))
    budget = T["LS002_MAX_FETCHES"]
    if fetches <= budget:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LS002",
        category="Material",
        severity="warning",
        message=(
            f"{fetches} texture fetches (budget {budget}) — bandwidth-bound; "
            "pack channels or share samples."
        ),
        current={"texture_fetch_count": fetches},
        recommended=_conf({"texture_fetch_count": f"<= {budget}"}, "high"),
        estimated_saving=Saving(shader_instructions=4 * (fetches - budget)),
        auto_fixable=False,
        guidance=guidance_for("LS002", engine),
    )


# ── LS003 ─────────────────────────────────────────────────────────────────────


def check_ls003(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LS003: Total branch count high."""
    T = thresholds if thresholds is not None else THRESHOLDS
    ss = _ss(asset)
    if ss is None:
        return None
    branches = int(ss.get("branch_count", 0))
    if branches <= T["LS003_MAX_BRANCHES"]:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LS003",
        category="Material",
        severity="info",
        message=(
            f"{branches} branches (budget {T['LS003_MAX_BRANCHES']}) — "
            "collapse into quality-level static switches where possible."
        ),
        current={"branch_count": branches},
        recommended=_conf({"branch_count": f"<= {T['LS003_MAX_BRANCHES']}"}, "high"),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LS003", engine),
    )


# ── LS004 ─────────────────────────────────────────────────────────────────────


def check_ls004(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LS004: Dynamic branching (divergence cost; escalates on mobile)."""
    T = thresholds if thresholds is not None else THRESHOLDS
    ss = _ss(asset)
    if ss is None:
        return None
    dynamic = int(ss.get("dynamic_branch_count", 0))
    if dynamic <= T["LS004_MAX_DYNAMIC_BRANCHES"]:
        return None
    severity = "warning" if T.get("profile") == "mobile" else "info"
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LS004",
        category="Material",
        severity=severity,
        message=(
            f"{dynamic} dynamic branches (budget {T['LS004_MAX_DYNAMIC_BRANCHES']}) "
            "— wave divergence is costly, especially on mobile."
        ),
        current={"dynamic_branch_count": dynamic},
        recommended=_conf(
            {"dynamic_branch_count": f"<= {T['LS004_MAX_DYNAMIC_BRANCHES']}"}, "high"
        ),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LS004", engine),
    )


# ── LS005 ─────────────────────────────────────────────────────────────────────


def check_ls005(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LS005: Loop with an unbounded or oversized iteration count."""
    T = thresholds if thresholds is not None else THRESHOLDS
    ss = _ss(asset)
    if ss is None:
        return None
    if int(ss.get("loop_count", 0)) <= 0:
        return None
    iterations = int(ss.get("max_loop_iterations", 0))
    cap = T["LS005_MAX_LOOP_ITERATIONS"]
    # Unbounded (0) or over the cap.
    if 0 < iterations <= cap:
        return None
    label = "unbounded" if iterations == 0 else f"{iterations} iterations"
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LS005",
        category="Material",
        severity="warning",
        message=(
            f"Shader loop is {label} (cap {cap}) — bound the loop or unroll it to "
            "a fixed, known count."
        ),
        current={"max_loop_iterations": iterations},
        recommended=_conf({"max_loop_iterations": f"<= {cap}"}, "high"),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LS005", engine),
    )


# ── LS006 ─────────────────────────────────────────────────────────────────────


def check_ls006(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LS006: High estimated register pressure (occupancy killer)."""
    T = thresholds if thresholds is not None else THRESHOLDS
    ss = _ss(asset)
    if ss is None:
        return None
    pressure = int(ss.get("estimated_register_pressure", 0))
    if pressure <= T["LS006_MAX_REGISTER_PRESSURE"]:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LS006",
        category="Material",
        severity="warning",
        message=(
            f"Estimated register pressure {pressure} (budget "
            f"{T['LS006_MAX_REGISTER_PRESSURE']}) — limits GPU occupancy."
        ),
        current={"estimated_register_pressure": pressure},
        recommended=_conf(
            {"estimated_register_pressure": f"<= {T['LS006_MAX_REGISTER_PRESSURE']}"},
            "medium",
        ),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LS006", engine),
    )


# ── LS007 ─────────────────────────────────────────────────────────────────────


def check_ls007(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LS007: Compiled shader variant count over budget (permutation blow-up)."""
    T = thresholds if thresholds is not None else THRESHOLDS
    ss = _ss(asset)
    if ss is None:
        return None
    variants = int(ss.get("variant_count", 0))
    budget = T["LS007_MAX_VARIANTS"]
    if variants <= budget:
        return None
    severity = "error" if variants > T["LS007_ERROR_VARIANTS"] else "warning"
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LS007",
        category="Material",
        severity=severity,
        message=(
            f"{variants} compiled shader variants (budget {budget}) — inflates "
            "build time and shader memory."
        ),
        current={"variant_count": variants},
        recommended=_conf({"variant_count": f"<= {budget}"}, "high"),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LS007", engine),
    )


# ── LS008 ─────────────────────────────────────────────────────────────────────


def check_ls008(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LS008: Full-float precision everywhere on mobile (half would do)."""
    T = thresholds if thresholds is not None else THRESHOLDS
    if T.get("profile") != "mobile":
        return None  # mobile-only rule
    ss = _ss(asset)
    if ss is None:
        return None
    ratio = float(ss.get("half_precision_ratio", 1.0))
    if ratio >= T["LS008_MIN_HALF_RATIO"]:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LS008",
        category="Material",
        severity="info",
        message=(
            f"Only {ratio * 100:.0f}% of float ops use half precision on mobile — "
            "most math can run at half precision for free bandwidth/ALU."
        ),
        current={"half_precision_ratio": round(ratio, 2)},
        recommended=_conf(
            {"half_precision_ratio": f">= {T['LS008_MIN_HALF_RATIO']}"}, "medium"
        ),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LS008", engine),
    )


# ── LS009 ─────────────────────────────────────────────────────────────────────


def check_ls009(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LS009: High engine-reported dead-code (stripped-instruction) ratio."""
    T = thresholds if thresholds is not None else THRESHOLDS
    ss = _ss(asset)
    if ss is None:
        return None
    ratio = float(ss.get("dead_code_ratio", 0.0))
    if ratio <= T["LS009_MAX_DEAD_CODE_RATIO"]:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LS009",
        category="Material",
        severity="info",
        message=(
            f"{ratio * 100:.0f}% of shader instructions are stripped as dead — "
            "the source graph carries unused work worth cleaning up."
        ),
        current={"dead_code_ratio": round(ratio, 2)},
        recommended=_conf(
            {"dead_code_ratio": f"<= {T['LS009_MAX_DEAD_CODE_RATIO']}"}, "medium"
        ),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LS009", engine),
    )


# ── LS010 ─────────────────────────────────────────────────────────────────────


def check_ls010(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LS010: Uniform parameters declared but never read."""
    T = thresholds if thresholds is not None else THRESHOLDS
    ss = _ss(asset)
    if ss is None:
        return None
    dead = int(ss.get("dead_parameter_count", 0))
    if dead <= T["LS010_MAX_DEAD_PARAMS"]:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LS010",
        category="Material",
        severity="info",
        message=(
            f"{dead} shader parameters are declared but never read — safe to "
            "delete from the material."
        ),
        current={"dead_parameter_count": dead},
        recommended=_conf({"dead_parameter_count": 0}, "high"),
        estimated_saving=Saving(),
        auto_fixable=True,
        guidance=guidance_for("LS010", engine),
    )


# ── LS011 ─────────────────────────────────────────────────────────────────────


def check_ls011(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LS011: Expensive math ops over their per-op budgets."""
    T = thresholds if thresholds is not None else THRESHOLDS
    ss = _ss(asset)
    if ss is None:
        return None
    counts = ss.get("expensive_op_counts", {}) or {}
    budgets: dict = T["LS011_OP_BUDGET"]
    overages: dict[str, int] = {}
    excess_total = 0
    for op, budget in budgets.items():
        used = int(counts.get(op, 0))
        if used > budget:
            overages[op] = used
            excess_total += used - budget
    if not overages:
        return None
    listed = ", ".join(f"{op}×{n}" for op, n in sorted(overages.items()))
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LS011",
        category="Material",
        severity="info",
        message=f"Expensive math over budget: {listed}. Precompute or approximate.",
        current={"expensive_op_counts": overages},
        recommended=_conf({"op_budget": budgets}, "high"),
        estimated_saving=Saving(shader_instructions=excess_total),
        auto_fixable=False,
        guidance=guidance_for("LS011", engine),
    )


# ── LS012 ─────────────────────────────────────────────────────────────────────


def check_ls012(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LS012: Dependent texture reads (UV computed from another fetch — stall)."""
    T = thresholds if thresholds is not None else THRESHOLDS
    ss = _ss(asset)
    if ss is None:
        return None
    dependent = int(ss.get("dependent_texture_reads", 0))
    if dependent <= T["LS012_MAX_DEPENDENT_READS"]:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LS012",
        category="Material",
        severity="warning",
        message=(
            f"{dependent} dependent texture reads (budget "
            f"{T['LS012_MAX_DEPENDENT_READS']}) — UV computed from a prior fetch "
            "stalls the texture pipeline."
        ),
        current={"dependent_texture_reads": dependent},
        recommended=_conf(
            {"dependent_texture_reads": f"<= {T['LS012_MAX_DEPENDENT_READS']}"}, "high"
        ),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LS012", engine),
    )


# ══════════════════════════════════════════════════════════════════════════════
# Shader-name classification (LS013 – LS015) — Unity only.
#
# No shader_stats scanner exists on the Unity side, so these classify the
# `shading_model` string on the material asset instead of reading measured
# stats. All three abstain on any other engine.
# ══════════════════════════════════════════════════════════════════════════════


def _is_unity(engine: str) -> bool:
    return engine.strip().lower() == "unity"


_LEGACY_SHADER_PREFIXES = (
    "Legacy Shaders/",
    "VertexLit",
    "Diffuse Fast",
    "Bumped Diffuse",
    "Bumped Specular",
    "Parallax Diffuse",
    "Decal",
    "Self-Illumin/",
    "Reflective/",
    "Transparent/Cutout/VertexLit",
    "Transparent/VertexLit",
)

_HEAVY_DESKTOP_SHADER_PREFIXES = (
    "Standard",
    "HDRP/Lit",
    "HDRP/LayeredLit",
    "Autodesk Interactive",
    "Nature/Terrain/Standard",
)


# ── LS013 ─────────────────────────────────────────────────────────────────────


def check_ls013(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LS013: Deprecated Unity built-in shader still assigned to a material."""
    if not _is_unity(engine):
        return None
    shading_model = str(asset.get("shading_model", "") or "")
    if not shading_model.startswith(_LEGACY_SHADER_PREFIXES):
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LS013",
        category="Material",
        severity="warning",
        message=(
            f"'{shading_model}' is a deprecated Unity built-in shader — it "
            "predates PBR, has no SRP Batcher / URP / HDRP path, and is a "
            "removal candidate in newer Unity LTS builds."
        ),
        current={"shading_model": shading_model},
        recommended={
            "hint": "reassign Standard (Built-in) or the project's URP/HDRP Lit shader"
        },
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LS013", engine),
    )


# ── LS014 ─────────────────────────────────────────────────────────────────────


def check_ls014(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LS014: Desktop-grade shader assigned while auditing under the mobile profile."""
    T = thresholds if thresholds is not None else THRESHOLDS
    if not _is_unity(engine) or T.get("profile") != "mobile":
        return None
    shading_model = str(asset.get("shading_model", "") or "")
    if not shading_model.startswith(_HEAVY_DESKTOP_SHADER_PREFIXES):
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LS014",
        category="Material",
        severity="warning",
        message=(
            f"'{shading_model}' is a full desktop PBR shader on a mobile-profile "
            "audit — its per-pixel PBR terms and probe blending cost far more "
            "than a Mobile/ or URP Lit (mobile quality preset) equivalent."
        ),
        current={"shading_model": shading_model},
        recommended={
            "hint": "switch to a Mobile/ shader or URP Lit with the mobile preset"
        },
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LS014", engine),
    )


# ── LS015 ─────────────────────────────────────────────────────────────────────


def check_ls015(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LS015: Mobile/ shader assigned while auditing under a non-mobile profile."""
    T = thresholds if thresholds is not None else THRESHOLDS
    if not _is_unity(engine) or T.get("profile") == "mobile":
        return None
    shading_model = str(asset.get("shading_model", "") or "")
    if not shading_model.startswith("Mobile/"):
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LS015",
        category="Material",
        severity="info",
        message=(
            f"'{shading_model}' is a Mobile/ shader on a non-mobile-profile "
            "audit — its cut corners (no real specular, baked-only reflections) "
            "buy nothing on this target and leave visual quality on the table."
        ),
        current={"shading_model": shading_model},
        recommended={
            "hint": "switch to Standard or the project's URP/HDRP Lit shader"
        },
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LS015", engine),
    )
