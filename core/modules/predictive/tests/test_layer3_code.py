# core/modules/predictive/tests/test_layer3_code.py
#
# Layer 3 quantifies validator issues via rule_costs.yaml. The spec's
# literal acceptance example: "Tick → GetAllActorsOfClass: impacto estimado
# +1.4 ms CPU/frame" — an issue in, a banded ms figure out.

from predictive.cost_model.rule_costs import apply_rule_cost, load_rule_costs
from predictive.layers.layer3_code import analyze_code


def _issue(rule_id="CP006", **kw):
    base = {
        "rule_id": rule_id,
        "rule_name": "GetAllActorsOfClass in Tick",
        "file": "Source/Game/Enemy.cpp",
        "line": 42,
        "severity": "warning",
    }
    base.update(kw)
    return base


class TestRuleCostTable:
    def test_table_loads_with_31_costed_rules(self):
        table = load_rule_costs()
        assert len(table.entries) >= 25
        assert table.calibration_version

    def test_every_entry_has_valid_bands_and_remediation(self):
        for rule_id, entry in load_rule_costs().entries.items():
            assert entry.dimensions, rule_id
            for dim, band in entry.dimensions.items():
                assert band["min"] <= band["expected"] <= band["max"], (
                    f"{rule_id}.{dim}"
                )
                assert band["min"] > 0, f"{rule_id}.{dim} zero-cost entry"
            assert entry.confidence in ("medium", "low"), rule_id
            assert entry.basis, rule_id
            assert entry.remediation_action, rule_id
            assert 0 < entry.recovery_pct <= 100, rule_id

    def test_costed_rules_exist_in_validator_catalog(self):
        # Anti-drift: a costed rule_id that the validator no longer ships is
        # a stale table entry — fail loudly.
        import sys
        from pathlib import Path

        shared = (
            Path(__file__).resolve().parents[2] / "code_validator"
        )
        sys.path.insert(0, str(shared.parent))
        from code_validator.shared._rule_metadata import RULE_NAMES

        missing = [
            rule_id
            for rule_id in load_rule_costs().entries
            if rule_id not in RULE_NAMES
        ]
        assert not missing, f"costed rules absent from the catalog: {missing}"


class TestApplyRuleCost:
    def test_spec_example_shape(self):
        priced = apply_rule_cost(_issue("CP006"))
        assert priced is not None
        impact, recovery, entry = priced
        cpu = impact["cpu_ms_frame"]
        assert cpu.min == 0.05 and cpu.expected == 0.35 and cpu.max == 1.2
        assert cpu.confidence == "medium"
        assert recovery["cpu_ms_frame"].expected < cpu.expected  # 95%

    def test_unknown_rule_returns_none(self):
        assert apply_rule_cost(_issue("ZZ999")) is None

    def test_scene_actor_scaling(self):
        small = apply_rule_cost(_issue("CP006"), scene_actor_count=1000)
        large = apply_rule_cost(_issue("CP006"), scene_actor_count=20000)
        assert small and large
        # 1000/5000=0.2 (clamp floor), 20000/5000=4.0 (clamp ceiling)
        assert small[0]["cpu_ms_frame"].expected == round(0.35 * 0.2, 2)
        assert large[0]["cpu_ms_frame"].expected == round(0.35 * 4.0, 2)
        # basis says why the number moved
        assert "actor scene" in large[0]["cpu_ms_frame"].basis

    def test_loop_depth_scaling(self):
        flat = apply_rule_cost(_issue("CSP010"))
        nested = apply_rule_cost(
            _issue("CSP010", occurrence_context={"loop_depth": 3})
        )
        assert nested[0]["cpu_ms_frame"].expected == round(
            flat[0]["cpu_ms_frame"].expected * 3, 2
        )

    def test_call_count_multiplies(self):
        once = apply_rule_cost(_issue("CSP001"))
        many = apply_rule_cost(
            _issue("CSP001", occurrence_context={"call_count_estimate": 4})
        )
        assert many[0]["gc_mb_min"].expected == round(
            once[0]["gc_mb_min"].expected * 4, 2
        )

    def test_multi_dimensional_rule(self):
        # LINQ in Update costs CPU *and* GC — both dimensions priced.
        impact, recovery, _ = apply_rule_cost(_issue("CSP001"))
        assert set(impact) == {"cpu_ms_frame", "gc_mb_min"}
        assert impact["gc_mb_min"].unit == "mb_min"


class TestAnalyzeCode:
    def test_empty_input(self):
        r = analyze_code([])
        assert r.cpu_total.expected == 0.0
        assert r.costed == 0 and r.uncosted == 0
        assert r.items == []

    def test_uncosted_issue_counted_never_priced(self):
        r = analyze_code([_issue("CM001")])  # maintainability — no cost entry
        assert r.costed == 0 and r.uncosted == 1
        assert r.cpu_total.expected == 0.0

    def test_cpu_total_sums_bands(self):
        r = analyze_code([_issue("CP006"), _issue("CP002")])
        assert r.costed == 2
        assert abs(r.cpu_total.expected - (0.35 + 0.05)) < 0.01
        assert r.cpu_total.min <= r.cpu_total.expected <= r.cpu_total.max

    def test_severity_from_expected_cpu(self):
        heavy = analyze_code([_issue("CP016")])  # 12 ms expected
        light = analyze_code([_issue("CSP006")])  # GC only, no CPU
        assert heavy.items[0].severity == "critical"
        assert light.items[0].severity == "info"

    def test_title_is_file_location(self):
        # Location, not a description — the "what" (rule_name) stays
        # queryable metadata, not the headline.
        r = analyze_code([_issue("CP013", rule_name="NewObject in loop")])
        assert r.items[0].title == "Source/Game/Enemy.cpp:42"

    def test_title_falls_back_to_file_without_line(self):
        r = analyze_code([_issue("CP006", line=None)])
        assert r.items[0].title == "Source/Game/Enemy.cpp"

    def test_gc_and_ram_aggregates(self):
        r = analyze_code([_issue("CSP001"), _issue("CP013")])
        assert r.gc_total is not None and r.gc_total.expected > 0
        assert r.ram_total is not None and r.ram_total.expected > 0

    def test_item_ids_continue_from_start_index(self):
        r = analyze_code([_issue("CP006")], start_index=7)
        assert r.items[0].item_id == "ci-0007"


def _cp006_source() -> str:
    """A Tick body with GetAllActorsOfClass nested 3 levels deep — Tree-sitter
    reaches it, the legacy 1-level regex would not."""
    return (
        "void AMyActor::Tick(float DeltaTime)\n"
        "{\n"
        "    Super::Tick(DeltaTime);\n"
        "    if (bShouldSearch)\n"
        "    {\n"
        "        for (int i = 0; i < 10; i++)\n"
        "        {\n"
        "            if (i > 0)\n"
        "            {\n"
        "                GetAllActorsOfClass<AActor>(this, Out);\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


class TestCodeFilesScan:
    """Predictive scans code itself instead of trusting a client that
    pre-ran the Code Validator — the operational coupling the redesign
    removes."""

    def test_code_files_are_scanned_in_process(self):
        r = analyze_code(
            [],
            code_files=[{"path": "Source/MyActor.cpp", "content": _cp006_source()}],
            engine="unreal",
        )
        assert r.costed >= 1
        rule_ids = {i.rule_id for i in r.items}
        assert "CP006" in rule_ids

    def test_code_files_yield_same_rule_as_legacy_code_issues(self):
        # Same underlying pattern, both paths — base cost bands must agree.
        # Not the same SCALED numbers: self-scanning populates
        # occurrence_context (in_tick/loop_depth) the legacy path never
        # sends, so this is an intentional behaviour delta, not a bug.
        via_files = analyze_code(
            [],
            code_files=[{"path": "Source/MyActor.cpp", "content": _cp006_source()}],
            engine="unreal",
        )
        via_issues = analyze_code([_issue("CP006")])
        assert via_files.items[0].rule_id == via_issues.items[0].rule_id == "CP006"

    def test_unknown_extension_yields_no_issues(self):
        r = analyze_code(
            [], code_files=[{"path": "notes.txt", "content": "hello"}], engine="unreal"
        )
        assert r.items == [] and r.costed == 0 and r.uncosted == 0

    def test_legacy_and_code_files_union(self):
        r = analyze_code(
            [_issue("CP002")],
            code_files=[{"path": "Source/MyActor.cpp", "content": _cp006_source()}],
            engine="unreal",
        )
        rule_ids = {i.rule_id for i in r.items}
        assert {"CP002", "CP006"} <= rule_ids
