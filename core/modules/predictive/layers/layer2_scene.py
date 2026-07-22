# core/modules/predictive/layers/layer2_scene.py
#
# Layer 2 — Scene Intelligence.
#
# Consumes the per-scene digests the client collects (SceneDigest in
# schema.py — UE5 fills actors/blueprints, Unity fills update_scripts;
# either engine leaves the other's fields at defaults and the pricing
# simply skips zero counts) and emits BOTH dimensions:
#
#   CPU — tick/Update dispatch, skeletal meshes, CPU particle emitters
#   GPU — dynamic shadowed lights (the dominant term) and GPU emitters
#
# Plus a 0-100 complexity score per scene and CostItems for the individually
# worth-fixing offenders (shadowed dynamic lights, heavy ticking BPs).

from __future__ import annotations

from typing import Any

from predictive.cost_model.prediction import Prediction, sum_predictions
from predictive.cost_model.scene_costs import (
    complexity_score,
    cpu_cost,
    light_cost,
    particle_cost,
)
from predictive.schema import CostItem, Remediation, SceneSummary

# A single scene item must move the needle to earn a row of its own.
_ITEM_MIN_EXPECTED_MS = 0.1


class Layer2Result:
    def __init__(
        self,
        cpu_total: Prediction,
        gpu_total: Prediction,
        items: list[CostItem],
        summaries: list[SceneSummary],
        scenes_analyzed: int,
        max_actor_count: int,
    ) -> None:
        self.cpu_total = cpu_total
        self.gpu_total = gpu_total
        self.items = items
        self.summaries = summaries
        self.scenes_analyzed = scenes_analyzed
        self.max_actor_count = max_actor_count


def _dispatch_costs(scene: dict[str, Any]) -> list[Prediction]:
    """Per-frame CPU dispatch bands for every counted unit in the digest."""
    parts: list[Prediction] = []
    mapping = [
        ("actor_tick_ms", scene.get("ticking_actors"), "native actor ticks"),
        ("blueprint_tick_ms", scene.get("ticking_blueprints"),
         "Blueprint ticks (~10x native VM overhead)"),
        ("update_script_ms", scene.get("update_scripts"),
         "MonoBehaviour Update() dispatch"),
        ("fixed_update_script_ms", scene.get("fixed_update_scripts"),
         "FixedUpdate dispatch at the 50 Hz default step"),
        ("skeletal_mesh_ms", scene.get("skeletal_meshes"),
         "skeletal pose evaluation"),
    ]
    for name, count, label in mapping:
        n = int(count or 0)
        pred = cpu_cost(name, n, f"{n} × {label}")
        if pred is not None:
            parts.append(pred)
    return parts


def analyze_scenes(
    scenes: list[dict[str, Any]],
    start_index: int = 0,
) -> Layer2Result:
    """Price the scene digests into CPU/GPU aggregates + items + summaries."""
    cpu_parts: list[Prediction] = []
    gpu_parts: list[Prediction] = []
    items: list[CostItem] = []
    summaries: list[SceneSummary] = []
    index = start_index
    max_actors = 0

    for scene in scenes:
        name = str(scene.get("scene_name", "") or "unnamed")
        max_actors = max(max_actors, int(scene.get("actor_count", 0) or 0))

        scene_cpu = _dispatch_costs(scene)

        # Lights — GPU. Each dynamic shadowed light is also an item: it's
        # individually actionable (bake it, drop the shadow, cull range).
        scene_gpu: list[Prediction] = []
        shadowed = 0
        for light in scene.get("lights") or []:
            pred = light_cost(light)
            if pred is None:
                continue
            scene_gpu.append(pred)
            if light.get("casts_shadows"):
                shadowed += 1
                if pred.expected >= _ITEM_MIN_EXPECTED_MS:
                    items.append(
                        CostItem(
                            item_id=f"ci-{index:04d}",
                            layer=2,
                            severity="warning",
                            title=(
                                f"Dynamic shadowed {light.get('type', 'Point')}"
                                f" light — {name}"
                            ),
                            rule_id="SCENE_LIGHT",
                            source={"kind": "scene", "path": name},
                            impact={"gpu_ms_frame": pred},
                            remediation=Remediation(
                                action=(
                                    "Bake the light if it never moves, or "
                                    "disable shadow casting / tighten the "
                                    "attenuation radius"
                                ),
                                recovery={
                                    "gpu_ms_frame": pred.scaled(
                                        0.9,
                                        basis="baking removes ~90% of the "
                                        "runtime cost",
                                    )
                                },
                                auto_fixable=False,
                            ),
                        )
                    )
                    index += 1

        # Particles — dimension depends on the sim target.
        particle_count = 0
        for system in scene.get("particle_systems") or []:
            priced = particle_cost(system)
            if priced is None:
                continue
            particle_count += 1
            dim, pred = priced
            (gpu_parts if dim == "gpu_ms_frame" else scene_cpu).append(pred)

        # Heavy ticking Blueprints — individually actionable CPU items.
        for bp in scene.get("heavy_blueprints") or []:
            if not bp.get("tick_enabled", True):
                continue
            instances = max(1, int(bp.get("instances", 1) or 1))
            pred = cpu_cost(
                "blueprint_tick_ms",
                instances,
                f"{instances} ticking instances of {bp.get('path', 'BP')}",
            )
            if pred is None or pred.expected < _ITEM_MIN_EXPECTED_MS:
                continue
            scene_cpu.append(pred)
            items.append(
                CostItem(
                    item_id=f"ci-{index:04d}",
                    layer=2,
                    severity="warning",
                    title=f"Ticking Blueprint {bp.get('path', '')} — {name}",
                    rule_id="SCENE_BP_TICK",
                    source={
                        "kind": "blueprint",
                        "path": str(bp.get("path", "")),
                        "instances_in_scene": instances,
                    },
                    impact={"cpu_ms_frame": pred},
                    remediation=Remediation(
                        action="Disable Tick or use timers/events instead",
                        recovery={
                            "cpu_ms_frame": pred.scaled(
                                0.95, basis="event-driven removes the "
                                "per-frame dispatch",
                            )
                        },
                        auto_fixable=False,
                    ),
                )
            )
            index += 1

        cpu_parts.extend(scene_cpu)
        gpu_parts.extend([p for p in scene_gpu])

        scene_cpu_total = sum_predictions(
            scene_cpu, "ms_frame", f"scene dispatch + particles ({name})"
        )
        scene_gpu_total = sum_predictions(
            scene_gpu, "ms_frame", f"dynamic lights ({name})"
        )
        summaries.append(
            SceneSummary(
                scene_name=name,
                complexity_score=complexity_score(
                    scene, shadowed, particle_count
                ),
                runtime_cost={
                    "cpu_ms_frame": scene_cpu_total,
                    "gpu_ms_frame": scene_gpu_total,
                },
            )
        )

    return Layer2Result(
        cpu_total=sum_predictions(
            cpu_parts, "ms_frame",
            f"Σ scene dispatch across {len(scenes)} scenes",
        ),
        gpu_total=sum_predictions(
            gpu_parts, "ms_frame",
            f"Σ dynamic lights + GPU particles across {len(scenes)} scenes",
        ),
        items=items,
        summaries=summaries,
        scenes_analyzed=len(scenes),
        max_actor_count=max_actors,
    )
