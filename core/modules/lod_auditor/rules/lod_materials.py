# core/modules/lod_auditor/rules/lod_materials.py
#
# Material LOD rules: LM001 – LM003
#
# Each rule is a pure function:
#   check_lmXXX(asset: dict) -> Finding | None

from lod_auditor.config import load_profile
from lod_auditor.guidance import guidance_for
from lod_auditor.schema import Finding, Saving

# Thresholds are loaded from YAML — see config/thresholds_default.yaml.
THRESHOLDS = load_profile()


# ── LM001 ─────────────────────────────────────────────────────────────────────


def check_lm001(asset: dict, engine: str = "unreal") -> Finding | None:
    """LM001: Shader instruction count exceeds the budget for its blend mode."""
    instruction_count: int = asset.get("instruction_count", 0)
    blend_mode: str = asset.get("blend_mode", "Opaque")

    budget_map: dict = THRESHOLDS["LM001_BUDGET_BY_BLEND_MODE"]
    budget: int = budget_map.get(blend_mode, THRESHOLDS["LM001_DEFAULT_BUDGET"])

    if instruction_count <= budget:
        return None

    excess: int = instruction_count - budget

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LM001",
        category="Material",
        severity="warning",
        message=(
            f"{instruction_count} shader instructions; "
            f"budget for '{blend_mode}' material: {budget}. "
            f"{excess} instructions over budget."
        ),
        current={"instruction_count": instruction_count},
        recommended={"instruction_count": f"<= {budget}"},
        estimated_saving=Saving(vram_mb=0.0, shader_instructions=excess),
        auto_fixable=False,
        guidance=guidance_for("LM001", engine),
    )


# ── LM002 ─────────────────────────────────────────────────────────────────────


def check_lm002(asset: dict, engine: str = "unreal") -> Finding | None:
    """LM002: Same texture sampled more than once (duplicate sampler slot usage).

    Requires the plugin to populate ``texture_samples`` on the asset dict.
    If the field is absent or empty the rule is skipped — it cannot detect
    duplicates it was never given. Ensure the plugin sends all texture sample
    paths when submitting Material assets.
    """
    raw_samples: list = asset.get("texture_samples", [])
    if not raw_samples:
        return None

    # Count occurrences of each texture path
    texture_count: dict[str, int] = {}
    for sample in raw_samples:
        if isinstance(sample, dict):
            tex_path: str = sample.get("texture", "")
        else:
            tex_path = getattr(sample, "texture", "")
        if tex_path:
            texture_count[tex_path] = texture_count.get(tex_path, 0) + 1

    duplicates: dict[str, int] = {
        tex: count for tex, count in texture_count.items() if count > 1
    }

    if not duplicates:
        return None

    dup_summary: str = ", ".join(
        f"{tex.split('/')[-1]} (×{count})" for tex, count in duplicates.items()
    )

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LM002",
        category="Material",
        severity="warning",
        message=(
            f"Duplicate texture sample(s): {dup_summary}. "
            "Each duplicate wastes a sampler slot — UE5 allows 16 per material."
        ),
        current={"duplicate_textures": list(duplicates.keys())},
        recommended={"duplicate_textures": []},
        estimated_saving=Saving(vram_mb=0.0, shader_instructions=0),
        auto_fixable=True,
        guidance=None,
    )


# ── LM003 ─────────────────────────────────────────────────────────────────────


def check_lm003(asset: dict, engine: str = "unreal") -> Finding | None:
    """LM003: Non-instanced material shared across many primitives."""
    is_material_instance: bool = asset.get("is_material_instance", False)
    used_by_primitives: int = asset.get("used_by_primitives", 1)
    threshold: int = THRESHOLDS["LM003_PRIMITIVES_THRESHOLD"]

    if is_material_instance or used_by_primitives < threshold:
        return None

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LM003",
        category="Material",
        severity="info",
        message=(
            f"Non-instanced material used on {used_by_primitives} primitives. "
            "A Material Instance enables per-object parameter overrides "
            "and reduces draw call overhead."
        ),
        current={
            "is_material_instance": False,
            "used_by_primitives": used_by_primitives,
        },
        recommended={"is_material_instance": True},
        estimated_saving=Saving(vram_mb=0.0, shader_instructions=0),
        auto_fixable=False,
        guidance=guidance_for("LM003", engine),
    )


# ── Shared helpers for the material-completion rules (LM004–LM014) ─────────────

_SEVERITY_RANK = {"info": 0, "warning": 1, "error": 2}


def _conf(recommended: dict, level: str) -> dict:
    recommended["confidence"] = level
    return recommended


# ── LM004 ─────────────────────────────────────────────────────────────────────


def check_lm004(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LM004: Texture sampler count over the budget for the blend mode."""
    T = thresholds if thresholds is not None else THRESHOLDS
    samplers = int(asset.get("sampler_count", 0) or 0)
    if samplers <= 0:
        return None
    blend = asset.get("blend_mode", "Opaque")
    budget = T["LM004_MAX_SAMPLERS"].get(blend, T["LM004_MAX_SAMPLERS"]["Opaque"])
    if samplers <= budget:
        return None
    severity = "error" if samplers > T["LM004_ERROR_SAMPLERS"] else "warning"
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LM004",
        category="Material",
        severity=severity,
        message=(
            f"{samplers} texture samplers on a '{blend}' material (budget {budget}"
            + (
                f", hard limit {T['LM004_ERROR_SAMPLERS']}"
                if severity == "error"
                else ""
            )
            + ") — share wrap samplers or pack channels."
        ),
        current={"sampler_count": samplers},
        recommended=_conf({"sampler_count": f"<= {budget}"}, "high"),
        estimated_saving=Saving(shader_instructions=4 * (samplers - budget)),
        auto_fixable=True,
        guidance=guidance_for("LM004", engine),
    )


# ── LM005 ─────────────────────────────────────────────────────────────────────


def check_lm005(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LM005: Material graph complexity (node count / depth) — maintainability."""
    T = thresholds if thresholds is not None else THRESHOLDS
    nodes = int(asset.get("graph_node_count", 0) or 0)
    depth = int(asset.get("graph_depth", 0) or 0)
    over_nodes = nodes > T["LM005_MAX_NODES"]
    over_depth = depth > T["LM005_MAX_DEPTH"]
    if not (over_nodes or over_depth):
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LM005",
        category="Material",
        severity="info",
        message=(
            f"Large material graph ({nodes} nodes, depth {depth}) — hard to "
            "maintain and reason about; consider factoring into functions."
        ),
        current={"graph_node_count": nodes, "graph_depth": depth},
        recommended=_conf({"graph_node_count": f"<= {T['LM005_MAX_NODES']}"}, "high"),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LM005", engine),
    )


# ── LM006 ─────────────────────────────────────────────────────────────────────


def check_lm006(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LM006: Deeply nested material functions hide cost and break attribution."""
    T = thresholds if thresholds is not None else THRESHOLDS
    depth = int(asset.get("function_call_depth", 0) or 0)
    if depth <= T["LM006_MAX_DEPTH"]:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LM006",
        category="Material",
        severity="info",
        message=(
            f"Material function nesting is {depth} deep (budget "
            f"{T['LM006_MAX_DEPTH']}) — deep nesting hides cost; flatten hot paths."
        ),
        current={"function_call_depth": depth},
        recommended=_conf(
            {"function_call_depth": f"<= {T['LM006_MAX_DEPTH']}"}, "high"
        ),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LM006", engine),
    )


# ── LM007 ─────────────────────────────────────────────────────────────────────


def check_lm007(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LM007: Too many material layers (each multiplies base-pass cost)."""
    T = thresholds if thresholds is not None else THRESHOLDS
    layers = int(asset.get("layer_count", 0) or 0)
    blend = asset.get("blend_mode", "Opaque")
    budget = T["LM007_MAX_LAYERS"].get(blend, T["LM007_MAX_LAYERS"]["_default"])
    if layers <= budget:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LM007",
        category="Material",
        severity="warning",
        message=(
            f"{layers} material layers on a '{blend}' material (budget {budget}) — "
            "each layer multiplies base-pass cost."
        ),
        current={"layer_count": layers},
        recommended=_conf({"layer_count": f"<= {budget}"}, "high"),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LM007", engine),
    )


# ── LM008 ─────────────────────────────────────────────────────────────────────


def check_lm008(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LM008: Layered blend is what pushes an otherwise-fine material toward budget.

    Suppressed by the orchestrator whenever LM001 fires on the same asset
    (one finding per root cause — see lod_orchestrator._SUPPRESSED_BY).
    """
    T = thresholds if thresholds is not None else THRESHOLDS
    layers = int(asset.get("layer_count", 0) or 0)
    if layers < 2:
        return None
    base_pass = int(asset.get("base_pass_instructions", 0) or 0)
    blend = asset.get("blend_mode", "Opaque")
    budget = T["LM001_BUDGET_BY_BLEND_MODE"].get(blend, T["LM001_DEFAULT_BUDGET"])
    if base_pass <= budget * T["LM008_BUDGET_FACTOR"]:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LM008",
        category="Material",
        severity="warning",
        message=(
            f"{layers} blended layers drive the base pass to {base_pass} "
            f"instructions (nearing the {budget} budget) — the blend is the cost."
        ),
        current={"layer_count": layers, "base_pass_instructions": base_pass},
        recommended=_conf(
            {"base_pass_instructions": f"<= {int(budget * 0.8)}"}, "medium"
        ),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LM008", engine),
    )


# ── LM009 ─────────────────────────────────────────────────────────────────────


def check_lm009(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LM009: RVT setup cost on a material used by too few primitives to amortise."""
    T = thresholds if thresholds is not None else THRESHOLDS
    if not asset.get("uses_rvt"):
        return None
    prims = int(asset.get("used_by_primitives", -1))
    if prims < 0 or prims >= T["LM009_MIN_PRIMITIVES"]:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LM009",
        category="Material",
        severity="info",
        message=(
            f"Runtime Virtual Texture used by only {prims} primitives — the RVT "
            "setup cost isn't amortised at this scale."
        ),
        current={"uses_rvt": True, "used_by_primitives": prims},
        recommended=_conf(
            {"hint": "drop RVT or apply it to a larger primitive set"}, "high"
        ),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LM009", engine),
    )


# ── LM010 ─────────────────────────────────────────────────────────────────────


def check_lm010(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LM010: Many dynamic parameters, worse on a non-instanced material."""
    T = thresholds if thresholds is not None else THRESHOLDS
    dynamic = int(asset.get("dynamic_parameter_count", 0) or 0)
    if dynamic <= T["LM010_MAX_DYNAMIC"]:
        return None
    not_instanced = not asset.get("is_material_instance", False)
    severity = "warning" if not_instanced else "info"
    tail = (
        " on a non-instanced material — forces per-draw uniform updates"
        if not_instanced
        else ""
    )
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LM010",
        category="Material",
        severity=severity,
        message=(
            f"{dynamic} dynamic parameters "
            f"(budget {T['LM010_MAX_DYNAMIC']}){tail}."
        ),
        current={"dynamic_parameter_count": dynamic},
        recommended=_conf(
            {"dynamic_parameter_count": f"<= {T['LM010_MAX_DYNAMIC']}"}, "high"
        ),
        estimated_saving=Saving(),
        auto_fixable=bool(not_instanced),
        guidance=guidance_for("LM010", engine),
    )


# ── LM011 ─────────────────────────────────────────────────────────────────────


def check_lm011(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LM011: Static switch count / permutation explosion (build size + memory)."""
    T = thresholds if thresholds is not None else THRESHOLDS
    switches = int(asset.get("static_switch_count", 0) or 0)
    permutations = int(asset.get("static_permutation_estimate", 0) or 0)
    over_switches = switches > T["LM011_MAX_SWITCHES"]
    over_perms = permutations > T["LM011_ERROR_PERMUTATIONS"]
    if not (over_switches or over_perms):
        return None
    severity = "error" if over_perms else "warning"
    build_mb = 0.0
    if over_perms:
        build_mb = round(
            (permutations - T["LM011_ERROR_PERMUTATIONS"])
            * T["LM011_MB_PER_PERMUTATION"],
            2,
        )
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LM011",
        category="Material",
        severity=severity,
        message=(
            f"{switches} static switches ≈ {permutations} permutations "
            f"(budget {T['LM011_MAX_SWITCHES']} switches / "
            f"{T['LM011_ERROR_PERMUTATIONS']} permutations) — collapse into "
            "quality-level branches or split the material."
        ),
        current={
            "static_switch_count": switches,
            "static_permutation_estimate": permutations,
        },
        recommended=_conf(
            {"static_switch_count": f"<= {T['LM011_MAX_SWITCHES']}"}, "high"
        ),
        estimated_saving=Saving(build_size_mb=build_mb),
        auto_fixable=False,
        guidance=guidance_for("LM011", engine),
    )


# ── LM012 ─────────────────────────────────────────────────────────────────────


def check_lm012(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LM012: Checked usage flags never hit by any referencing component type."""
    T = thresholds if thresholds is not None else THRESHOLDS
    unused = asset.get("usage_flags_unused", []) or []
    if not unused:
        return None
    build_mb = round(len(unused) * T["LM011_MB_PER_PERMUTATION"], 2)
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LM012",
        category="Material",
        severity="warning",
        message=(
            f"Usage flag(s) checked but never used by any referencer: "
            f"{', '.join(unused)} — each doubles the compiled permutation set."
        ),
        current={"usage_flags_unused": list(unused)},
        recommended=_conf({"usage_flags_unused": []}, "high"),
        estimated_saving=Saving(build_size_mb=build_mb),
        auto_fixable=True,
        guidance=guidance_for("LM012", engine),
    )


# ── LM013 ─────────────────────────────────────────────────────────────────────


def check_lm013(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LM013: Expensive material nodes present (table-driven severity)."""
    T = thresholds if thresholds is not None else THRESHOLDS
    counts = asset.get("expensive_node_counts", {}) or {}
    severities: dict = T["LM013_NODE_SEVERITY"]
    hits: list[str] = []
    worst = "info"
    for node, n in counts.items():
        if int(n) <= 0 or node not in severities:
            continue
        hits.append(f"{node}×{int(n)}")
        node_sev = severities[node]
        if _SEVERITY_RANK[node_sev] > _SEVERITY_RANK[worst]:
            worst = node_sev
    if not hits:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LM013",
        category="Material",
        severity=worst,
        message=(
            f"Expensive material nodes: {', '.join(sorted(hits))}. "
            "Bake, approximate, or gate them behind quality switches."
        ),
        current={"expensive_nodes": sorted(hits)},
        recommended=_conf({"hint": "reduce or bake the flagged nodes"}, "high"),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LM013", engine),
    )


# ── LM014 ─────────────────────────────────────────────────────────────────────


def check_lm014(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LM014: Vertex-shader cost too high (WPO-heavy material)."""
    T = thresholds if thresholds is not None else THRESHOLDS
    vs = int(asset.get("vertex_shader_instructions", 0) or 0)
    if vs <= T["LM014_MAX_VS_INSTRUCTIONS"]:
        return None
    worst_verts = int(asset.get("max_referencer_vertex_count", 0) or 0)
    tail = f" on a {worst_verts:,}-vertex mesh" if worst_verts else ""
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LM014",
        category="Material",
        severity="warning",
        message=(
            f"Vertex shader runs {vs} instructions (budget "
            f"{T['LM014_MAX_VS_INSTRUCTIONS']}){tail} — costed per vertex."
        ),
        current={"vertex_shader_instructions": vs},
        recommended=_conf(
            {"vertex_shader_instructions": f"<= {T['LM014_MAX_VS_INSTRUCTIONS']}"},
            "high",
        ),
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LM014", engine),
    )
