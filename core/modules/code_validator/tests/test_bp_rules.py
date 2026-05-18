"""
Tests for all 17 Blueprint validation rules + fix instruction builders.

Fixtures:
  bp_all_bad.json  — triggers every rule
  bp_all_good.json — triggers no rule
"""

import json
from pathlib import Path

from unreal.blueprint.blueprint_orchestrator import run_all_blueprint_rules
from unreal.blueprint.blueprint_rules import (
    detect_abandoned_blueprint,
    detect_blueprint_no_functions,
    detect_disconnected_nodes,
    detect_excessive_casts,
    detect_function_no_tooltip,
    detect_generic_variable_name,
    detect_heavy_event_tick,
    detect_high_complexity_function,
    detect_large_blueprint,
    detect_large_graph,
    detect_missing_begin_play_super,
    detect_missing_bp_prefix,
    detect_missing_end_play_super,
    detect_no_functions_large_graph,
    detect_tick_enabled,
    detect_unused_variables,
    detect_variable_no_category,
)
from unreal.parsers.fixers.fix_patterns import build_bp_fix_instruction

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(filename: str) -> dict:
    with open(FIXTURES_DIR / filename, "r") as f:
        return json.load(f)


# ── Helpers ──────────────────────────────────────────


def _bad() -> dict:
    return load_fixture("bp_all_bad.json")


def _good() -> dict:
    return load_fixture("bp_all_good.json")


# ── BPB001: Missing BP_ prefix ──────────────────────


class TestBPB001:

    def test_detects_missing_prefix(self):
        issues = detect_missing_bp_prefix(_bad())
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "BPB001"
        assert issues[0]["is_auto_fixable"] is True

    def test_no_false_positive(self):
        issues = detect_missing_bp_prefix(_good())
        assert len(issues) == 0

    def test_fix_instruction(self):
        issues = detect_missing_bp_prefix(_bad())
        fix = build_bp_fix_instruction(issues[0])
        assert fix["action"] == "rename_asset"
        assert fix["old_name"] == "MyActor"
        assert fix["value"] == "BP_MyActor"
        assert fix["needs_input"] is False


# ── BPB002: No functions + large graph ───────────────


class TestBPB002:

    def test_detects_no_functions_large_graph(self):
        bp = _bad()
        bp["functions"] = []
        issues = detect_no_functions_large_graph(bp)
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "BPB002"

    def test_no_false_positive_with_functions(self):
        issues = detect_no_functions_large_graph(_bad())
        assert len(issues) == 0

    def test_no_false_positive_small_blueprint(self):
        issues = detect_no_functions_large_graph(_good())
        assert len(issues) == 0


# ── BPB003: Generic variable name ────────────────────


class TestBPB003:

    def test_detects_generic_names(self):
        issues = detect_generic_variable_name(_bad())
        names = [i["message"] for i in issues]
        assert len(issues) >= 2
        assert all(i["rule_id"] == "BPB003" for i in issues)
        assert any("NewVar" in m for m in names)
        assert any("Temp" in m for m in names)

    def test_no_false_positive(self):
        issues = detect_generic_variable_name(_good())
        assert len(issues) == 0

    def test_fix_instruction_needs_input(self):
        issues = detect_generic_variable_name(_bad())
        fix = build_bp_fix_instruction(issues[0])
        assert fix["action"] == "rename_variable"
        assert fix["needs_input"] is True
        assert fix["value"] == ""


# ── BPB004: Missing BeginPlay Super ──────────────────


class TestBPB004:

    def test_detects_missing_super(self):
        issues = detect_missing_begin_play_super(_bad())
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "BPB004"
        assert issues[0]["severity"] == "error"

    def test_no_false_positive(self):
        issues = detect_missing_begin_play_super(_good())
        assert len(issues) == 0


# ── BPB005: Missing EndPlay Super ────────────────────


class TestBPB005:

    def test_detects_missing_super(self):
        issues = detect_missing_end_play_super(_bad())
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "BPB005"
        assert issues[0]["severity"] == "error"

    def test_no_false_positive(self):
        issues = detect_missing_end_play_super(_good())
        assert len(issues) == 0


# ── BPB006: Public function without tooltip ──────────


class TestBPB006:

    def test_detects_no_tooltip(self):
        issues = detect_function_no_tooltip(_bad())
        assert len(issues) >= 1
        assert any(i["rule_id"] == "BPB006" for i in issues)

    def test_no_false_positive(self):
        issues = detect_function_no_tooltip(_good())
        assert len(issues) == 0


# ── BPB007: Public variable without category ─────────


class TestBPB007:

    def test_detects_no_category(self):
        issues = detect_variable_no_category(_bad())
        assert len(issues) >= 1
        assert all(i["rule_id"] == "BPB007" for i in issues)

    def test_no_false_positive(self):
        issues = detect_variable_no_category(_good())
        assert len(issues) == 0

    def test_fix_instruction_needs_input(self):
        issues = detect_variable_no_category(_bad())
        fix = build_bp_fix_instruction(issues[0])
        assert fix["action"] == "set_variable_category"
        assert fix["needs_input"] is True


# ── BPP001: Tick enabled ─────────────────────────────


class TestBPP001:

    def test_detects_tick_enabled(self):
        issues = detect_tick_enabled(_bad())
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "BPP001"
        assert issues[0]["is_auto_fixable"] is True

    def test_no_false_positive(self):
        issues = detect_tick_enabled(_good())
        assert len(issues) == 0

    def test_fix_instruction(self):
        issues = detect_tick_enabled(_bad())
        fix = build_bp_fix_instruction(issues[0])
        assert fix["action"] == "set_property"
        assert fix["property"] == "bCanEverTick"
        assert fix["value"] is False
        assert fix["needs_input"] is False


# ── BPP002: Excessive casts ──────────────────────────


class TestBPP002:

    def test_detects_excessive_casts(self):
        issues = detect_excessive_casts(_bad())
        assert len(issues) >= 1
        assert issues[0]["rule_id"] == "BPP002"

    def test_no_false_positive(self):
        issues = detect_excessive_casts(_good())
        assert len(issues) == 0


# ── BPP003: Heavy EventTick ──────────────────────────


class TestBPP003:

    def test_detects_heavy_tick(self):
        issues = detect_heavy_event_tick(_bad())
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "BPP003"

    def test_no_false_positive(self):
        issues = detect_heavy_event_tick(_good())
        assert len(issues) == 0


# ── BPM001: Unused variables ─────────────────────────


class TestBPM001:

    def test_detects_unused(self):
        issues = detect_unused_variables(_bad())
        assert len(issues) >= 1
        assert all(i["rule_id"] == "BPM001" for i in issues)

    def test_no_false_positive(self):
        issues = detect_unused_variables(_good())
        assert len(issues) == 0

    def test_fix_instruction(self):
        issues = detect_unused_variables(_bad())
        fix = build_bp_fix_instruction(issues[0])
        assert fix["action"] == "remove_variable"
        assert fix["needs_input"] is False
        assert "variable" in fix


# ── BPM002: Disconnected nodes ───────────────────────


class TestBPM002:

    def test_detects_disconnected(self):
        issues = detect_disconnected_nodes(_bad())
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "BPM002"

    def test_no_false_positive(self):
        issues = detect_disconnected_nodes(_good())
        assert len(issues) == 0

    def test_fix_instruction(self):
        issues = detect_disconnected_nodes(_bad())
        fix = build_bp_fix_instruction(issues[0])
        assert fix["action"] == "delete_disconnected_nodes"
        assert fix["needs_input"] is False


# ── BPM003: Blueprint too large ──────────────────────


class TestBPM003:

    def test_detects_large(self):
        issues = detect_large_blueprint(_bad())
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "BPM003"

    def test_no_false_positive(self):
        issues = detect_large_blueprint(_good())
        assert len(issues) == 0


# ── BPM004: High complexity function ─────────────────


class TestBPM004:

    def test_detects_high_complexity(self):
        issues = detect_high_complexity_function(_bad())
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "BPM004"

    def test_no_false_positive(self):
        issues = detect_high_complexity_function(_good())
        assert len(issues) == 0


# ── BPM005: Large graph ──────────────────────────────


class TestBPM005:

    def test_detects_large_graph(self):
        issues = detect_large_graph(_bad())
        assert len(issues) >= 1
        assert issues[0]["rule_id"] == "BPM005"

    def test_no_false_positive(self):
        issues = detect_large_graph(_good())
        assert len(issues) == 0


# ── BPM006: No functions defined ─────────────────────


class TestBPM006:

    def test_detects_no_functions(self):
        bp = _bad()
        bp["functions"] = []
        issues = detect_blueprint_no_functions(bp)
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "BPM006"

    def test_no_false_positive_with_functions(self):
        issues = detect_blueprint_no_functions(_bad())
        assert len(issues) == 0


# ── BPM007: Abandoned blueprint ──────────────────────


class TestBPM007:

    def test_detects_abandoned(self):
        bp = {
            "name": "BP_Abandoned",
            "path": "Content/Blueprints/BP_Abandoned.uasset",
            "type": "blueprint",
            "graphs": [],
            "variables": [
                {"name": f"Var{i}", "used": False, "is_public": False} for i in range(5)
            ],
            "functions": [],
            "stats": {"total_nodes": 2, "disconnected_nodes": 0},
        }
        issues = detect_abandoned_blueprint(bp)
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "BPM007"

    def test_no_false_positive(self):
        issues = detect_abandoned_blueprint(_good())
        assert len(issues) == 0


# ── Runner: all rules at once ────────────────────────


class TestRunAllBlueprintRules:

    def test_bad_fixture_triggers_multiple(self):
        issues = run_all_blueprint_rules(_bad())
        rule_ids = {i["rule_id"] for i in issues}
        # bad fixture must trigger at least these
        assert "BPB001" in rule_ids
        assert "BPP001" in rule_ids
        assert "BPM001" in rule_ids
        assert "BPM002" in rule_ids
        assert "BPB004" in rule_ids
        assert "BPB005" in rule_ids

    def test_good_fixture_triggers_none(self):
        issues = run_all_blueprint_rules(_good())
        assert len(issues) == 0

    def test_every_issue_has_required_fields(self):
        issues = run_all_blueprint_rules(_bad())
        required = {
            "asset_path",
            "graph",
            "severity",
            "rule_id",
            "category",
            "message",
        }
        for issue in issues:
            missing = required - set(issue.keys())
            assert not missing, f"Issue {issue.get('rule_id')} missing: {missing}"


# ── Fix instruction builder edge cases ───────────────


class TestFixInstructionBuilder:

    def test_unknown_rule_returns_empty(self):
        fix = build_bp_fix_instruction({"rule_id": "FAKE001"})
        assert fix == {}

    def test_non_auto_fixable_returns_empty(self):
        fix = build_bp_fix_instruction({"rule_id": "BPB002"})
        assert fix == {}

    def test_all_auto_fixable_produce_action(self):
        issues = run_all_blueprint_rules(_bad())
        auto_rules = {"BPB001", "BPP001", "BPM001", "BPM002"}
        for issue in issues:
            if issue.get("rule_id") in auto_rules:
                fix = build_bp_fix_instruction(issue)
                assert "action" in fix, f"{issue['rule_id']} missing action"
                assert fix.get("needs_input") is False
