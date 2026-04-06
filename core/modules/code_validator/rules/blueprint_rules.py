# core/modules/code_validator/rules/blueprint_rules.py
#
# Deterministic Blueprint rules for Unreal Engine 5.
#
# Rules receive the blueprint dict exported by the UE5
# plugin via UBlueprint / UEdGraph / UK2Node.
#
# Expected input structure (per file in the plugin JSON):
# {
#   "name": "BP_PlayerCharacter",
#   "path": "/Game/Blueprints/Characters/BP_PlayerCharacter",
#   "type": "blueprint",
#   "graphs": [
#     {
#       "name": "EventGraph",
#       "type": "event_graph",
#       "nodes_count": 87,
#       "nodes": [
#         { "type": "CastTo", "target": "BP_Enemy", "count": 4 }
#       ]
#     }
#   ],
#   "variables": [
#     { "name": "Health", "type": "Float", "used": true }
#   ],
#   "functions": [
#     { "name": "HandleInventory", "complexity": 22 }
#   ],
#   "stats": {
#     "total_nodes": 234,
#     "cast_nodes": 12,
#     "tick_enabled": true,
#     "disconnected_nodes": 4
#   }
# }
#
# Each issue contains:
#   asset_path  — path to the Blueprint asset
#   graph       — graph name where the issue was found
#   severity    — error | warning | info
#   rule_id     — unique rule identifier
#   category    — Performance | Best Practices
#                 | Maintainability | Security
#   message     — human-readable description
#
# ── Rule index ────────────────────────────────────────
#
# BEST PRACTICES (BPB)
#   BPB001 — Blueprint missing BP_ prefix
#   BPB002 — REMOVED: test folder rule not valid across
#            studios (each studio has its own folder
#            structure). Scheduled for Phase 2 with
#            configurable paths via shinttools.config.json
#
# PERFORMANCE (BPP)
#   BPP001 — Tick enabled in Blueprint
#   BPP002 — Excessive Cast To nodes per graph
#
# MAINTAINABILITY (BPM)
#   BPM001 — Unused variables
#   BPM002 — Disconnected nodes
#   BPM003 — Blueprint too large (total nodes)
#   BPM004 — High complexity function
#   BPM005 — Graph too large (nodes per graph)
#
# SECURITY (BPS) — pending, no rules yet
# ──────────────────────────────────────────────────────

from typing import Dict, List

# Type alias for issue dictionary
Issue = Dict[str, object]

# ── THRESHOLDS ────────────────────────────────────────
# Revisit with Raul before Sprint 5 freeze

# Maximum Cast To nodes allowed per graph
_MAX_CAST_NODES_PER_GRAPH = 10

# Maximum total nodes allowed in a Blueprint
_MAX_TOTAL_NODES = 200

# Maximum nodes allowed in a single graph
_MAX_NODES_PER_GRAPH = 100

# Maximum cyclomatic complexity allowed per function
_MAX_FUNCTION_COMPLEXITY = 10


# ── BEST PRACTICES (BPB) ──────────────────────────────


# BPB001: Blueprint missing BP_ prefix
def detect_missing_bp_prefix(
    blueprint: dict,
) -> List[Issue]:
    """
    Checks that Blueprint assets use the BP_ prefix.
    Required by UE5 convention for identification in the
    Content Browser and distinction from C++ classes.
    """
    issues = []
    bp_path = blueprint.get("path", "")
    bp_name = blueprint.get("name", "")

    if not bp_name.startswith("BP_"):
        issues.append(
            {
                "asset_path": bp_path,
                "graph": "N/A",
                "severity": "warning",
                "rule_id": "BPB001",
                "category": "Best Practices",
                "message": (
                    f"Blueprint '{bp_name}' does not use BP_ "
                    "prefix — rename to BP_<AssetName> to follow"
                    " UE5 naming conventions."
                ),
            }
        )
    return issues


# ── PERFORMANCE (BPP) ─────────────────────────────────


# BPP001: Tick enabled in Blueprint
def detect_tick_enabled(
    blueprint: dict,
) -> List[Issue]:
    """
    Detects Blueprints with Tick enabled in Class Defaults.
    Tick runs every frame — disable it if the Blueprint
    does not need per-frame updates. Use timers or events
    instead whenever possible.
    """
    issues = []
    bp_path = blueprint.get("path", "")
    tick_enabled = blueprint.get("stats", {}).get("tick_enabled", False)

    if tick_enabled:
        issues.append(
            {
                "asset_path": bp_path,
                "graph": "Class Defaults",
                "severity": "warning",
                "rule_id": "BPP001",
                "category": "Performance",
                "message": (
                    "Tick is enabled in this Blueprint — "
                    "disable it in Class Defaults if per-frame "
                    "updates are not needed. Use timers or "
                    "events instead."
                ),
            }
        )
    return issues


# BPP002: Excessive Cast To nodes per graph
def detect_excessive_casts(
    blueprint: dict,
) -> List[Issue]:
    """
    Detects graphs with excessive Cast To nodes.
    Each Cast To creates a hard reference that increases
    memory usage and load times. Prefer interfaces or
    event dispatchers for loose coupling.
    Analyses each graph individually using the nodes[]
    array exported by the plugin.
    """
    issues = []
    bp_path = blueprint.get("path", "")
    graphs = blueprint.get("graphs", [])

    for graph in graphs:
        graph_name = graph.get("name", "Unknown")
        cast_count = sum(
            node.get("count", 0)
            for node in graph.get("nodes", [])
            if node.get("type") == "CastTo"
        )

        if cast_count > _MAX_CAST_NODES_PER_GRAPH:
            issues.append(
                {
                    "asset_path": bp_path,
                    "graph": graph_name,
                    "severity": "warning",
                    "rule_id": "BPP002",
                    "category": "Performance",
                    "message": (
                        f"Graph '{graph_name}' has {cast_count}"
                        " Cast To nodes "
                        f"(max: {_MAX_CAST_NODES_PER_GRAPH}) — "
                        "use interfaces or event dispatchers to "
                        "reduce hard references."
                    ),
                }
            )
    return issues


# ── MAINTAINABILITY (BPM) ─────────────────────────────


# BPM001: Unused variables
def detect_unused_variables(
    blueprint: dict,
) -> List[Issue]:
    """
    Detects declared Blueprint variables that are never
    referenced in any graph. Unused variables clutter the
    editor, confuse developers and waste runtime memory.
    Remove or deprecate them.
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
                    "graph": "Variables",
                    "severity": "warning",
                    "rule_id": "BPM001",
                    "category": "Maintainability",
                    "message": (
                        f"Variable '{var_name}' is declared but "
                        "never used — remove it or mark it as "
                        "deprecated."
                    ),
                }
            )
    return issues


# BPM002: Disconnected nodes in Blueprint
def detect_disconnected_nodes(
    blueprint: dict,
) -> List[Issue]:
    """
    Detects disconnected (orphan) nodes in Blueprint graphs.
    These nodes are never executed, clutter the graph and
    can hide unfinished logic. Delete or connect them.
    Uses stats.disconnected_nodes from the plugin export.
    """
    issues = []
    bp_path = blueprint.get("path", "")
    disconnected_count = blueprint.get("stats", {}).get("disconnected_nodes", 0)

    if disconnected_count > 0:
        issues.append(
            {
                "asset_path": bp_path,
                "graph": "EventGraph",
                "severity": "warning",
                "rule_id": "BPM002",
                "category": "Maintainability",
                "message": (
                    f"Blueprint has {disconnected_count} "
                    "disconnected node(s) — delete them or "
                    "connect them to the execution flow."
                ),
            }
        )
    return issues


# BPM003: Blueprint too large (total nodes)
def detect_large_blueprint(
    blueprint: dict,
) -> List[Issue]:
    """
    Detects Blueprints exceeding the maximum total node
    count across all graphs. Large Blueprints are hard to
    read, navigate and maintain. Split logic into smaller
    Blueprints or move it to C++.
    """
    issues = []
    bp_path = blueprint.get("path", "")
    total_nodes = blueprint.get("stats", {}).get("total_nodes", 0)

    if total_nodes > _MAX_TOTAL_NODES:
        issues.append(
            {
                "asset_path": bp_path,
                "graph": "All Graphs",
                "severity": "warning",
                "rule_id": "BPM003",
                "category": "Maintainability",
                "message": (
                    f"Blueprint has {total_nodes} total nodes "
                    f"(max: {_MAX_TOTAL_NODES}) — split into "
                    "smaller Blueprints or move logic to C++."
                ),
            }
        )
    return issues


# BPM004: High complexity function
def detect_high_complexity_function(
    blueprint: dict,
) -> List[Issue]:
    """
    Detects Blueprint functions exceeding the cyclomatic
    complexity threshold. Too many decision paths make
    functions hard to read and test. Split into smaller
    focused functions.
    Uses functions[].complexity from the plugin export.
    """
    issues = []
    bp_path = blueprint.get("path", "")
    functions = blueprint.get("functions", [])

    for bp_function in functions:
        func_name = bp_function.get("name", "unknown")
        complexity = bp_function.get("complexity", 0)

        if complexity > _MAX_FUNCTION_COMPLEXITY:
            issues.append(
                {
                    "asset_path": bp_path,
                    "graph": func_name,
                    "severity": "warning",
                    "rule_id": "BPM004",
                    "category": "Maintainability",
                    "message": (
                        f"Function '{func_name}' has complexity "
                        f"{complexity} "
                        f"(max: {_MAX_FUNCTION_COMPLEXITY}) — "
                        "split into smaller focused functions."
                    ),
                }
            )
    return issues


# BPM005: Graph too large (nodes per graph)
def detect_large_graph(
    blueprint: dict,
) -> List[Issue]:
    """
    Detects individual graphs exceeding the maximum node
    count. A single graph with too many nodes is harder
    to navigate than a Blueprint with many small graphs.
    Analyses each graph individually using nodes_count
    from the plugin export.
    """
    issues = []
    bp_path = blueprint.get("path", "")
    graphs = blueprint.get("graphs", [])

    for graph in graphs:
        graph_name = graph.get("name", "Unknown")
        nodes_count = graph.get("nodes_count", 0)

        if nodes_count > _MAX_NODES_PER_GRAPH:
            issues.append(
                {
                    "asset_path": bp_path,
                    "graph": graph_name,
                    "severity": "warning",
                    "rule_id": "BPM005",
                    "category": "Maintainability",
                    "message": (
                        f"Graph '{graph_name}' has {nodes_count}"
                        f" nodes (max: {_MAX_NODES_PER_GRAPH})"
                        " — split logic into smaller functions "
                        "or separate graphs."
                    ),
                }
            )
    return issues


# ── RUNNER ────────────────────────────────────────────


def run_all_blueprint_rules(
    blueprint: dict,
) -> List[Issue]:
    """
    Runs all deterministic Blueprint rules against a single
    blueprint dict and returns a merged list of issues.

    Best Practices (BPB): BPB001
    Performance (BPP):    BPP001, BPP002
    Maintainability (BPM): BPM001-BPM005
    Security (BPS):       pending — no rules yet
    """
    issues: List[Issue] = []

    # Best Practices
    issues += detect_missing_bp_prefix(blueprint)

    # Performance
    issues += detect_tick_enabled(blueprint)
    issues += detect_excessive_casts(blueprint)

    # Maintainability
    issues += detect_unused_variables(blueprint)
    issues += detect_disconnected_nodes(blueprint)
    issues += detect_large_blueprint(blueprint)
    issues += detect_high_complexity_function(blueprint)
    issues += detect_large_graph(blueprint)

    return issues


def run_all_blueprint_rules_from_export(
    plugin_export: dict,
) -> List[Issue]:
    """
    Entry point for the full plugin JSON export.
    Iterates over all files in the export and runs
    all Blueprint rules on each one.

    Expected input: the full JSON sent by the UE5 plugin
    with a 'files' array containing blueprint dicts.
    """
    issues: List[Issue] = []

    for blueprint in plugin_export.get("files", []):
        if blueprint.get("type") == "blueprint":
            issues += run_all_blueprint_rules(blueprint)

    return issues
