# core/modules/predictive/tests/test_layer4_scores.py

from predictive.cost_model.platform_profiles import load_platform_profile
from predictive.cost_model.prediction import Prediction
from predictive.layers.layer4_scores import (
    compute_build_health,
    compute_memory_risk,
    compute_overall,
    utilisation_risk,
)
from predictive.schema import CostItem, RiskScore, Scores


def _mb(value: float) -> Prediction:
    return Prediction.exact(value, "mb", "test")


class TestUtilisationCurve:
    def test_piecewise_anchors(self):
        assert utilisation_risk(0.0) == 0
        assert utilisation_risk(0.60) == 20
        assert utilisation_risk(0.85) == 50
        assert utilisation_risk(1.00) == 80
        assert utilisation_risk(1.10) == 100  # +200/unit over budget

    def test_monotonic(self):
        samples = [utilisation_risk(u / 100) for u in range(0, 160, 5)]
        assert samples == sorted(samples)

    def test_strict_budget_steepens_overrun(self):
        # VR: the same 5% overrun scores worse than on a lax profile.
        assert utilisation_risk(1.05, strict=True) == 100
        assert utilisation_risk(1.05, strict=False) == 90

    def test_capped_at_100(self):
        assert utilisation_risk(5.0) == 100


class TestMemoryRisk:
    def test_comfortable_project_is_low_risk(self):
        profile = load_platform_profile("desktop_60")  # 8192 MB VRAM
        score = compute_memory_risk(_mb(2000), profile, [])
        assert score.value < 20

    def test_over_budget_is_high_risk(self):
        profile = load_platform_profile("desktop_60")
        score = compute_memory_risk(_mb(9000), profile, [])
        assert score.value >= 80

    def test_same_payload_riskier_on_mobile(self):
        desktop = load_platform_profile("desktop_60")
        mobile = load_platform_profile("mobile_30")  # 2048 MB VRAM
        payload = _mb(1800)
        assert (
            compute_memory_risk(payload, mobile, []).value
            > compute_memory_risk(payload, desktop, []).value
        )

    def test_unified_memory_uses_joint_pool(self):
        deck = load_platform_profile("steamdeck_60")
        # 8192 VRAM alone would read 9000 as over budget; the joint pool
        # (8192+12288)·⅔ ≈ 13653 keeps it under.
        score = compute_memory_risk(_mb(9000), deck, [])
        assert score.value < 80

    def test_drivers_are_top_vram_items(self):
        profile = load_platform_profile("desktop_60")
        items = [
            CostItem(item_id=f"ci-{i:04d}", layer=1,
                     impact={"vram_mb": _mb(float(i))})
            for i in range(1, 9)
        ]
        score = compute_memory_risk(_mb(4000), profile, items)
        assert len(score.drivers) == 5
        assert score.drivers[0] == "ci-0008"  # biggest contributor first


class TestBuildHealth:
    def test_small_build_is_healthy(self):
        profile = load_platform_profile("desktop_60")  # 50 GB advisory
        assert compute_build_health(_mb(10_000), profile, []).value > 80

    def test_bloated_build_is_unhealthy(self):
        profile = load_platform_profile("mobile_30")  # 4 GB advisory
        assert compute_build_health(_mb(6_000), profile, []).value <= 20


class TestOverall:
    def test_no_scored_axes_is_100(self):
        assert compute_overall(Scores()) == 100

    def test_one_blown_axis_sinks_overall(self):
        scores = Scores(
            memory_risk=RiskScore(value=90, drivers=["ci-0001"]),
            build_health=RiskScore(value=95, drivers=["ci-0002"]),
        )
        # Weighted max: overall must sit near the worst axis, not the mean.
        assert compute_overall(scores) < 35

    def test_unscored_axes_do_not_dilute(self):
        only_memory = Scores(memory_risk=RiskScore(value=80, drivers=["x"]))
        assert compute_overall(only_memory) <= 40
