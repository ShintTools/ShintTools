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


# UE5-only concepts. Unity has no Material Instance, no material usage flags,
# no Material Layers and no Runtime Virtual Texture, so these rules describe
# machinery that does not exist there. They stayed quiet on Unity only because
# the collector sent none of their inputs — an accident, not a decision: the
# moment a Unity payload carries used_by_primitives (which the collector spec
# now asks for), LM003 would start telling Unity users to convert a material
# into an Unreal Material Instance. Gate on the concept, not on the data.
def _unreal_only(engine: str) -> bool:
    return engine.strip().lower() not in {"unity"}


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
    if not _unreal_only(engine):
        return None
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
    if not _unreal_only(engine):
        return None
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
    if not _unreal_only(engine):
        return None
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
    if not _unreal_only(engine):
        return None
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
    if not _unreal_only(engine):
        return None
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
    if not _unreal_only(engine):
        return None
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
        # Contract change (v2.1): recommended carries the CONCRETE flags the
        # client must clear (as a machine-readable list under `clear_usage_flags`)
        # so the in-editor fixer can call SetMaterialUsage(flag, false) directly
        # without re-deriving them. The client is the source of `unused` (it did
        # the referencer analysis), so we simply echo it back as the action list.
        recommended=_conf(
            {"usage_flags_unused": [], "clear_usage_flags": list(unused)}, "high"
        ),
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


# ══════════════════════════════════════════════════════════════════════════════
# Unity-native material rules (LM015 – LM018)
#
# LM001-LM014 above are UE5-shaped: material instances, usage flags, layers,
# RVT, WPO. None of those exist in Unity, so a Unity material scan could reach
# exactly one rule (LM004) and nothing it produced was applicable — the panel's
# Materials tab had no fixes to offer at all.
#
# These four price the levers Unity actually exposes on a Material, all of them
# settable from the editor without touching the shader. They abstain on any
# other engine rather than translate a concept that has no counterpart.
# ══════════════════════════════════════════════════════════════════════════════


def _is_unity(engine: str) -> bool:
    return engine.strip().lower() == "unity"


# ── LM015 ─────────────────────────────────────────────────────────────────────


def check_lm015(
    asset: dict, engine: str = "unreal", thresholds: dict | None = None
) -> Finding | None:
    """LM015: GPU Instancing off on a material shared by many renderers."""
    T = thresholds if thresholds is not None else THRESHOLDS
    if not _is_unity(engine):
        return None

    instancing = asset.get("gpu_instancing")
    if instancing is None or instancing:
        return None

    prims = int(asset.get("used_by_primitives", -1))
    if prims < T["LM015_MIN_PRIMITIVES"]:
        return None

    # Under URP/HDRP the SRP Batcher takes precedence: a batcher-compatible
    # material ignores the instancing flag entirely, so recommending it there
    # would be a fix that changes nothing. Only claim the win where it lands —
    # the Built-in pipeline, or a material the batcher cannot take.
    pipeline = str(asset.get("render_pipeline", "") or "").strip().lower()
    srp_compatible = asset.get("srp_batcher_compatible")
    if pipeline in {"urp", "hdrp"} and srp_compatible is not False:
        return None
    if not pipeline and srp_compatible is not False:
        return None  # cannot tell which path this material takes

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LM015",
        category="Material",
        severity="warning",
        message=(
            f"GPU Instancing is off on a material shared by {prims} renderers — "
            "each one costs its own draw call. Enabling it batches identical "
            "mesh + material pairs into a single call."
        ),
        current={"gpu_instancing": False, "used_by_primitives": prims},
        recommended={"enable_instancing": True},
        estimated_saving=Saving(),
        auto_fixable=True,
        guidance=guidance_for("LM015", engine),
    )


# ── LM016 ─────────────────────────────────────────────────────────────────────


def check_lm016(asset: dict, engine: str = "unreal") -> Finding | None:
    """LM016: Material is not SRP Batcher compatible under URP/HDRP."""
    if not _is_unity(engine):
        return None
    if asset.get("srp_batcher_compatible") is not False:
        return None

    pipeline = str(asset.get("render_pipeline", "") or "").strip().lower()
    if pipeline not in {"urp", "hdrp"}:
        return None  # the batcher only exists on the scriptable pipelines

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LM016",
        category="Material",
        severity="warning",
        message=(
            "Shader is not SRP Batcher compatible — every renderer using this "
            "material re-uploads its constants and breaks the batch. Move the "
            "per-material properties into the UnityPerMaterial CBUFFER."
        ),
        current={"srp_batcher_compatible": False, "render_pipeline": pipeline},
        # Deliberately advisory: compatibility is decided by how the shader
        # declares its constant buffer, which no material property can change.
        recommended={},
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LM016", engine),
    )


# ── LM017 ─────────────────────────────────────────────────────────────────────

# Unity's queue ranges. A material whose queue sits in the wrong band either
# sorts against the wrong set (transparents drawn before the opaques they
# blend with) or forfeits the early-Z the opaque pass depends on.
_QUEUE_GEOMETRY: int = 2000
_QUEUE_ALPHATEST: int = 2450
_QUEUE_TRANSPARENT: int = 3000
_QUEUE_BANDS: dict[str, tuple[int, int, int]] = {
    # blend mode -> (band start, band end exclusive, canonical queue)
    "opaque": (_QUEUE_GEOMETRY, _QUEUE_ALPHATEST, _QUEUE_GEOMETRY),
    "masked": (_QUEUE_ALPHATEST, _QUEUE_TRANSPARENT, _QUEUE_ALPHATEST),
    "cutout": (_QUEUE_ALPHATEST, _QUEUE_TRANSPARENT, _QUEUE_ALPHATEST),
    "transparent": (_QUEUE_TRANSPARENT, 4000, _QUEUE_TRANSPARENT),
    "additive": (_QUEUE_TRANSPARENT, 4000, _QUEUE_TRANSPARENT),
    "fade": (_QUEUE_TRANSPARENT, 4000, _QUEUE_TRANSPARENT),
}


def check_lm017(asset: dict, engine: str = "unreal") -> Finding | None:
    """LM017: Render queue override contradicts the material's blend mode."""
    if not _is_unity(engine):
        return None

    queue = asset.get("render_queue")
    if queue is None:
        return None
    queue = int(queue)
    if queue < 0:
        return None  # -1 = "from shader", i.e. no override at all

    band = _QUEUE_BANDS.get(str(asset.get("blend_mode", "") or "").strip().lower())
    if band is None:
        return None

    start, end, canonical = band
    if start <= queue < end:
        return None

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LM017",
        category="Material",
        severity="warning",
        message=(
            f"Render queue is overridden to {queue}, outside the "
            f"{start}–{end - 1} band its '{asset.get('blend_mode')}' blend mode "
            f"sorts in. Opaques drawn late lose early-Z; transparents drawn "
            f"early blend against an unfinished frame."
        ),
        current={"render_queue": queue, "blend_mode": asset.get("blend_mode")},
        recommended={"render_queue": canonical},
        estimated_saving=Saving(),
        auto_fixable=True,
        guidance=guidance_for("LM017", engine),
    )


# ── LM018 ─────────────────────────────────────────────────────────────────────


def check_lm018(asset: dict, engine: str = "unreal") -> Finding | None:
    """LM018: Double-sided GI on a single-sided material costs bake time."""
    if not _is_unity(engine):
        return None

    if asset.get("double_sided_gi") is not True:
        return None
    # Only wasteful when the material itself is single-sided: a genuinely
    # two-sided surface needs both faces to receive and bounce light.
    if asset.get("two_sided") is not False:
        return None

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LM018",
        category="Material",
        severity="info",
        message=(
            "Double Sided Global Illumination is on for a single-sided "
            "material — the lightmapper traces both faces of geometry that "
            "only renders one, lengthening every bake for no visual change."
        ),
        current={"double_sided_gi": True, "two_sided": False},
        recommended={"double_sided_gi": False},
        estimated_saving=Saving(),
        auto_fixable=True,
        guidance=guidance_for("LM018", engine),
    )


# ══════════════════════════════════════════════════════════════════════════════
# Shading-model classification (LM019 – LM020) — Unity only.
#
# The Unity material scan sends exactly four real fields today: blend_mode,
# sampler_count, two_sided and shading_model (the assigned shader's name).
# LM001-LM014 above read fields the client never sends for a Unity payload
# (instruction_count, graph_node_count, layer_count, ...) — they only fire on
# UE5. LM004/LM015-LM018 already mine the four real fields; these two mine the
# one still mostly unused: shading_model.
#
# NOTE on `two_sided`: the Unity collector populates this field from
# Material.doubleSidedGI, not the render-face/culling mode — confirmed against
# AssetOptimizerMaterialsScannerData.cs. LM020 reads it as what it actually is.
# ══════════════════════════════════════════════════════════════════════════════

_URP_SHADER_PREFIXES = ("Universal Render Pipeline/", "Shader Graphs/URP")
_HDRP_SHADER_PREFIXES = ("HDRP/",)
_BUILTIN_SHADER_PREFIXES = (
    "Standard",
    "Legacy Shaders/",
    "Mobile/",
    "Nature/",
    "Particles/",
    "Skybox/",
    "UI/",
    "Sprites/",
    "FX/",
    "Autodesk Interactive",
)

# Folder-name markers that declare which pipeline a project has adopted.
# Deliberately narrow — only an unambiguous folder segment counts, so a
# studio's own naming conventions are never second-guessed.
_URP_PATH_MARKERS = ("/URP/", "_URP/")
_HDRP_PATH_MARKERS = ("/HDRP/", "_HDRP/")

# Shader families that never sample scene GI, so paying for Double Sided GI on
# them buys nothing.
_NO_GI_SHADER_PREFIXES = (
    "Unlit/",
    "Universal Render Pipeline/Unlit",
    "HDRP/Unlit",
    "UI/",
    "Skybox/",
    "Sprites/",
    "Particles/",
    "FX/",
)


def _shader_family(shading_model: str) -> str | None:
    s = shading_model or ""
    if s.startswith(_URP_SHADER_PREFIXES):
        return "urp"
    if s.startswith(_HDRP_SHADER_PREFIXES):
        return "hdrp"
    if s.startswith(_BUILTIN_SHADER_PREFIXES):
        return "builtin"
    return None


# ── LM019 ─────────────────────────────────────────────────────────────────────


def check_lm019(asset: dict, engine: str = "unreal") -> Finding | None:
    """LM019: Shader family contradicts the pipeline the asset's folder declares."""
    if not _is_unity(engine):
        return None
    path = str(asset.get("asset_path", "") or "")
    family = _shader_family(str(asset.get("shading_model", "") or ""))
    if family is None:
        return None
    declared: str | None = None
    if any(marker in path for marker in _URP_PATH_MARKERS):
        declared = "urp"
    elif any(marker in path for marker in _HDRP_PATH_MARKERS):
        declared = "hdrp"
    if declared is None or declared == family:
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LM019",
        category="Material",
        severity="warning",
        message=(
            f"Material lives under a folder that declares the {declared.upper()} "
            f"pipeline but is assigned a '{asset.get('shading_model')}' shader "
            f"({family} family) — usually a pipeline migration left half-done."
        ),
        current={
            "shading_model": asset.get("shading_model"),
            "folder_pipeline": declared,
        },
        recommended={"hint": f"reassign a {declared.upper()} shader"},
        estimated_saving=Saving(),
        auto_fixable=False,
        guidance=guidance_for("LM019", engine),
    )


# ── LM020 ─────────────────────────────────────────────────────────────────────


def check_lm020(asset: dict, engine: str = "unreal") -> Finding | None:
    """LM020: Double Sided GI is on for a shader family that never contributes to GI."""
    if not _is_unity(engine):
        return None
    if asset.get("two_sided") is not True:
        return None
    shading_model = str(asset.get("shading_model", "") or "")
    if not shading_model.startswith(_NO_GI_SHADER_PREFIXES):
        return None
    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LM020",
        category="Material",
        severity="info",
        message=(
            f"Double Sided Global Illumination is on for a '{shading_model}' "
            "material — unlit/UI/particle shaders never sample or contribute to "
            "baked GI, so the lightmapper's extra pass over both faces buys "
            "nothing."
        ),
        current={"double_sided_gi": True, "shading_model": shading_model},
        recommended={"double_sided_gi": False},
        estimated_saving=Saving(),
        auto_fixable=True,
        guidance=guidance_for("LM020", engine),
    )
