# core/modules/predictive/tests/test_orchestrator.py
#
# One-shot analysis end-to-end (M1 scope): synthetic project in, honest
# report out.

from predictive.predictive_orchestrator import analyze_oneshot
from predictive.schema import AnalyzeRequest

# A small synthetic UE5 project: one clean texture, one oversized texture
# (fires LT003 with a recovery), one mesh.
_SYNTHETIC_ASSETS = [
    {
        "asset_path": "/Game/T_Clean",
        "asset_type": "Texture2D",
        "usage": "BaseColor",
        "width": 2048,
        "height": 2048,
        "compression": "BC7",
        "mips_enabled": True,
        "streaming": True,
        "lod_group": "World",
    },
    {
        "asset_path": "/Game/T_Oversized",
        "asset_type": "Texture2D",
        "usage": "BaseColor",
        "width": 4096,
        "height": 4096,
        "compression": "BC7",
        "mips_enabled": True,
        "streaming": True,
        "lod_group": "World",
    },
    {
        "asset_path": "/Game/SM_Rock",
        "asset_type": "StaticMesh",
        "vertex_count": 250_000,
        "triangle_count": 500_000,
        "lod_count": 1,
    },
]


def _request(**kw) -> AnalyzeRequest:
    base = dict(
        engine="UE5",
        project_name="Synthetic",
        platform_profile="desktop_60",
        assets=list(_SYNTHETIC_ASSETS),
    )
    base.update(kw)
    return AnalyzeRequest(**base)


class TestReportShape:
    def test_report_identity_fields(self):
        report = analyze_oneshot(_request())
        assert report.schema_version == "1.0"
        assert report.report_id.startswith("pr-")
        assert report.generated_at  # ISO stamp
        assert report.calibration_version == "uncalibrated-dev"
        assert "reference hardware" in report.disclaimer
        assert report.platform_profile["profile"] == "desktop_60"

    def test_vram_total_is_exact_sum(self):
        report = analyze_oneshot(_request())
        # 5.33 (2k BC7) + 21.33 (4k BC7) + 7.63 (250k verts) = 34.29
        assert abs(report.memory.vram.predicted.expected - 34.29) < 0.05
        assert report.memory.vram.predicted.confidence == "high"
        assert report.memory.vram.budget_mb == 8192

    def test_build_band_present(self):
        report = analyze_oneshot(_request())
        assert report.build.size_mb is not None
        assert report.build.size_mb.confidence == "medium"

    def test_scores_scored_axes_only(self):
        report = analyze_oneshot(_request())
        # Tiny project on a desktop budget: memory risk low, build healthy.
        assert report.scores.memory_risk.value < 20
        assert report.scores.build_health.value > 80
        assert report.scores.overall_project_health > 80
        # CPU/GPU axes unshipped in M1 — must read as absent, not "risk 0
        # with drivers".
        assert report.scores.cpu_risk.drivers == []
        assert report.scores.gpu_risk.drivers == []

    def test_top_issues_ranked_and_capped(self):
        report = analyze_oneshot(_request())
        assert report.top_issues, "oversized texture must produce an item"
        ranks = [i.rank for i in report.top_issues]
        assert ranks == sorted(ranks) and ranks[0] == 1
        assert report.top_issues[0].rule_id == "LT003"

    def test_stats_are_transparent_about_coverage(self):
        report = analyze_oneshot(
            _request(code_issues=[{"rule_id": "CP006"}])
        )
        assert report.stats.assets_analyzed == 3
        assert report.stats.scenes_analyzed == 0
        # M1 doesn't cost code yet — the issue is COUNTED as uncosted, never
        # silently dropped.
        assert report.stats.code_issues_uncosted == 1
        assert report.stats.code_issues_costed == 0

    def test_memory_risk_reacts_to_platform(self):
        desktop = analyze_oneshot(_request())
        mobile = analyze_oneshot(_request(platform_profile="mobile_30"))
        assert (
            mobile.scores.memory_risk.value
            >= desktop.scores.memory_risk.value
        )
        assert mobile.platform_profile["profile"] == "mobile_30"

    def test_cost_items_equal_superset_of_top_issues(self):
        report = analyze_oneshot(_request())
        top_ids = {i.item_id for i in report.top_issues}
        all_ids = {i.item_id for i in report.cost_items}
        assert top_ids <= all_ids
