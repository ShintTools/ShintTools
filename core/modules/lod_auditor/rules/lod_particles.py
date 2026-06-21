# core/modules/lod_auditor/rules/lod_particles.py
#
# VFX / Particle system LOD rules: LV001 – LV003
#
# Targets Niagara (UE5) and Particle Systems (Unity). The plugin sends
# either NiagaraSystem assets or ParticleSystem assets via the existing
# /assets/lod/audit endpoint.

from lod_auditor.config import load_profile
from lod_auditor.schema import Finding, Saving

THRESHOLDS = load_profile()

# Default budgets when the profile YAML omits the keys — keep the rule
# functional out-of-the-box without requiring every profile to specify
# particle thresholds.
_DEFAULT_MAX_PARTICLES_GPU = 100_000
_DEFAULT_MAX_PARTICLES_CPU = 5_000
_DEFAULT_MAX_EMITTERS_PER_SYSTEM = 8


# ── LV001 ─────────────────────────────────────────────────────────────────────


def check_lv001(asset: dict, engine: str = "unreal") -> Finding | None:
    """LV001: Particle system exceeds the max-particles budget for its sim type."""
    if asset.get("asset_type") not in ("NiagaraSystem", "ParticleSystem"):
        return None

    sim_target: str = asset.get("sim_target", "CPU")  # "CPU" | "GPU"
    max_particles: int = asset.get("max_particles", 0)

    if sim_target == "GPU":
        budget = THRESHOLDS.get("LV001_MAX_PARTICLES_GPU", _DEFAULT_MAX_PARTICLES_GPU)
    else:
        budget = THRESHOLDS.get("LV001_MAX_PARTICLES_CPU", _DEFAULT_MAX_PARTICLES_CPU)

    if max_particles <= budget:
        return None

    excess: int = max_particles - budget

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LV001",
        category="VFX",
        severity="warning",
        message=(
            f"{sim_target} particle system exceeds {budget:,} particle budget "
            f"({max_particles:,} active, {excess:,} over). "
            "Sustained spawn rates above the budget cause frametime spikes."
        ),
        current={"sim_target": sim_target, "max_particles": max_particles},
        recommended={"max_particles": f"<= {budget}"},
        estimated_saving=Saving(vram_mb=0.0, shader_instructions=0),
        auto_fixable=False,
        guidance=(
            "Reduce spawn rate, shorten lifetime, or move long-lived emitters "
            "to a separate system so the budget is per-effect, not per-asset."
        ),
    )


# ── LV002 ─────────────────────────────────────────────────────────────────────


def check_lv002(asset: dict, engine: str = "unreal") -> Finding | None:
    """LV002: CPU sim used where GPU would scale far better.

    Heuristic: any CPU emitter declaring > 1 000 particles should be on
    GPU unless it interacts with collision/audio/CPU-only modules.
    """
    if asset.get("asset_type") not in ("NiagaraSystem", "ParticleSystem"):
        return None
    if asset.get("sim_target", "CPU") != "CPU":
        return None
    if asset.get("uses_cpu_only_modules", False):
        return None

    max_particles: int = asset.get("max_particles", 0)
    threshold = THRESHOLDS.get("LV002_CPU_PROMOTE_TO_GPU", 1_000)
    if max_particles <= threshold:
        return None

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LV002",
        category="VFX",
        severity="info",
        message=(
            f"CPU particle system runs {max_particles:,} particles. "
            "GPU sim scales linearly with particle count and frees CPU cores "
            "for gameplay logic."
        ),
        current={"sim_target": "CPU", "max_particles": max_particles},
        recommended={"sim_target": "GPU"},
        estimated_saving=Saving(vram_mb=0.0, shader_instructions=0),
        auto_fixable=False,
        guidance=(
            "Switch the emitter's sim target to GPU. Note: GPU sim does not "
            "support direct mesh collision or audio triggers — verify modules "
            "before swapping."
        ),
    )


# ── LV003 ─────────────────────────────────────────────────────────────────────


def check_lv003(asset: dict, engine: str = "unreal") -> Finding | None:
    """LV003: Particle system without bounds culling (always-evaluating)."""
    if asset.get("asset_type") not in ("NiagaraSystem", "ParticleSystem"):
        return None
    bounds_mode: str = asset.get("bounds_mode", "Fixed")  # "Fixed" | "Dynamic" | "None"
    if bounds_mode != "None":
        return None

    return Finding(
        asset_path=asset["asset_path"],
        rule_id="LV003",
        category="VFX",
        severity="warning",
        message=(
            "Particle system has no fixed/dynamic bounds. "
            "The engine cannot frustum-cull it and evaluates every frame "
            "even when off-screen."
        ),
        current={"bounds_mode": "None"},
        recommended={"bounds_mode": "Fixed or Dynamic"},
        estimated_saving=Saving(vram_mb=0.0, shader_instructions=0),
        auto_fixable=True,
        guidance=None,
    )
