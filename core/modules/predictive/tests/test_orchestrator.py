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
        # Stamped from rule_costs.yaml since M2.
        assert "uncalibrated" in report.calibration_version
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
        # One costed rule (CP006) + one with no cost entry (CM001): the
        # split is visible, nothing is silently dropped.
        report = analyze_oneshot(
            _request(code_issues=[{"rule_id": "CP006"}, {"rule_id": "CM001"}])
        )
        assert report.stats.assets_analyzed == 3
        assert report.stats.scenes_analyzed == 0
        assert report.stats.code_issues_costed == 1
        assert report.stats.code_issues_uncosted == 1

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


class TestCodeLayer:
    """M2: code_issues flow through Layer 3 into the report."""

    _CODE_ISSUES = [
        {
            "rule_id": "CP006",
            "rule_name": "GetAllActorsOfClass in Tick",
            "file": "Source/Game/Enemy.cpp",
            "line": 42,
            "occurrence_context": {"in_tick": True},
        },
        {
            "rule_id": "CSP001",
            "rule_name": "LINQ operator in Update",
            "file": "Assets/Scripts/Spawner.cs",
            "line": 17,
        },
        {"rule_id": "CM001", "rule_name": "Method too long"},  # uncosted
    ]

    def test_spec_example_end_to_end(self):
        report = analyze_oneshot(_request(code_issues=list(self._CODE_ISSUES)))
        cp006 = next(
            i for i in report.cost_items if i.rule_id == "CP006"
        )
        cpu = cp006.impact["cpu_ms_frame"]
        # "Tick → GetAllActorsOfClass: +0.05–1.2 ms, est. +0.35 ms"
        assert cpu.to_display() == "+0.05–1.2 ms, est. +0.35 ms"
        assert cp006.remediation is not None
        assert cp006.remediation.recovery["cpu_ms_frame"].expected > 0

    def test_cpu_risk_scored_with_drivers(self):
        report = analyze_oneshot(_request(code_issues=list(self._CODE_ISSUES)))
        assert report.scores.cpu_risk.drivers  # costed items drive the score
        assert report.frame_budget.cpu.predicted is not None
        assert report.frame_budget.cpu.budget_ms == 10.0

    def test_costed_uncosted_split(self):
        report = analyze_oneshot(_request(code_issues=list(self._CODE_ISSUES)))
        assert report.stats.code_issues_costed == 2
        assert report.stats.code_issues_uncosted == 1

    def test_gc_pressure_surfaces_for_unity_patterns(self):
        report = analyze_oneshot(_request(code_issues=list(self._CODE_ISSUES)))
        assert report.memory.gc_pressure is not None
        assert report.memory.gc_pressure.unit == "mb_min"

    def test_scene_actor_count_scales_code_cost(self):
        issues = [dict(self._CODE_ISSUES[0])]
        small = analyze_oneshot(_request(code_issues=issues))
        big = analyze_oneshot(
            _request(
                code_issues=issues,
                scenes=[{"scene_name": "L_Main", "actor_count": 20000}],
            )
        )
        cpu_small = next(
            i for i in small.cost_items if i.rule_id == "CP006"
        ).impact["cpu_ms_frame"]
        cpu_big = next(
            i for i in big.cost_items if i.rule_id == "CP006"
        ).impact["cpu_ms_frame"]
        assert cpu_big.expected > cpu_small.expected

    def test_no_code_issues_leaves_cpu_axis_unscored(self):
        report = analyze_oneshot(_request())
        assert report.scores.cpu_risk.value == 0
        assert report.scores.cpu_risk.drivers == []
        assert report.frame_budget.cpu.predicted is None

    def test_calibration_version_comes_from_the_table(self):
        report = analyze_oneshot(_request())
        assert report.calibration_version == "2026.07-uncalibrated-r1"


class TestClientReportedRegressions:
    """Six defects reported from the live Unity client (2026-07-29).

    All were Core-side: the report is the shared contract, so a display
    problem in one engine's client is a Core problem for both.
    """

    _CS_FILE = {
        "path": "Assets/Scripts/Enemy.cs",
        "content": (
            "using System.Linq;\n"
            "using UnityEngine;\n"
            "public class Enemy : MonoBehaviour {\n"
            "  void Update() {\n"
            "    var all = GameObject.FindObjectsOfType<Enemy>()"
            ".Where(e => e != null).ToList();\n"
            "  }\n"
            "}"
        ),
    }

    def _unity_request(self, **kw) -> AnalyzeRequest:
        base = dict(
            engine="Unity",
            project_name="UnityClient",
            platform_profile="mobile_30",
            assets=[
                {"asset_path": "Assets/T_Rock.png", "asset_type": "Texture",
                 "width": 4096, "height": 4096, "format": "RGBA32",
                 "mip_count": 1},
            ],
        )
        base.update(kw)
        return AnalyzeRequest(**base)

    def test_frame_line_is_the_bottleneck_not_the_sum(self):
        """CPU and GPU are pipelined — frame = max(cpu, gpu), never cpu+gpu."""
        report = analyze_oneshot(
            self._unity_request(
                scenes=[{
                    "scene_name": "Arena",
                    "update_scripts": 400,
                    "lights": [{"type": "Point", "mobility": "Movable",
                                "casts_shadows": True, "radius": 1500}],
                }],
                code_files=[self._CS_FILE],
            )
        )
        frame = report.frame_budget.frame
        cpu = report.frame_budget.cpu.predicted.expected
        gpu = report.frame_budget.gpu.predicted.expected
        assert frame.predicted_ms == round(max(cpu, gpu), 3)
        assert frame.predicted_ms < cpu + gpu  # the reported mismatch
        assert frame.bottleneck in ("cpu", "gpu")
        assert frame.budget_ms > 0

    def test_breakdown_reconciles_with_its_total(self):
        report = analyze_oneshot(
            self._unity_request(
                scenes=[{"scene_name": "Arena", "update_scripts": 400}],
                code_files=[self._CS_FILE],
            )
        )
        line = report.frame_budget.cpu
        assert abs(
            sum(b["expected_ms"] for b in line.breakdown)
            - line.predicted.expected
        ) < 0.02
        # The table shows less than the total (aggregate dispatch isn't
        # itemized) — stated explicitly rather than looking like lost time.
        assert line.itemized_ms <= line.predicted.expected + 0.01

    def test_duplicate_assets_yield_one_row_and_are_not_double_counted(self):
        asset = {"asset_path": "Assets/T_Rock.png", "asset_type": "Texture",
                 "width": 4096, "height": 4096, "format": "RGBA32",
                 "mip_count": 1}
        once = analyze_oneshot(self._unity_request(assets=[asset]))
        twice = analyze_oneshot(self._unity_request(assets=[asset, dict(asset)]))
        assert len(twice.cost_items) == len(once.cost_items)
        assert twice.stats.assets_analyzed == once.stats.assets_analyzed
        # The duplicate must not inflate the project's VRAM either.
        assert twice.memory.vram.predicted.expected == \
            once.memory.vram.predicted.expected

    def test_two_rules_on_one_line_merge_into_one_row(self):
        report = analyze_oneshot(
            self._unity_request(code_files=[self._CS_FILE])
        )
        code_rows = [i for i in report.cost_items if i.layer == 3]
        titles = [i.title for i in code_rows]
        assert len(titles) == len(set(titles))  # no visually identical rows
        # The merged row still credits every contributing rule.
        merged = [i for i in code_rows if len(i.source.get("rule_ids", [])) > 1]
        assert merged, "expected LINQ + FindObjectsOfType to share a line"

    def test_no_zero_cost_rows_and_every_row_states_its_unit(self):
        report = analyze_oneshot(
            self._unity_request(code_files=[self._CS_FILE])
        )
        for item in report.cost_items:
            assert any(p.expected > 0 for p in item.impact.values())
            assert item.primary_cost is not None
            assert item.primary_cost.unit  # "MB" / "ms" — never a bare number
            assert item.primary_cost.value > 0
        # An asset is priced in MB, not ms: a fixed "ms" column showed 0.
        asset_row = next(i for i in report.cost_items if i.layer == 1)
        assert asset_row.primary_cost.unit == "MB"

    def test_scene_path_is_echoed_back_for_icon_resolution(self):
        report = analyze_oneshot(
            self._unity_request(
                scenes=[{"scene_name": "Arena",
                         "scene_path": "Assets/Scenes/Arena.unity",
                         "update_scripts": 10}],
            )
        )
        summary = report.scene_summaries[0]
        assert summary.scene_name == "Arena"
        assert summary.scene_path == "Assets/Scenes/Arena.unity"

    def test_code_files_removes_the_code_validator_pre_run(self):
        """The client sends raw source; the Core scans it itself."""
        report = analyze_oneshot(
            self._unity_request(code_files=[self._CS_FILE], code_issues=[])
        )
        assert report.stats.code_issues_costed > 0
        assert any(i.layer == 3 for i in report.cost_items)
