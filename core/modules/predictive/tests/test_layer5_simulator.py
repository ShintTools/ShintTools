# core/modules/predictive/tests/test_layer5_simulator.py
#
# The simulator replays selections against a report — pure arithmetic,
# no re-analysis. Fed with a real report from the orchestrator so the
# fixture can't drift from the production shape.

from predictive.layers.layer5_simulator import simulate
from predictive.predictive_orchestrator import analyze_oneshot
from predictive.schema import AnalyzeRequest


def _report() -> dict:
    """A real report: oversized texture (vram recovery), shadowed light
    (gpu recovery), CP006 (cpu recovery)."""
    request = AnalyzeRequest(
        engine="UE5",
        project_name="Sim",
        platform_profile="desktop_60",
        assets=[
            {
                "asset_path": "/Game/T_Big",
                "asset_type": "Texture2D",
                "usage": "BaseColor",
                "width": 4096,
                "height": 4096,
                "compression": "BC7",
                "mips_enabled": True,
                "streaming": True,
                "lod_group": "World",
            }
        ],
        scenes=[
            {
                "scene_name": "L_Main",
                "actor_count": 4000,
                "ticking_actors": 800,
                "lights": [
                    {"type": "Point", "mobility": "Movable",
                     "casts_shadows": True}
                ],
            }
        ],
        code_issues=[
            {
                "rule_id": "CP006",
                "rule_name": "GetAllActorsOfClass in Tick",
                "file": "Source/Game/Enemy.cpp",
                "line": 42,
            }
        ],
    )
    return analyze_oneshot(request).model_dump()


def _item_by_rule(report: dict, rule_id: str) -> dict:
    return next(i for i in report["cost_items"] if i["rule_id"] == rule_id)


class TestDeltas:
    def test_empty_selection_yields_no_deltas(self):
        report = _report()
        r = simulate(report, [], [], "")
        assert r.selected_count == 0
        assert r.deltas == {}
        assert r.scores_before.memory_risk.value == (
            report["scores"]["memory_risk"]["value"]
        )
        # Nothing selected — after == before.
        assert r.scores_after.overall_project_health == (
            r.scores_before.overall_project_health
        )

    def test_selected_recovery_becomes_negative_delta(self):
        report = _report()
        lt003 = _item_by_rule(report, "LT003")
        r = simulate(report, [lt003["item_id"]], [], "")
        assert r.selected_count == 1
        delta = r.deltas["vram_mb"]
        assert delta.expected < 0
        assert abs(delta.expected) == (
            lt003["remediation"]["recovery"]["vram_mb"]["expected"]
        )

    def test_multi_dimension_selection(self):
        report = _report()
        ids = [
            _item_by_rule(report, "LT003")["item_id"],
            _item_by_rule(report, "SCENE_LIGHT")["item_id"],
            _item_by_rule(report, "CP006")["item_id"],
        ]
        r = simulate(report, ids, [], "")
        assert set(r.deltas) >= {"vram_mb", "gpu_ms_frame", "cpu_ms_frame"}

    def test_unknown_ids_are_ignored(self):
        report = _report()
        r = simulate(report, ["ci-9999"], [], "")
        assert r.selected_count == 0


class TestScores:
    def test_fixing_improves_or_holds_every_axis(self):
        report = _report()
        all_ids = [i["item_id"] for i in report["cost_items"]]
        r = simulate(report, all_ids, [], "")
        assert r.scores_after.cpu_risk.value <= r.scores_before.cpu_risk.value
        assert r.scores_after.gpu_risk.value <= r.scores_before.gpu_risk.value
        assert (
            r.scores_after.memory_risk.value
            <= r.scores_before.memory_risk.value
        )
        assert (
            r.scores_after.overall_project_health
            >= r.scores_before.overall_project_health
        )

    def test_porting_scenario_uses_new_budgets_on_both_sides(self):
        report = _report()
        r = simulate(report, [], [], platform_profile="mobile_30")
        # Same project, tighter budgets: before-risk on mobile must be >=
        # the desktop before-risk stored in the report.
        assert (
            r.scores_before.memory_risk.value
            >= report["scores"]["memory_risk"]["value"]
        )


class TestStatelessFallback:
    def test_inline_items_give_deltas_without_scores(self):
        report = _report()
        lt003 = _item_by_rule(report, "LT003")
        r = simulate(None, [lt003["item_id"]], report["cost_items"], "")
        assert r.deltas["vram_mb"].expected < 0
        # No report → aggregate totals unknown → scores stay at defaults.
        assert r.scores_before.overall_project_health == 0


class TestRecommendations:
    def test_top_remaining_recovery_recommended(self):
        report = _report()
        r = simulate(report, [], [], "")
        assert r.recommendations
        assert r.recommendations[0]["reason"].startswith("Largest remaining")
        rec_ids = {rec["item_id"] for rec in r.recommendations}
        assert rec_ids <= {i["item_id"] for i in report["cost_items"]}

    def test_selected_items_never_recommended(self):
        report = _report()
        all_ids = [i["item_id"] for i in report["cost_items"]]
        r = simulate(report, all_ids, [], "")
        assert r.recommendations == []
