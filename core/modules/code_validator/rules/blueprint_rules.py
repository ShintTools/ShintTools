# core/modules/code_validator/rules/blueprint_rules.py
#
# Blueprint rules for Unreal Engine 5.
# Each rule receives an asset_path and returns a list of issues.
# Currently analyses asset path only (name + folder).
# Sprint 5: full Blueprint bytecode analysis via UHT reflection.

from pathlib import Path
from typing import Dict, List, Optional

# Type alias for issue dictionary
Issue = Dict[str, object]


# BLUEPRINT NAMING & STRUCTURE RULES (BP001-BP002)


# BP001: Blueprint missing BP_ prefix
def detect_missing_bp_prefix(asset_path: str) -> List[Issue]:
    """
    Checks that Blueprint assets use the BP_ prefix.
    Required by UE5 convention for identification in the
    Content Browser and distinction from C++ classes.
    """
    issues = []
    asset_name = Path(asset_path).stem

    if not asset_name.startswith("BP_"):
        issues.append(
            {
                "asset_path": asset_path,
                "severity": "warning",
                "rule_id": "BP001",
                "message": "Blueprint asset does not use BP_ prefix.",
                "line": 0,
            }
        )
    return issues


# BP002: Test Blueprint outside /Tests/ directory
def detect_test_bp_outside_tests(asset_path: str) -> List[Issue]:
    """
    Detects Blueprint assets with 'test' in their name
    outside a /Tests/ directory, where they should reside
    to be excluded from shipping builds.
    """
    issues = []
    path_lower = asset_path.lower()

    if "test" in path_lower and "/tests/" not in path_lower:
        issues.append(
            {
                "asset_path": asset_path,
                "severity": "warning",
                "rule_id": "BP002",
                "message": "Test Blueprint outside a /Tests/ directory.",
                "line": 0,
            }
        )
    return issues


# BP003: Tick enabled in Blueprint
def detect_tick_enabled(blueprint: dict) -> List[Issue]:
    """
    Detects Blueprints with Tick enabled.
    Tick runs every frame — disable it in the Class Defaults
    if the Blueprint does not need per-frame updates.
    """
    # Umbral: cualquier Blueprint con Tick activo se reporta.
    # Revisar con Raul si hay casos donde sea aceptable.
    issues = []
    bp_path = blueprint.get("path", "")
    tick_enabled = blueprint.get("stats", {}).get("tick_enabled", False)

    if tick_enabled:
        issues.append(
            {
                "asset_path": bp_path,
                "severity": "warning",
                "rule_id": "BP003",
                "message": (
                    "Tick is enabled in this Blueprint — disable it in "
                    "Class Defaults if per-frame updates are not needed."
                ),
                "line": 0,
            }
        )
    return issues


# BP004: Excessive Cast To nodes
# Umbral ajustable — revisar con Raul si 10 es correcto
_BP_MAX_CAST_NODES = 10


def detect_excessive_casts(blueprint: dict) -> List[Issue]:
    """
    Detects Blueprints with excessive Cast To nodes,
    which create hard references that increase memory and
    load times. Prefer interfaces or event dispatchers.
    """
    issues = []
    bp_path = blueprint.get("path", "")
    cast_count = blueprint.get("stats", {}).get("cast_nodes", 0)

    if cast_count > _BP_MAX_CAST_NODES:
        issues.append(
            {
                "asset_path": bp_path,
                "severity": "warning",
                "rule_id": "BP004",
                "message": (
                    f"Blueprint has {cast_count} Cast To nodes "
                    f"(max recommended: {_BP_MAX_CAST_NODES}) — "
                    "use interfaces or event dispatchers instead."
                ),
                "line": 0,
            }
        )
    return issues


# BP005: Unused variables
def detect_unused_variables(blueprint: dict) -> List[Issue]:
    """
    Detects declared Blueprint variables that are never used.
    Unused variables clutter the editor, confuse developers
    and waste runtime memory. Remove or deprecate them.
    """
    issues = []
    bp_path = blueprint.get("path", "")
    variables = blueprint.get("variables", [])

    for variable in variables:
        var_name = variable.get("name", "unknown")
        var_used = variable.get("used", True)

        if not var_used:
            issues.append(
                {
                    "asset_path": bp_path,
                    "severity": "warning",
                    "rule_id": "BP005",
                    "message": (
                        f"Variable '{var_name}' is declared but never used — "
                        "remove it or mark it as deprecated."
                    ),
                    "line": 0,
                }
            )
    return issues


# BP006: Disconnected nodes in Blueprint
def detect_disconnected_nodes(blueprint: dict) -> List[Issue]:
    """
    Detects disconnected (orphan) nodes in Blueprints.
    Never executed, they clutter the graph and can hide
    unfinished logic. Delete or connect them.
    """
    issues = []
    bp_path = blueprint.get("path", "")
    disconnected_count = blueprint.get("stats", {}).get("disconnected_nodes", 0)

    if disconnected_count > 0:
        issues.append(
            {
                "asset_path": bp_path,
                "severity": "warning",
                "rule_id": "BP006",
                "message": (
                    f"Blueprint has {disconnected_count} disconnected node(s) — "
                    "delete them or connect them to the execution flow."
                ),
                "line": 0,
            }
        )
    return issues


# BP007: Blueprint too large
# Umbral ajustable — revisar con Raul si 200 nodos es correcto
_BP_MAX_TOTAL_NODES = 200


def detect_large_blueprint(blueprint: dict) -> List[Issue]:
    """
    Detects Blueprints exceeding the maximum node count.
    Large Blueprints are hard to read and maintain; split
    logic into smaller Blueprints or move it to C++.
    """
    issues = []
    bp_path = blueprint.get("path", "")
    total_nodes = blueprint.get("stats", {}).get("total_nodes", 0)

    if total_nodes > _BP_MAX_TOTAL_NODES:
        issues.append(
            {
                "asset_path": bp_path,
                "severity": "warning",
                "rule_id": "BP007",
                "message": (
                    f"Blueprint has {total_nodes} nodes "
                    f"(max recommended: {_BP_MAX_TOTAL_NODES}) — "
                    "split into smaller Blueprints or move logic to C++."
                ),
                "line": 0,
            }
        )
    return issues


# BP008: High complexity function in Blueprint
# Umbral ajustable — revisar con Raul si 10 es correcto
_BP_MAX_FUNCTION_COMPLEXITY = 10


def detect_high_complexity_function(blueprint: dict) -> List[Issue]:
    """
    Detects Blueprint functions exceeding the cyclomatic
    complexity threshold. Too many decision paths make
    functions hard to test; split into smaller ones.
    """
    issues = []
    bp_path = blueprint.get("path", "")
    functions = blueprint.get("functions", [])

    for bp_function in functions:
        func_name = bp_function.get("name", "unknown")
        complexity = bp_function.get("complexity", 0)

        if complexity > _BP_MAX_FUNCTION_COMPLEXITY:
            issues.append(
                {
                    "asset_path": bp_path,
                    "severity": "warning",
                    "rule_id": "BP008",
                    "message": (
                        f"Function '{func_name}' has complexity {complexity} "
                        f"(max recommended: {_BP_MAX_FUNCTION_COMPLEXITY}) — "
                        "split into smaller focused functions."
                    ),
                    "line": 0,
                }
            )
    return issues


# RUNNER — executes ALL Blueprint rules


def run_all_blueprint_rules(
    asset_path: str, blueprint: Optional[dict] = None
) -> List[Issue]:
    """
    Runs all deterministic Blueprint rules and returns a merged list of issues.

    Path-only rules (2): BP001, BP002
    Blueprint JSON rules (6): BP003-BP008
    """
    issues: List[Issue] = []

    # BP001-BP002 — solo necesitan el asset_path
    issues += detect_missing_bp_prefix(asset_path)
    issues += detect_test_bp_outside_tests(asset_path)

    # BP003-BP008 — necesitan el JSON completo del Blueprint
    if blueprint:
        issues += detect_tick_enabled(blueprint)
        issues += detect_excessive_casts(blueprint)
        issues += detect_unused_variables(blueprint)
        issues += detect_disconnected_nodes(blueprint)
        issues += detect_large_blueprint(blueprint)
        issues += detect_high_complexity_function(blueprint)

    return issues
