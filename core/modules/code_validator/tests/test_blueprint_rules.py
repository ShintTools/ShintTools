import json
from pathlib import Path

from code_validator.rules.cpp.ue5_cpp_rules import (
    detect_find_object_in_tick,
    detect_get_component_in_tick,
    detect_infinite_loop,
    detect_runtime_load,
)

# Path to fixtures folder
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(filename: str) -> dict:
    """Loads a JSON fixture file and returns its content."""
    with open(FIXTURES_DIR / filename, "r") as f:
        return json.load(f)


# RULE 1: FindObjectOfType in Tick
class TestFindObjectInTick:

    def test_detects_find_object_in_tick(self):
        """Should detect FindObjectOfType inside Tick."""
        fixture = load_fixture("cpp_find_object_bad.json")
        issues = detect_find_object_in_tick(fixture["content"], fixture["file_path"])
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "find_object_in_tick"
        assert issues[0]["severity"] == "error"

    def test_no_false_positive_find_object(self):
        """Should not flag FindObjectOfType inside BeginPlay."""
        fixture = load_fixture("cpp_find_object_good.json")
        issues = detect_find_object_in_tick(fixture["content"], fixture["file_path"])
        assert len(issues) == 0


# RULE 2: GetComponent in Tick
class TestGetComponentInTick:

    def test_detects_get_component_in_tick(self):
        """Should detect GetComponent inside Tick."""
        fixture = load_fixture("cpp_get_component_bad.json")
        issues = detect_get_component_in_tick(fixture["content"], fixture["file_path"])
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "get_component_in_tick"
        assert issues[0]["severity"] == "error"

    def test_no_false_positive_get_component(self):
        """Should not flag GetComponent inside BeginPlay."""
        fixture = load_fixture("cpp_get_component_good.json")
        issues = detect_get_component_in_tick(fixture["content"], fixture["file_path"])
        assert len(issues) == 0


# RULE 3: Infinite loop without exit
class TestInfiniteLoop:

    def test_detects_infinite_loop_no_exit(self):
        """Should detect while(true) without break/return."""
        fixture = load_fixture("cpp_infinite_loop_bad.json")
        issues = detect_infinite_loop(fixture["content"], fixture["file_path"])
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "infinite_loop_no_exit"
        assert issues[0]["severity"] == "error"

    def test_no_false_positive_infinite_loop(self):
        """Should not flag while(true) that has a break."""
        fixture = load_fixture("cpp_infinite_loop_good.json")
        issues = detect_infinite_loop(fixture["content"], fixture["file_path"])
        assert len(issues) == 0


# RULE 4: Runtime asset load
class TestRuntimeLoad:

    def test_detects_runtime_load_in_tick(self):
        """Should detect StaticLoadObject outside BeginPlay."""
        fixture = load_fixture("cpp_runtime_load_bad.json")
        issues = detect_runtime_load(fixture["content"], fixture["file_path"])
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "runtime_asset_load"
        assert issues[0]["severity"] == "warning"

    def test_no_false_positive_runtime_load(self):
        """Should not flag StaticLoadObject inside BeginPlay."""
        fixture = load_fixture("cpp_runtime_load_good.json")
        issues = detect_runtime_load(fixture["content"], fixture["file_path"])
        assert len(issues) == 0
