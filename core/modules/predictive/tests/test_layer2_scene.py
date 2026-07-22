# core/modules/predictive/tests/test_layer2_scene.py
#
# Layer 2 emits BOTH dimensions: CPU (tick/Update dispatch) and GPU
# (dynamic shadowed lights — the dominant term — plus GPU particles).

from predictive.layers.layer2_scene import analyze_scenes


def _scene(**kw):
    base = {"scene_name": "L_Main", "actor_count": 4000}
    base.update(kw)
    return base


def _light(type="Point", mobility="Movable", shadows=True):
    return {"type": type, "mobility": mobility, "casts_shadows": shadows}


class TestCpuDispatch:
    def test_ticking_actors_priced(self):
        r = analyze_scenes([_scene(ticking_actors=1000)])
        assert abs(r.cpu_total.expected - 1.0) < 0.01  # 1000 × 0.001
        assert r.gpu_total.expected == 0.0

    def test_blueprint_tick_is_10x_native(self):
        native = analyze_scenes([_scene(ticking_actors=100)])
        bp = analyze_scenes([_scene(ticking_blueprints=100)])
        assert abs(bp.cpu_total.expected / native.cpu_total.expected - 10) < 0.1

    def test_unity_update_scripts_priced(self):
        r = analyze_scenes(
            [_scene(update_scripts=300, fixed_update_scripts=100)]
        )
        # 300×0.002 + 100×0.002 = 0.8
        assert abs(r.cpu_total.expected - 0.8) < 0.01

    def test_empty_scene_costs_nothing(self):
        r = analyze_scenes([_scene()])
        assert r.cpu_total.expected == 0.0
        assert r.gpu_total.expected == 0.0
        assert r.scenes_analyzed == 1


class TestGpuLights:
    def test_shadowed_dynamic_point_light_priced_on_gpu(self):
        r = analyze_scenes([_scene(lights=[_light()])])
        assert abs(r.gpu_total.expected - 0.6) < 0.01
        assert r.cpu_total.expected == 0.0  # lights are GPU, never CPU

    def test_static_light_is_free_at_runtime(self):
        r = analyze_scenes(
            [_scene(lights=[_light(mobility="Static")])]
        )
        assert r.gpu_total.expected == 0.0

    def test_shadowless_light_is_an_order_cheaper(self):
        shadowed = analyze_scenes([_scene(lights=[_light(shadows=True)])])
        bare = analyze_scenes([_scene(lights=[_light(shadows=False)])])
        assert shadowed.gpu_total.expected > bare.gpu_total.expected * 5

    def test_unity_realtime_mobility_counts_as_dynamic(self):
        r = analyze_scenes(
            [_scene(lights=[_light(mobility="Realtime")])]
        )
        assert r.gpu_total.expected > 0

    def test_shadowed_light_becomes_actionable_item(self):
        r = analyze_scenes([_scene(lights=[_light()])])
        assert len(r.items) == 1
        item = r.items[0]
        assert item.layer == 2
        assert "gpu_ms_frame" in item.impact
        assert item.remediation is not None
        assert item.remediation.recovery["gpu_ms_frame"].expected > 0


class TestParticles:
    def test_gpu_sim_lands_on_gpu(self):
        r = analyze_scenes(
            [_scene(particle_systems=[
                {"path": "NS_Fire", "sim_target": "GPU", "emitter_count": 4,
                 "instance_count_in_scene": 3},
            ])]
        )
        # 4 emitters × 3 instances × 0.1
        assert abs(r.gpu_total.expected - 1.2) < 0.01
        assert r.cpu_total.expected == 0.0

    def test_cpu_sim_lands_on_cpu(self):
        r = analyze_scenes(
            [_scene(particle_systems=[
                {"path": "PS_Smoke", "sim_target": "CPU", "emitter_count": 2},
            ])]
        )
        assert r.cpu_total.expected > 0
        assert r.gpu_total.expected == 0.0


class TestHeavyBlueprints:
    def test_many_instances_become_an_item(self):
        r = analyze_scenes(
            [_scene(heavy_blueprints=[
                {"path": "BP_Enemy", "tick_enabled": True,
                 "node_count": 400, "instances": 60},
            ])]
        )
        bp_items = [i for i in r.items if i.rule_id == "SCENE_BP_TICK"]
        assert len(bp_items) == 1
        assert bp_items[0].impact["cpu_ms_frame"].expected >= 0.1

    def test_tick_disabled_bp_is_skipped(self):
        r = analyze_scenes(
            [_scene(heavy_blueprints=[
                {"path": "BP_Prop", "tick_enabled": False, "instances": 500},
            ])]
        )
        assert r.items == []


class TestSummaries:
    def test_summary_carries_both_dimensions(self):
        r = analyze_scenes(
            [_scene(ticking_actors=500, lights=[_light()])]
        )
        s = r.summaries[0]
        assert s.scene_name == "L_Main"
        assert s.runtime_cost["cpu_ms_frame"].expected > 0
        assert s.runtime_cost["gpu_ms_frame"].expected > 0

    def test_complexity_score_grows_with_density(self):
        light_scene = analyze_scenes([_scene(actor_count=500)])
        dense = analyze_scenes(
            [_scene(actor_count=20000, ticking_actors=2000,
                    lights=[_light()] * 8)]
        )
        assert (
            dense.summaries[0].complexity_score
            > light_scene.summaries[0].complexity_score
        )
        assert dense.summaries[0].complexity_score <= 100

    def test_max_actor_count_reported_for_layer3_scaling(self):
        r = analyze_scenes([_scene(actor_count=4000),
                            _scene(scene_name="L_2", actor_count=9000)])
        assert r.max_actor_count == 9000
