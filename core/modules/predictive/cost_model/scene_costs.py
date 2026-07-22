# core/modules/predictive/cost_model/scene_costs.py
#
# Scene composition pricing (Layer 2) — loader + per-unit band helpers over
# config/scene_costs.yaml. Layer 2 emits BOTH dimensions: CPU (tick/Update
# dispatch, skeletal meshes, CPU particles) and GPU (dynamic shadowed
# lights — the dominant term — and GPU particles).

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from predictive.cost_model.prediction import Prediction

_CONFIG_PATH = Path(__file__).parent / "config" / "scene_costs.yaml"


@lru_cache(maxsize=1)
def load_scene_costs() -> dict[str, Any]:
    with _CONFIG_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _band(spec: dict[str, float], count: float, unit: str,
          confidence: str, basis: str) -> Prediction:
    """Scale one per-unit band by *count*.

    Multiply BEFORE constructing the Prediction: per-unit costs are
    sub-centisecond (0.001 ms/tick) and the constructor rounds to 2
    decimals — building first would truncate them to zero.
    """
    return Prediction.banded(
        spec["expected"] * count,
        spec["min"] * count,
        spec["max"] * count,
        unit,
        confidence,
        basis,
    )


def cpu_cost(name: str, count: float, basis: str) -> Prediction | None:
    """Per-unit CPU band × count, or None for a zero count."""
    if count <= 0:
        return None
    table = load_scene_costs()
    section = table.get("cpu") or {}
    spec = section.get(name)
    if not spec:
        return None
    return _band(spec, count, "ms_frame", section.get("confidence", "low"), basis)


def light_cost(light: dict[str, Any]) -> Prediction | None:
    """GPU band for one light, or None when it's static/baked (free at
    runtime — its cost is lightmaps, billed by the LOD auditor, never here)."""
    table = load_scene_costs()
    gpu = table.get("gpu") or {}
    mobility = str(light.get("mobility", "Static"))
    if mobility not in set(table.get("dynamic_mobilities") or []):
        return None
    light_type = str(light.get("type", "Point"))
    key = "shadowed_light_ms" if light.get("casts_shadows") else "unshadowed_light_ms"
    per_type = gpu.get(key) or {}
    spec = per_type.get(light_type) or per_type.get("Point")
    if not spec:
        return None
    shadow_note = "shadowed" if light.get("casts_shadows") else "no shadows"
    return _band(
        spec, 1.0, "ms_frame", gpu.get("confidence", "low"),
        f"dynamic {light_type} light ({shadow_note})",
    )


def particle_cost(system: dict[str, Any]) -> tuple[str, Prediction] | None:
    """(dimension, band) for one particle system — CPU or GPU by sim target."""
    table = load_scene_costs()
    emitters = int(system.get("emitter_count", 0) or 0)
    instances = max(1, int(system.get("instance_count_in_scene", 1) or 1))
    if emitters <= 0:
        return None
    count = float(emitters * instances)
    target = str(system.get("sim_target", "CPU")).upper()
    if target == "GPU":
        gpu = table.get("gpu") or {}
        spec = gpu.get("gpu_particle_emitter_ms")
        if not spec:
            return None
        return "gpu_ms_frame", _band(
            spec, count, "ms_frame", gpu.get("confidence", "low"),
            f"{emitters} GPU emitters × {instances} instances",
        )
    cpu = table.get("cpu") or {}
    spec = cpu.get("cpu_particle_emitter_ms")
    if not spec:
        return None
    return "cpu_ms_frame", _band(
        spec, count, "ms_frame", cpu.get("confidence", "low"),
        f"{emitters} CPU emitters × {instances} instances",
    )


def complexity_score(scene: dict[str, Any], dynamic_shadowed_lights: int,
                     particle_systems: int) -> int:
    """0-100 weighted density measure for the per-scene summary card."""
    weights = load_scene_costs().get("complexity") or {}
    actors = int(scene.get("actor_count", 0) or 0)
    ticking = (
        int(scene.get("ticking_actors", 0) or 0)
        + int(scene.get("ticking_blueprints", 0) or 0)
    )
    updates = (
        int(scene.get("update_scripts", 0) or 0)
        + int(scene.get("fixed_update_scripts", 0) or 0)
    )
    score = (
        (actors / 1000.0) * weights.get("per_1k_actors", 0)
        + (ticking / 100.0) * weights.get("per_100_ticking", 0)
        + dynamic_shadowed_lights * weights.get("per_dynamic_shadowed_light", 0)
        + particle_systems * weights.get("per_particle_system", 0)
        + (updates / 100.0) * weights.get("per_100_update_scripts", 0)
    )
    return int(round(min(float(weights.get("max", 100)), score)))
