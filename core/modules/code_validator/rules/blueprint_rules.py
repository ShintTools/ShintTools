# core/modules/code_validator/rules/blueprint_rules.py
#
# Deterministic Blueprint rules for Unreal Engine 5.
# Input: blueprint dict exported by the UE5 plugin.
# Input fields: name, path, type, graphs[], variables[],
#               functions[], stats{}
# Issue fields: asset_path, graph, severity, rule_id,
#               category, message
#
# Rule index:
#   Best Practices (BPB): BPB001-BPB003
#   Performance (BPP):    BPP001-BPP003
#   Maintainability (BPM): BPM001-BPM007
#   Security (BPS):       pending

# ──────────────────────────────────────────────────────
import re
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


# BPB002: Blueprint without functions — all logic in EventGraph
def detect_no_functions_large_graph(
    blueprint: dict,
) -> List[Issue]:
    """BPB002: flag Blueprints with many nodes but no functions defined.
    All logic in EventGraph makes the Blueprint hard to maintain.
    Split logic into named functions for readability.
    """
    issues: List[Issue] = []
    bp_path = blueprint.get("path", "")
    bp_name = blueprint.get("name", "")
    functions = blueprint.get("functions", [])
    total_nodes = blueprint.get("stats", {}).get("total_nodes", 0)

    # Configurable: flag when Blueprint has many nodes but no functions.
    # 50 nodes without any function is a clear maintainability issue.
    _MIN_NODES_FOR_FUNCTION_REQUIRED: int = 50

    if not functions and total_nodes >= _MIN_NODES_FOR_FUNCTION_REQUIRED:
        issues.append(
            {
                "asset_path": bp_path,
                "graph": "EventGraph",
                "severity": "warning",
                "rule_id": "BPB002",
                "category": "Best Practices",
                "message": (
                    f"'{bp_name}' has {total_nodes} nodes but no "
                    "functions defined — split logic into named "
                    "functions for readability and reuse."
                ),
            }
        )
    return issues


# BPB003: Variable with generic or placeholder name
def detect_generic_variable_name(
    blueprint: dict,
) -> List[Issue]:
    """BPB003: flag Blueprint variables with generic placeholder names.
    Names like NewVar, Temp, Var_1 give no context about their purpose.
    Use descriptive names that reflect the variable's role.
    """
    issues: List[Issue] = []
    bp_path = blueprint.get("path", "")
    variables = blueprint.get("variables", [])

    # Generic variable name patterns — case-insensitive check
    _GENERIC_VAR_WORDS: frozenset = frozenset(
        [
            "newvar",
            "new_var",
            "tempvar",
            "temp_var",
            "temp",
            "tmp",
            "test",
            "var",
            "variable",
            "unnamed",
            "untitled",
            "placeholder",
            "dummy",
            "default",
            "value",
            "data",
            "item",
            "object",
        ]
    )

    # Regex: matches names like Var_1, Var1, Variable2
    generic_indexed_pattern = re.compile(
        r"^(?:var|variable|temp|new)[_]?\d*$",
        re.IGNORECASE,
    )

    for variable in variables:
        var_name = variable.get("name", "")
        if not var_name:
            continue

        is_generic = (
            var_name.lower() in _GENERIC_VAR_WORDS
            or generic_indexed_pattern.match(var_name)
        )
        if not is_generic:
            continue

        issues.append(
            {
                "asset_path": bp_path,
                "graph": "Variables",
                "severity": "warning",
                "rule_id": "BPB003",
                "category": "Best Practices",
                "message": (
                    f"Variable '{var_name}' has a generic name — "
                    "use a descriptive name that reflects its "
                    "purpose (e.g. 'PlayerHealth', 'MoveSpeed')."
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


# BPP003: EventTick graph with too many nodes
def detect_heavy_event_tick(
    blueprint: dict,
) -> List[Issue]:
    """BPP003: flag Blueprints with too many nodes in their EventTick graph.
    Heavy Tick logic runs every frame — move infrequent logic to timers.
    """
    issues: List[Issue] = []
    bp_path = blueprint.get("path", "")
    graphs = blueprint.get("graphs", [])

    # Configurable: maximum nodes allowed in the EventTick graph.
    # More than 20 nodes in Tick is a strong signal of overuse.
    _MAX_TICK_NODES: int = 20

    for graph in graphs:
        graph_name = graph.get("name", "")
        nodes_count = graph.get("nodes_count", 0)

        if graph_name.lower() not in ("eventtick", "tick"):
            continue

        if nodes_count > _MAX_TICK_NODES:
            issues.append(
                {
                    "asset_path": bp_path,
                    "graph": graph_name,
                    "severity": "warning",
                    "rule_id": "BPP003",
                    "category": "Performance",
                    "message": (
                        f"EventTick graph has {nodes_count} nodes "
                        f"(max: {_MAX_TICK_NODES}) — move "
                        "infrequent logic to timers or events."
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


# BPM006: Blueprint with no functions defined
def detect_blueprint_no_functions(
    blueprint: dict,
) -> List[Issue]:
    """BPM006: flag Blueprints with zero functions defined.
    Any Blueprint beyond a trivial size should organise logic
    into named functions for readability and reusability.
    """
    issues: List[Issue] = []
    bp_path = blueprint.get("path", "")
    bp_name = blueprint.get("name", "")
    functions = blueprint.get("functions", [])
    total_nodes = blueprint.get("stats", {}).get("total_nodes", 0)

    # Only flag if the Blueprint has a meaningful number of nodes.
    # Small Blueprints with no functions are acceptable.
    _MIN_NODES_TO_REQUIRE_FUNCTIONS: int = 30

    if not functions and total_nodes >= _MIN_NODES_TO_REQUIRE_FUNCTIONS:
        issues.append(
            {
                "asset_path": bp_path,
                "graph": "All Graphs",
                "severity": "warning",
                "rule_id": "BPM006",
                "category": "Maintainability",
                "message": (
                    f"'{bp_name}' has {total_nodes} nodes but "
                    "no functions — organise logic into named "
                    "functions for maintainability."
                ),
            }
        )
    return issues


# BPM007: Blueprint with more variables than nodes — likely abandoned
def detect_abandoned_blueprint(
    blueprint: dict,
) -> List[Issue]:
    """BPM007: flag Blueprints with more variables than nodes.
    This usually indicates an incomplete or abandoned Blueprint
    where variables were declared but logic was never implemented.
    Review and either complete or delete the Blueprint.
    """
    issues: List[Issue] = []
    bp_path = blueprint.get("path", "")
    bp_name = blueprint.get("name", "")
    variables = blueprint.get("variables", [])
    total_nodes = blueprint.get("stats", {}).get("total_nodes", 0)

    variable_count = len(variables)

    # Only flag if the Blueprint has at least some variables
    # and significantly more variables than nodes.
    if variable_count < 3:
        return issues

    if variable_count > total_nodes:
        issues.append(
            {
                "asset_path": bp_path,
                "graph": "All Graphs",
                "severity": "warning",
                "rule_id": "BPM007",
                "category": "Maintainability",
                "message": (
                    f"'{bp_name}' has {variable_count} variables "
                    f"but only {total_nodes} nodes — may be "
                    "incomplete or abandoned. Review and complete "
                    "or delete this Blueprint."
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
    issues += detect_no_functions_large_graph(blueprint)
    issues += detect_generic_variable_name(blueprint)

    # Performance
    issues += detect_tick_enabled(blueprint)
    issues += detect_excessive_casts(blueprint)
    issues += detect_heavy_event_tick(blueprint)

    # Maintainability
    issues += detect_unused_variables(blueprint)
    issues += detect_disconnected_nodes(blueprint)
    issues += detect_large_blueprint(blueprint)
    issues += detect_high_complexity_function(blueprint)
    issues += detect_large_graph(blueprint)
    issues += detect_blueprint_no_functions(blueprint)
    issues += detect_abandoned_blueprint(blueprint)

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
