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
#   Best Practices (BPB): BPB001-BPB007
#   Performance (BPP):    BPP001-BPP005
#   Maintainability (BPM): BPM001-BPM007
#   Security (BPS):       BPS001, BPS003

# ──────────────────────────────────────────────────────
import re
from typing import Dict, List

try:
    from code_validator.unreal.parsers.fixers.fix_patterns import (
        build_bp_fix_instruction,
    )
except ModuleNotFoundError:
    build_bp_fix_instruction = None  # type: ignore[assignment]

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

    # The exporter sends every UBlueprint subclass through this rule —
    # widgets, anim BPs, interfaces, function/macro libraries — and each has
    # its OWN canonical prefix. Demanding literally "BP_" flagged every
    # correctly-named WBP_/ABP_ asset (and the auto-fix would have produced
    # "BP_WBP_..."). Accept the standard UE prefix family.
    _BP_PREFIX_FAMILY = (
        "BP_",    # actor/object blueprint
        "WBP_",   # widget blueprint
        "ABP_",   # animation blueprint
        "BPI_",   # blueprint interface
        "BPFL_",  # blueprint function library
        "BPML_",  # blueprint macro library
        "GA_",    # gameplay ability
        "GE_",    # gameplay effect
        "BTT_", "BTS_", "BTD_",  # behavior tree task/service/decorator
        "AN_", "ANS_",           # anim notify / notify state
        "EQS_",   # environment query
    )

    if not bp_name.startswith(_BP_PREFIX_FAMILY):
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
                "fix_suggestion": f"Rename '{bp_name}' to 'BP_{bp_name}'",
                "is_auto_fixable": True,
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
                "fix_suggestion": "",
                "is_auto_fixable": False,
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

    # Generic variable name patterns — case-insensitive check.
    # Deliberately restricted to true PLACEHOLDER names. "Value", "Data",
    # "Item", "Object" and "Default" were removed: they are idiomatic exact
    # names in real graphs (a slider's Value, a ForEach Item, a data-asset
    # ref) and produced steady false positives on well-kept projects.
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
                "fix_suggestion": (
                    f"Rename '{var_name}' to a descriptive name "
                    "reflecting its purpose (e.g. 'PlayerHealth', 'MoveSpeed')"
                ),
                "is_auto_fixable": True,
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
    issues: List[Issue] = []
    bp_path = blueprint.get("path", "")
    tick_enabled = blueprint.get("stats", {}).get("tick_enabled", False)

    if not tick_enabled:
        return issues

    # Characters, pawns and movement-driven actors legitimately tick —
    # warning on EVERY tick-enabled Blueprint was the single loudest false
    # positive. Only the unambiguous waste stays a warning: tick enabled
    # while the EventTick graph is absent or a bare stub (<= 1 node). A
    # tick that is actually USED becomes an informational advisory (the UI
    # excludes info from its error/warning counts).
    tick_nodes = 0
    for graph in blueprint.get("graphs", []):
        if graph.get("name", "").lower() in ("eventtick", "tick"):
            tick_nodes = max(tick_nodes, graph.get("nodes_count", 0))

    tick_unused = tick_nodes <= 1

    issues.append(
        {
            "asset_path": bp_path,
            "graph": "Class Defaults",
            "severity": "warning" if tick_unused else "info",
            "rule_id": "BPP001",
            "category": "Performance",
            "message": (
                (
                    "Tick is enabled but the EventTick graph is empty — "
                    "this pays the per-frame cost for nothing. Disable "
                    "'Start with Tick Enabled' in Class Defaults."
                )
                if tick_unused
                else (
                    "Tick is enabled in this Blueprint — fine if "
                    "per-frame updates are required; otherwise prefer "
                    "timers or events."
                )
            ),
            "fix_suggestion": (
                "Set 'Start with Tick Enabled' to false in Class Defaults"
                if tick_unused
                else ""
            ),
            "is_auto_fixable": tick_unused,
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
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
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
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
                }
            )
    return issues


# BPP004: Delay node inside EventTick graph
def detect_delay_in_tick(
    blueprint: dict,
) -> List[Issue]:
    """BPP004: flag Blueprints that use a Delay node inside EventTick.
    Delay does not pause Tick execution — it schedules a latent action
    while Tick continues firing every frame. This accumulates pending
    latent actions, leaks memory, and causes unpredictable behaviour.
    Use a Timer or boolean gate instead.
    """
    issues: List[Issue] = []
    bp_path = blueprint.get("path", "")
    graphs = blueprint.get("graphs", [])

    # Node types that represent a Delay in Blueprint exports
    _DELAY_TYPES: frozenset = frozenset({"Delay", "K2Node_Delay", "RetriggerableDelay"})

    for graph in graphs:
        graph_name = graph.get("name", "")

        if graph_name.lower() not in ("eventtick", "tick"):
            continue

        delay_count = sum(
            node.get("count", 0)
            for node in graph.get("nodes", [])
            if node.get("type") in _DELAY_TYPES
        )

        if delay_count > 0:
            issues.append(
                {
                    "asset_path": bp_path,
                    "graph": graph_name,
                    "severity": "error",
                    "rule_id": "BPP004",
                    "category": "Performance",
                    "message": (
                        f"Delay node found inside '{graph_name}' "
                        f"({delay_count} instance(s)) — Delay does "
                        "not pause Tick, it accumulates latent "
                        "actions every frame causing memory leaks. "
                        "Use a Timer or boolean gate instead."
                    ),
                    "fix_suggestion": (
                        "Replace Delay with Set Timer by Event or "
                        "a boolean gate that skips frames."
                    ),
                    "is_auto_fixable": False,
                }
            )
    return issues


# BPP005: GetAllActorsOfClass inside EventTick graph
def detect_get_all_actors_in_tick(
    blueprint: dict,
) -> List[Issue]:
    """BPP005: flag GetAllActorsOfClass called inside EventTick.
    This node iterates every actor in the world each frame,
    causing massive CPU overhead in scenes with many actors.
    Cache the result in BeginPlay or use a timer-based refresh.
    """
    issues: List[Issue] = []
    bp_path = blueprint.get("path", "")
    graphs = blueprint.get("graphs", [])

    _GET_ALL_TYPES: frozenset = frozenset(
        {
            "GetAllActorsOfClass",
            "K2Node_GetAllActorsOfClass",
            "GetAllActorsOfClassWithTag",
            "GetAllActorsWithInterface",
            "GetAllActorsWithTag",
        }
    )

    for graph in graphs:
        graph_name = graph.get("name", "")

        if graph_name.lower() not in ("eventtick", "tick"):
            continue

        get_all_count = sum(
            node.get("count", 0)
            for node in graph.get("nodes", [])
            if node.get("type") in _GET_ALL_TYPES
        )

        if get_all_count > 0:
            issues.append(
                {
                    "asset_path": bp_path,
                    "graph": graph_name,
                    "severity": "error",
                    "rule_id": "BPP005",
                    "category": "Performance",
                    "message": (
                        f"GetAllActorsOfClass found inside "
                        f"'{graph_name}' ({get_all_count} "
                        "instance(s)) — iterating all world "
                        "actors every frame is extremely "
                        "expensive. Cache the result in BeginPlay "
                        "or refresh on a timer."
                    ),
                    "fix_suggestion": (
                        "Move GetAllActorsOfClass to BeginPlay and "
                        "store the result in a variable. Refresh "
                        "only when needed (timer or event)."
                    ),
                    "is_auto_fixable": False,
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
                    "fix_suggestion": (
                        f"Remove unused variable '{var_name}' from the Blueprint"
                    ),
                    "is_auto_fixable": True,
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
        # One or two parked nodes are routine mid-iteration workflow, not a
        # defect — advisory only. Three or more is genuine graph clutter.
        issues.append(
            {
                "asset_path": bp_path,
                "graph": "EventGraph",
                "severity": "warning" if disconnected_count >= 3 else "info",
                "rule_id": "BPM002",
                "category": "Maintainability",
                "message": (
                    f"Blueprint has {disconnected_count} "
                    "disconnected node(s) — delete them or "
                    "connect them to the execution flow."
                ),
                "fix_suggestion": (
                    f"Delete {disconnected_count} disconnected node(s) "
                    "from the Blueprint graph"
                ),
                "is_auto_fixable": True,
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
                "fix_suggestion": "",
                "is_auto_fixable": False,
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
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
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
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
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

    # BPB002 already fires a warning for >= 50 nodes without functions —
    # this rule used to fire alongside it, double-reporting the exact same
    # condition on the same asset. BPM006 now covers only the 30-49 band,
    # as a soft advisory.
    if not functions and (
        _MIN_NODES_TO_REQUIRE_FUNCTIONS <= total_nodes < 50
    ):
        issues.append(
            {
                "asset_path": bp_path,
                "graph": "All Graphs",
                "severity": "info",
                "rule_id": "BPM006",
                "category": "Maintainability",
                "message": (
                    f"'{bp_name}' has {total_nodes} nodes but "
                    "no functions — organise logic into named "
                    "functions for maintainability."
                ),
                "fix_suggestion": "",
                "is_auto_fixable": False,
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

    # Data-container Blueprints (config holders, item definitions) are
    # idiomatic: many variables, little or no graph logic. "More variables
    # than nodes" cannot distinguish them from abandoned work, so this stays
    # an informational hint rather than a warning.
    if variable_count > total_nodes:
        issues.append(
            {
                "asset_path": bp_path,
                "graph": "All Graphs",
                "severity": "info",
                "rule_id": "BPM007",
                "category": "Maintainability",
                "message": (
                    f"'{bp_name}' has {variable_count} variables "
                    f"but only {total_nodes} nodes — may be "
                    "incomplete or abandoned. Review and complete "
                    "or delete this Blueprint."
                ),
                "fix_suggestion": "",
                "is_auto_fixable": False,
            }
        )
    return issues


# ── ADDITIONAL BEST PRACTICES (BPB004-BPB006) ────────


# BPB004: Blueprint overrides BeginPlay without calling Super
def detect_missing_begin_play_super(
    blueprint: dict,
) -> List[Issue]:
    """BPB004: flag Blueprints that override BeginPlay but do not
    call the parent implementation (Super::BeginPlay).
    Missing the Super call can break initialization chains.
    """
    issues: List[Issue] = []
    bp_path = blueprint.get("path", "")
    bp_name = blueprint.get("name", "")
    stats = blueprint.get("stats", {})
    graphs = blueprint.get("graphs", [])

    # Only flag if the BP has a BeginPlay event but no Super call
    has_begin_play_event = any(
        node.get("type") == "EventBeginPlay"
        for graph in graphs
        for node in graph.get("nodes", [])
    )

    if has_begin_play_event and not stats.get("has_begin_play_super", True):
        issues.append(
            {
                "asset_path": bp_path,
                "graph": "EventGraph",
                "severity": "error",
                "rule_id": "BPB004",
                "category": "Best Practices",
                "message": (
                    f"'{bp_name}' overrides BeginPlay without "
                    "calling Parent: BeginPlay — add a Call to "
                    "Parent Function node to preserve the "
                    "initialization chain."
                ),
                "fix_suggestion": "",
                "is_auto_fixable": False,
            }
        )
    return issues


# BPB005: Blueprint overrides EndPlay without calling Super
def detect_missing_end_play_super(
    blueprint: dict,
) -> List[Issue]:
    """BPB005: flag Blueprints that override EndPlay but do not
    call the parent implementation (Super::EndPlay).
    Missing the Super call can cause resource leaks.
    """
    issues: List[Issue] = []
    bp_path = blueprint.get("path", "")
    bp_name = blueprint.get("name", "")
    stats = blueprint.get("stats", {})
    graphs = blueprint.get("graphs", [])

    has_end_play_event = any(
        node.get("type") == "EventEndPlay"
        for graph in graphs
        for node in graph.get("nodes", [])
    )

    if has_end_play_event and not stats.get("has_end_play_super", True):
        issues.append(
            {
                "asset_path": bp_path,
                "graph": "EventGraph",
                "severity": "error",
                "rule_id": "BPB005",
                "category": "Best Practices",
                "message": (
                    f"'{bp_name}' overrides EndPlay without "
                    "calling Parent: EndPlay — add a Call to "
                    "Parent Function node to ensure proper "
                    "cleanup."
                ),
                "fix_suggestion": "",
                "is_auto_fixable": False,
            }
        )
    return issues


# BPB006: Public function without tooltip
def detect_function_no_tooltip(
    blueprint: dict,
) -> List[Issue]:
    """BPB006: flag public Blueprint functions that have no tooltip.
    Public functions are part of the class API — they should have
    a description so other developers understand their purpose.
    """
    issues: List[Issue] = []
    bp_path = blueprint.get("path", "")
    functions = blueprint.get("functions", [])

    for func in functions:
        func_name = func.get("name", "")
        is_public = func.get("is_public", True)
        has_tooltip = func.get("has_tooltip", False)

        if is_public and not has_tooltip:
            issues.append(
                {
                    "asset_path": bp_path,
                    "graph": func_name,
                    "severity": "warning",
                    "rule_id": "BPB006",
                    "category": "Best Practices",
                    "message": (
                        f"Public function '{func_name}' has no "
                        "tooltip — add a description so other "
                        "developers understand its purpose."
                    ),
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
                }
            )
    return issues


# BPB007: Public variable without category
def detect_variable_no_category(
    blueprint: dict,
) -> List[Issue]:
    """BPB007: flag public Blueprint variables without a category.
    Categories organise variables in the Details panel and make
    Blueprints easier to understand for other developers.
    """
    issues: List[Issue] = []
    bp_path = blueprint.get("path", "")
    variables = blueprint.get("variables", [])

    for variable in variables:
        var_name = variable.get("name", "")
        is_public = variable.get("is_public", False)
        category = variable.get("category", "")

        if is_public and (not category or category.lower() in ("", "default")):
            issues.append(
                {
                    "asset_path": bp_path,
                    "graph": "Variables",
                    "severity": "warning",
                    "rule_id": "BPB007",
                    "category": "Best Practices",
                    "message": (
                        f"Public variable '{var_name}' has no "
                        "category — assign a category to organise "
                        "variables in the Details panel."
                    ),
                    "fix_suggestion": (
                        f"Assign a category to '{var_name}' "
                        "(e.g. 'Combat', 'Movement', 'UI')"
                    ),
                    "is_auto_fixable": True,
                }
            )
    return issues


# ── SECURITY (BPS) ───────────────────────────────────


# BPS001: Authority check missing for replicated variable writes
def detect_missing_authority_check(
    blueprint: dict,
) -> List[Issue]:
    """BPS001: flag Blueprints that modify replicated variables
    without a HasAuthority or SwitchHasAuthority guard.
    In multiplayer, only the server should modify replicated
    state. Clients writing replicated variables directly can
    cause desync, cheating, or server rejection.
    """
    issues: List[Issue] = []
    bp_path = blueprint.get("path", "")
    bp_name = blueprint.get("name", "")
    variables = blueprint.get("variables", [])
    graphs = blueprint.get("graphs", [])

    # Check if the Blueprint has any replicated variables
    replicated_vars = {
        v.get("name", "") for v in variables if v.get("is_replicated", False)
    }

    if not replicated_vars:
        return issues

    # Authority-related node types the plugin may export
    _AUTHORITY_TYPES: frozenset = frozenset(
        {
            "HasAuthority",
            "SwitchHasAuthority",
            "IsServer",
            "IsLocalController",
            "K2Node_HasAuthority",
        }
    )

    for graph in graphs:
        graph_name = graph.get("name", "Unknown")
        nodes = graph.get("nodes", [])

        node_types = {node.get("type", "") for node in nodes}

        has_authority_check = bool(node_types & _AUTHORITY_TYPES)

        # Check if any Set node targets a replicated variable
        sets_replicated = any(
            node.get("type") == "SetVariable"
            and node.get("variable_name", "") in replicated_vars
            for node in nodes
        )

        if sets_replicated and not has_authority_check:
            issues.append(
                {
                    "asset_path": bp_path,
                    "graph": graph_name,
                    "severity": "error",
                    "rule_id": "BPS001",
                    "category": "Security",
                    "message": (
                        f"'{bp_name}' modifies replicated "
                        f"variable(s) in '{graph_name}' without "
                        "an authority check — add "
                        "SwitchHasAuthority or HasAuthority "
                        "before writing replicated state to "
                        "prevent client-side desync and cheating."
                    ),
                    "fix_suggestion": (
                        "Add a SwitchHasAuthority node before "
                        "the Set node and only allow the "
                        "Authority branch to write the variable."
                    ),
                    "is_auto_fixable": False,
                }
            )
    return issues


# BPS003: ExecuteConsoleCommand in Blueprint
def detect_console_command_usage(
    blueprint: dict,
) -> List[Issue]:
    """BPS003: flag Blueprints that contain ExecuteConsoleCommand nodes.
    Console commands can change game state, enable cheats, or expose
    debug functionality. In shipping builds this is a security risk
    and potential exploit vector. Remove or gate behind development-
    only checks.
    """
    issues: List[Issue] = []
    bp_path = blueprint.get("path", "")
    bp_name = blueprint.get("name", "")
    graphs = blueprint.get("graphs", [])

    _CONSOLE_TYPES: frozenset = frozenset(
        {
            "ExecuteConsoleCommand",
            "K2Node_ExecuteConsoleCommand",
            "ConsoleCommand",
        }
    )

    for graph in graphs:
        graph_name = graph.get("name", "Unknown")
        nodes = graph.get("nodes", [])

        console_count = sum(
            node.get("count", 0) for node in nodes if node.get("type") in _CONSOLE_TYPES
        )

        if console_count > 0:
            issues.append(
                {
                    "asset_path": bp_path,
                    "graph": graph_name,
                    "severity": "error",
                    "rule_id": "BPS003",
                    "category": "Security",
                    "message": (
                        f"ExecuteConsoleCommand found in "
                        f"'{bp_name}' graph '{graph_name}' "
                        f"({console_count} instance(s)) — "
                        "console commands can change game "
                        "state and enable cheats. Remove for "
                        "shipping builds or gate behind a "
                        "development-only check."
                    ),
                    "fix_suggestion": (
                        "Remove ExecuteConsoleCommand or wrap "
                        "it with a UE_BUILD_SHIPPING / "
                        "WITH_EDITOR preprocessor check."
                    ),
                    "is_auto_fixable": False,
                }
            )
    return issues


# ── PERFORMANCE (BPP) cont. ───────────────────────────


# BPP006: PrintString node left in Blueprint
def detect_print_string_in_bp(
    blueprint: dict,
) -> List[Issue]:
    """BPP006: flag Blueprints that contain PrintString or PrintText nodes.
    These are debug nodes — in shipping builds they produce log spam,
    add overhead, and in multiplayer they replicate the message to all
    clients. Remove them before shipping or replace with proper logging.
    """
    issues: List[Issue] = []
    bp_path = blueprint.get("path", "")
    bp_name = blueprint.get("name", "")
    graphs = blueprint.get("graphs", [])

    _PRINT_TYPES: frozenset = frozenset(
        {
            "PrintString",
            "K2Node_PrintString",
            "PrintText",
            "K2Node_PrintText",
        }
    )

    for graph in graphs:
        graph_name = graph.get("name", "Unknown")
        nodes = graph.get("nodes", [])

        print_count = sum(
            node.get("count", 0) for node in nodes if node.get("type") in _PRINT_TYPES
        )

        if print_count > 0:
            issues.append(
                {
                    "asset_path": bp_path,
                    "graph": graph_name,
                    "severity": "warning",
                    "rule_id": "BPP006",
                    "category": "Performance",
                    "message": (
                        f"PrintString/PrintText found in '{bp_name}' "
                        f"graph '{graph_name}' ({print_count} instance(s)) "
                        "— debug print nodes cause log spam and replicate "
                        "to all clients in multiplayer. Remove before shipping."
                    ),
                    "fix_suggestion": (
                        "Remove PrintString nodes or replace with "
                        "UE_LOG for server-side logging that does "
                        "not replicate."
                    ),
                    "is_auto_fixable": False,
                }
            )
    return issues


# ── PERFORMANCE (BPP) cont. ───────────────────────────


# BPP007: SetTimer without ClearTimer in EndPlay
def detect_timer_not_cleared(
    blueprint: dict,
) -> List[Issue]:
    """BPP007: flag Blueprints that call SetTimer in BeginPlay but have
    no ClearTimer in EndPlay. Timer handles that outlive the actor prevent
    garbage collection, fire callbacks on destroyed objects, and cause
    crashes in multiplayer when the owning actor is removed mid-session.
    Always pair SetTimer with ClearTimer or ClearAndInvalidateTimerHandle
    in EndPlay.
    """
    issues: List[Issue] = []
    bp_path = blueprint.get("path", "")
    bp_name = blueprint.get("name", "")
    graphs = blueprint.get("graphs", [])

    _SET_TIMER_TYPES: frozenset = frozenset(
        {
            "SetTimer",
            "K2Node_SetTimer",
            "SetTimerByEvent",
            "K2Node_SetTimerByEvent",
            "SetTimerByFunctionName",
            "K2Node_SetTimerByFunctionName",
        }
    )
    _CLEAR_TIMER_TYPES: frozenset = frozenset(
        {
            "ClearTimer",
            "K2Node_ClearTimer",
            "ClearAndInvalidateTimerHandle",
            "K2Node_ClearAndInvalidateTimerHandle",
            "PauseTimer",
        }
    )

    graphs_by_name: dict = {}
    for graph in graphs:
        graphs_by_name[graph.get("name", "").lower()] = graph

    begin_graph = graphs_by_name.get("eventbeginplay") or graphs_by_name.get(
        "beginplay"
    )
    end_graph = graphs_by_name.get("eventendplay") or graphs_by_name.get("endplay")

    if not begin_graph:
        return issues

    timer_count = sum(
        node.get("count", 0)
        for node in begin_graph.get("nodes", [])
        if node.get("type") in _SET_TIMER_TYPES
    )

    if timer_count == 0:
        return issues

    clear_count = 0
    if end_graph:
        clear_count = sum(
            node.get("count", 0)
            for node in end_graph.get("nodes", [])
            if node.get("type") in _CLEAR_TIMER_TYPES
        )

    if clear_count == 0:
        issues.append(
            {
                "asset_path": bp_path,
                "graph": "EventBeginPlay",
                "severity": "warning",
                "rule_id": "BPP007",
                "category": "Performance",
                "message": (
                    f"'{bp_name}' starts {timer_count} timer(s) in BeginPlay "
                    "but does not clear them in EndPlay — timer handles that "
                    "outlive the actor fire on destroyed objects and block "
                    "garbage collection. Add ClearAndInvalidateTimerHandle "
                    "in EventEndPlay."
                ),
                "fix_suggestion": (
                    "Add ClearAndInvalidateTimerHandle for each timer "
                    "handle in EventEndPlay."
                ),
                "is_auto_fixable": False,
            }
        )
    return issues


# ── MAINTAINABILITY (BPM) cont. ───────────────────────


# BPM008: Blueprint with too many variables
def detect_excessive_variables(
    blueprint: dict,
) -> List[Issue]:
    """BPM008: flag Blueprints that declare more variables than the
    configured threshold. A large number of variables is a strong signal
    of a god-class — a Blueprint that has grown beyond a single
    responsibility. Split logic into Actor Components or child Blueprints
    to improve maintainability and reuse.
    """
    issues: List[Issue] = []
    bp_path = blueprint.get("path", "")
    bp_name = blueprint.get("name", "")
    variables = blueprint.get("variables", [])

    # Configurable: flag when a Blueprint has more variables than this.
    _MAX_VARIABLES: int = 20

    var_count = len(variables)
    if var_count > _MAX_VARIABLES:
        issues.append(
            {
                "asset_path": bp_path,
                "graph": "Variables",
                "severity": "warning",
                "rule_id": "BPM008",
                "category": "Maintainability",
                "message": (
                    f"'{bp_name}' has {var_count} variables "
                    f"(max: {_MAX_VARIABLES}) — consider splitting "
                    "logic into Actor Components or child Blueprints "
                    "to reduce responsibility and improve reuse."
                ),
                "fix_suggestion": (
                    "Move related variables and logic into an "
                    "Actor Component Blueprint."
                ),
                "is_auto_fixable": False,
            }
        )
    return issues


# ── PERFORMANCE (BPP) cont. ───────────────────────────


# BPP010: GetOwner / GetInstigator without validity check
def detect_get_owner_no_check(
    blueprint: dict,
) -> List[Issue]:
    """BPP010: flag Blueprints that call GetOwner, GetInstigator, or
    GetOwningPawn without a downstream IsValid / IsValidLowLevel node
    in the same graph. These return nullptr when the actor has no
    owner, is unpossessed, or has been destroyed — dereferencing
    without a validity check crashes at runtime, especially in
    multiplayer where ownership changes frequently.
    """
    issues: List[Issue] = []
    bp_path = blueprint.get("path", "")
    bp_name = blueprint.get("name", "")
    graphs = blueprint.get("graphs", [])

    _GET_OWNER_TYPES: frozenset = frozenset(
        {
            "GetOwner",
            "K2Node_GetOwner",
            "GetInstigator",
            "K2Node_GetInstigator",
            "GetOwningPawn",
            "K2Node_GetOwningPawn",
            "GetOwnerRole",
        }
    )
    _VALIDITY_TYPES: frozenset = frozenset(
        {
            "IsValid",
            "K2Node_IsValid",
            "IsValidLowLevel",
            "IsStillValid",
        }
    )

    for graph in graphs:
        graph_name = graph.get("name", "Unknown")
        nodes = graph.get("nodes", [])
        node_types = {node.get("type", "") for node in nodes}

        has_get_owner = bool(node_types & _GET_OWNER_TYPES)
        has_validity_check = bool(node_types & _VALIDITY_TYPES)

        if has_get_owner and not has_validity_check:
            found = sorted(node_types & _GET_OWNER_TYPES)
            issues.append(
                {
                    "asset_path": bp_path,
                    "graph": graph_name,
                    "severity": "error",
                    "rule_id": "BPP010",
                    "category": "Performance",
                    "message": (
                        f"'{bp_name}' calls {', '.join(found)} in "
                        f"'{graph_name}' without an IsValid check — "
                        "GetOwner returns nullptr when the actor has "
                        "no owner or is unpossessed. Always validate "
                        "the result before use to prevent crashes."
                    ),
                    "fix_suggestion": (
                        "Connect the return value of GetOwner to an "
                        "IsValid node and branch on the result before "
                        "accessing any properties."
                    ),
                    "is_auto_fixable": False,
                }
            )
    return issues


# ── BEST PRACTICES (BPB) cont. ────────────────────────


# BPB009: Public function name does not follow verb-noun convention
def detect_function_naming_convention(
    blueprint: dict,
) -> List[Issue]:
    """BPB009: flag public Blueprint functions whose names do not start
    with a recognised action verb. UE5 convention expects verb-noun
    pairs (GetHealth, SetSpeed, CalculateDamage, IsAlive): Get/Set for
    accessors, Is/Has/Can/Should for boolean queries, a strong verb for
    actions. Noun-only names are easily confused with variables.
    """
    issues: List[Issue] = []
    bp_path = blueprint.get("path", "")
    bp_name = blueprint.get("name", "")
    functions = blueprint.get("functions", [])

    # Common UE5-style action verb prefixes expected on public functions.
    _VERB_PREFIXES: tuple = (
        "Get",
        "Set",
        "Is",
        "Has",
        "Can",
        "Should",
        "Will",
        "Calculate",
        "Compute",
        "Damage",
        "Apply",
        "Reset",
        "Update",
        "Handle",
        "On",
        "Check",
        "Find",
        "Load",
        "Spawn",
        "Destroy",
        "Init",
        "Setup",
        "Start",
        "Stop",
        "Enable",
        "Disable",
        "Toggle",
        "Add",
        "Remove",
        "Create",
        "Build",
        "Register",
        "Unregister",
        "Notify",
        "Execute",
        "Validate",
        "Process",
        "Play",
        "Pause",
        "Request",
        "Fire",
        "Trigger",
        "Activate",
        "Deactivate",
    )

    for func in functions:
        func_name = func.get("name", "")
        is_public = func.get("is_public", False)

        if not func_name or not is_public:
            continue

        # Skip UE5 built-in overrides — these are valid without verb prefix.
        _BUILTIN_OVERRIDES: frozenset = frozenset(
            {
                "BeginPlay",
                "EndPlay",
                "Tick",
                "ReceiveBeginPlay",
                "ReceiveEndPlay",
                "ReceiveTick",
                "ConstructionScript",
                "UserConstructionScript",
            }
        )
        if func_name in _BUILTIN_OVERRIDES:
            continue

        if not any(func_name.startswith(prefix) for prefix in _VERB_PREFIXES):
            issues.append(
                {
                    "asset_path": bp_path,
                    "graph": func_name,
                    "severity": "warning",
                    "rule_id": "BPB009",
                    "category": "Best Practices",
                    "message": (
                        f"Public function '{func_name}' in '{bp_name}' "
                        "does not start with an action verb — UE5 "
                        "convention expects verb-noun names such as "
                        "GetHealth, SetSpeed, CalculateDamage, IsAlive."
                    ),
                    "fix_suggestion": (
                        f"Rename '{func_name}' to follow verb-noun "
                        "convention (e.g. Get/Set/Is/Has/Calculate + noun)."
                    ),
                    "is_auto_fixable": False,
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

    Best Practices (BPB): BPB001-BPB007
    Performance (BPP):    BPP001-BPP005
    Maintainability (BPM): BPM001-BPM007
    Security (BPS):       BPS001, BPS003
    """
    issues: List[Issue] = []

    # Best Practices
    issues += detect_missing_bp_prefix(blueprint)
    issues += detect_no_functions_large_graph(blueprint)
    issues += detect_generic_variable_name(blueprint)
    issues += detect_missing_begin_play_super(blueprint)
    issues += detect_missing_end_play_super(blueprint)
    issues += detect_function_no_tooltip(blueprint)
    issues += detect_variable_no_category(blueprint)

    # Performance
    issues += detect_tick_enabled(blueprint)
    issues += detect_excessive_casts(blueprint)
    issues += detect_heavy_event_tick(blueprint)
    issues += detect_delay_in_tick(blueprint)
    issues += detect_get_all_actors_in_tick(blueprint)
    issues += detect_print_string_in_bp(blueprint)
    issues += detect_timer_not_cleared(blueprint)
    issues += detect_get_owner_no_check(blueprint)

    # Best Practices (cont.)
    issues += detect_function_naming_convention(blueprint)

    # Maintainability
    issues += detect_unused_variables(blueprint)
    issues += detect_disconnected_nodes(blueprint)
    issues += detect_large_blueprint(blueprint)
    issues += detect_high_complexity_function(blueprint)
    issues += detect_large_graph(blueprint)
    issues += detect_blueprint_no_functions(blueprint)
    issues += detect_abandoned_blueprint(blueprint)
    issues += detect_excessive_variables(blueprint)

    # Security
    issues += detect_missing_authority_check(blueprint)
    issues += detect_console_command_usage(blueprint)

    # Inject fix_instruction for auto-fixable BP rules so the
    # UE5 plugin can execute the fix directly via its editor API.
    if build_bp_fix_instruction is not None:
        for issue in issues:
            if issue.get("is_auto_fixable"):
                fix_inst = build_bp_fix_instruction(issue)
                if fix_inst:
                    issue["fix_instruction"] = fix_inst

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
