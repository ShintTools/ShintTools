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
