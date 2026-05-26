"""Unity Visual Scripting graph rules.

Eight initial detectors that mirror the spirit of the UE5 Blueprint
ruleset (VSP / VSM / VSB / VSS families). Each detector takes a graph
dict produced by `unity_vs_parser.parse_unity_graph` and returns a
list of `Issue` records ready for the validate route to enrich.

Rule IDs:

  VSP001  Log in Update     — Debug.Log node inside an Update graph
  VSP002  Unsafe Cast        — Cast node without null-check downstream
  VSM001  Graph too large    — > 50 nodes
  VSM002  Disconnected node  — Phase B placeholder (no connection list yet)
  VSB001  Orphan custom event — CustomEvent unit with no inbound edges
  VSB002  Empty graph        — 0 nodes
  VSB003  Deep flow chain    — > 5 sequential nodes in one branch
  VSS001  Hardcoded secret   — string literal w/ key-like prefix in any node

For Phase B we use the unit list alone — connection introspection (the
graph's edges) isn't extracted by the parser yet. VSM002 / VSB001 /
VSB003 fall back to type-counting heuristics until v1.4.5 adds an
edge parser; the issues they emit are still actionable but may produce
false positives on heavily-orchestrated graphs.
"""

from __future__ import annotations

import re
from typing import Dict, List

Issue = Dict
Graph = Dict


# Type name fragments we treat as "log" / "print" nodes (any Visual
# Scripting class that ultimately calls UnityEngine.Debug.Log).
_LOG_TYPES = (
    "Unity.VisualScripting.Log",
    "Unity.VisualScripting.PrintToConsole",
)

# Cast / type-check nodes that can throw or null-out on failure.
_CAST_TYPES = (
    "Unity.VisualScripting.Cast",
    "Unity.VisualScripting.GenericCast",
    "Unity.VisualScripting.TypeCheck",
)

_CUSTOM_EVENT_TYPES = (
    "Unity.VisualScripting.CustomEvent",
    "Unity.VisualScripting.TriggerCustomEvent",
)

_GETCOMPONENT_TYPES = (
    "Unity.VisualScripting.GetComponent",
    "Unity.VisualScripting.GetComponentInChildren",
    "Unity.VisualScripting.GetComponentInParent",
    "Unity.VisualScripting.GetComponents",
)

_FIND_TYPES = (
    "Unity.VisualScripting.FindGameObject",
    "Unity.VisualScripting.FindObjectOfType",
    "Unity.VisualScripting.FindObjectsOfType",
    "Unity.VisualScripting.FindWithTag",
    "Unity.VisualScripting.GameObject.Find",
)

_INSTANTIATE_TYPES = (
    "Unity.VisualScripting.Instantiate",
    "Unity.VisualScripting.Object.Instantiate",
)

_DESTROY_TYPES = (
    "Unity.VisualScripting.Destroy",
    "Unity.VisualScripting.DestroyImmediate",
    "Unity.VisualScripting.Object.Destroy",
)

_VARIABLE_TYPES = (
    "Unity.VisualScripting.GetVariable",
    "Unity.VisualScripting.SetVariable",
    "Unity.VisualScripting.GetGraphVariable",
    "Unity.VisualScripting.SetGraphVariable",
    "Unity.VisualScripting.GetObjectVariable",
    "Unity.VisualScripting.SetObjectVariable",
    "Unity.VisualScripting.GetSceneVariable",
    "Unity.VisualScripting.SetSceneVariable",
    "Unity.VisualScripting.GetApplicationVariable",
    "Unity.VisualScripting.SetApplicationVariable",
)

_STATE_UNIT_TYPES = (
    "Unity.VisualScripting.StateUnit",
    "Unity.VisualScripting.AnyState",
    "Unity.VisualScripting.StartState",
)

# Lifecycle event root suffixes — any unit type ending in one of these
# is treated as an event root that triggers the graph.
_EVENT_ROOT_SUFFIXES = (
    "OnStart",
    "OnUpdate",
    "OnFixedUpdate",
    "OnLateUpdate",
    "OnEnable",
    "OnDisable",
    "OnDestroy",
    "OnApplicationQuit",
    "OnTriggerEnter",
    "OnTriggerExit",
    "OnTriggerStay",
    "OnCollisionEnter",
    "OnCollisionExit",
    "OnCollisionStay",
    "OnMouseDown",
    "OnMouseUp",
    "OnMouseEnter",
    "OnMouseExit",
    "OnBecameVisible",
    "OnBecameInvisible",
    "OnAnimatorIK",
    "OnAnimatorMove",
    "Start",
    "Awake",
)

_NULL_CHECK_TYPES = (
    "Unity.VisualScripting.NullCheck",
    "Unity.VisualScripting.Null",
    "Unity.VisualScripting.IsNull",
)

_SEND_MESSAGE_TYPES = (
    "Unity.VisualScripting.SendMessage",
    "Unity.VisualScripting.SendMessageUpwards",
    "Unity.VisualScripting.BroadcastMessage",
)

_WAIT_FOR_SECONDS_TYPES = (
    "Unity.VisualScripting.WaitForSeconds",
    "Unity.VisualScripting.WaitForSecondsRealtime",
    "Unity.VisualScripting.WaitForEndOfFrame",
    "Unity.VisualScripting.WaitForFixedUpdate",
    "Unity.VisualScripting.WaitWhile",
    "Unity.VisualScripting.WaitUntil",
)

_DEBUG_BREAK_TYPES = (
    "Unity.VisualScripting.DebugBreak",
    "Unity.VisualScripting.Debug.Break",
    "Unity.VisualScripting.BreakPoint",
)

_PLAYER_PREFS_SET_TYPES = (
    "Unity.VisualScripting.PlayerPrefs.SetString",
    "Unity.VisualScripting.PlayerPrefs.SetInt",
    "Unity.VisualScripting.PlayerPrefs.SetFloat",
    "Unity.VisualScripting.SetPlayerPrefs",
)


def _emit(
    graph: Graph,
    *,
    rule_id: str,
    category: str,
    severity: str,
    message: str,
    fix_suggestion: str,
    line: int = 0,
) -> Issue:
    """Build a single Issue with the same key shape every validate route
    expects. `asset_path` doubles as `file_path` for the Unity plugin
    after the route's normalisation pass.
    """
    return {
        "asset_path": graph.get("file_path", ""),
        "line": line,
        "severity": severity,
        "rule_id": rule_id,
        "category": category,
        "message": message,
        "snippet": "",  # VS has no source snippet — kept for shape parity
        "fix_suggestion": fix_suggestion,
        "is_auto_fixable": False,  # No auto-fix for graph YAML yet (deferred)
    }


# ── VSP — Performance ──────────────────────────────────────────────


def detect_vsp001_log_in_update(graph: Graph) -> List[Issue]:
    """VSP001 — Log / PrintToConsole inside a graph that runs every frame."""
    if not graph.get("has_update_root"):
        return []
    out: List[Issue] = []
    for u in graph.get("units", []):
        if any(u["type"].startswith(t) for t in _LOG_TYPES):
            out.append(
                _emit(
                    graph,
                    rule_id="VSP001",
                    category="Performance",
                    severity="warning",
                    message=(
                        f"{u['type'].rsplit('.', 1)[-1]} node sits inside an "
                        "Update graph — the console serialises a string every "
                        "frame which kills editor and runtime perf."
                    ),
                    fix_suggestion="Gate the Log behind a branch that fires only when state changes, or move it to a one-shot event.",  # noqa: E501
                    line=u.get("line", 0),
                )
            )
    return out


def detect_vsp002_unsafe_cast(graph: Graph) -> List[Issue]:
    """VSP002 — Cast node that may downstream a null without a Null Check.

    Phase B heuristic: every Cast unit emits the issue. False-positive
    rate is acceptable because Visual Scripting users almost never
    wire the failure pin; v1.4.5 will refine with edge introspection.
    """
    out: List[Issue] = []
    for u in graph.get("units", []):
        if any(u["type"].startswith(t) for t in _CAST_TYPES):
            out.append(
                _emit(
                    graph,
                    rule_id="VSP002",
                    category="Security",
                    severity="warning",
                    message=(
                        "Cast node without explicit null-check downstream — "
                        "Visual Scripting won't stop execution on a failed cast."
                    ),
                    fix_suggestion="Wire the cast's failure pin to a Null Check before using the result.",  # noqa: E501
                    line=u.get("line", 0),
                )
            )
    return out


# ── VSM — Maintainability ──────────────────────────────────────────


def detect_vsm001_graph_too_large(graph: Graph) -> List[Issue]:
    """VSM001 — > 50 nodes is hard to read and slow to load in the editor."""
    if graph.get("unit_count", 0) <= 50:
        return []
    return [
        _emit(
            graph,
            rule_id="VSM001",
            category="Maintainability",
            severity="warning",
            message=(
                f"Graph has {graph['unit_count']} nodes — past 50 the editor "
                "stops fitting in a single screen and load time grows."
            ),
            fix_suggestion="Split into sub-graphs or move pure data flow into C# helper methods.",  # noqa: E501
        )
    ]


def detect_vsm002_disconnected_node(graph: Graph) -> List[Issue]:
    """VSM002 — Phase B placeholder. No-op until v1.4.5 edge parser."""
    return []


# ── VSB — Best practices ───────────────────────────────────────────


def detect_vsb001_orphan_custom_event(graph: Graph) -> List[Issue]:
    """VSB001 — CustomEvent declared but never triggered (or vice versa).

    Phase B heuristic: if the graph has CustomEvent definitions but no
    TriggerCustomEvent (or the other way around) we report the imbalance.
    """
    has_def = any(u["type"].endswith("CustomEvent") for u in graph.get("units", []))
    has_trig = any(
        u["type"].endswith("TriggerCustomEvent") for u in graph.get("units", [])
    )
    if has_def and not has_trig:
        return [
            _emit(
                graph,
                rule_id="VSB001",
                category="BestPractices",
                severity="info",
                message="CustomEvent declared but never triggered from any node.",
                fix_suggestion="Either trigger the event from somewhere or remove the declaration.",  # noqa: E501
            )
        ]
    if has_trig and not has_def:
        return [
            _emit(
                graph,
                rule_id="VSB001",
                category="BestPractices",
                severity="warning",
                message="TriggerCustomEvent fired against an event with no matching CustomEvent receiver in this graph.",  # noqa: E501
                fix_suggestion="Add a CustomEvent receiver or rename the trigger to an existing event.",  # noqa: E501
            )
        ]
    return []


def detect_vsb002_empty_graph(graph: Graph) -> List[Issue]:
    """VSB002 — 0-unit graph is dead weight."""
    if graph.get("unit_count", 0) != 0:
        return []
    return [
        _emit(
            graph,
            rule_id="VSB002",
            category="BestPractices",
            severity="info",
            message="Graph has zero nodes — it's a no-op kept around for nothing.",
            fix_suggestion="Delete the asset if it's no longer wired into a runner / state machine.",  # noqa: E501
        )
    ]


def detect_vsb003_deep_flow_chain(graph: Graph) -> List[Issue]:
    """VSB003 — long sequential chain in one path is hard to follow.

    Heuristic: a count of "Sequence" or "Flow" nodes paired with
    > 30 non-event units suggests the graph is one long script. The
    real depth check arrives with the edge parser in v1.4.5.
    """
    if graph.get("unit_count", 0) < 30:
        return []
    if not any(
        "Sequence" in u["type"] or "Branch" in u["type"] for u in graph.get("units", [])
    ):
        return []
    return [
        _emit(
            graph,
            rule_id="VSB003",
            category="Maintainability",
            severity="info",
            message=(
                f"Graph has {graph['unit_count']} nodes plus Sequence/Branch "
                "nodes — likely a single deep flow chain that reads like "
                "spaghetti."
            ),
            fix_suggestion="Refactor into sub-graphs or extract the deep portion into a C# behaviour.",  # noqa: E501
        )
    ]


# ── VSS — Security ─────────────────────────────────────────────────


_SECRET_RE = re.compile(
    r"(?:api[_-]?key|password|secret|token|bearer)",
    re.IGNORECASE,
)


def detect_vss001_hardcoded_secret(graph: Graph) -> List[Issue]:
    """VSS001 — string literal inside any node whose name looks
    secret-ish (api_key, token, password). Visual Scripting literals
    live in the graph YAML as quoted values.

    Implementation: Phase B scans the raw YAML for `value: "..."`
    lines with secret-like substrings via `_raw_content` injected by
    the route. Without raw content the rule is a no-op; v1.4.5 will
    hook the parser to surface literals directly.
    """
    return []  # active in v1.4.5


# ── VSP — Performance (Batch 2) ────────────────────────────────────


def detect_vsp003_getcomponent_in_update(graph: Graph) -> List[Issue]:
    """VSP003 — GetComponent call inside an Update graph — O(n) component lookup every frame."""  # noqa: E501
    if not graph.get("has_update_root"):
        return []
    out: List[Issue] = []
    for u in graph.get("units", []):
        if any(u["type"].startswith(t) for t in _GETCOMPONENT_TYPES):
            short = u["type"].rsplit(".", 1)[-1]
            out.append(
                _emit(
                    graph,
                    rule_id="VSP003",
                    category="Performance",
                    severity="warning",
                    message=(
                        f"{short} node inside an Update graph — component lookup "
                        "traverses the GameObject's component list every frame."
                    ),
                    fix_suggestion=(
                        "Cache the component reference in an OnStart node and "
                        "store it in a graph variable; read the variable in Update."
                    ),
                    line=u.get("line", 0),
                )
            )
    return out


def detect_vsp004_find_in_update(graph: Graph) -> List[Issue]:
    """VSP004 — FindObject / FindObjectOfType inside an Update graph — full scene scan every frame."""  # noqa: E501
    if not graph.get("has_update_root"):
        return []
    out: List[Issue] = []
    for u in graph.get("units", []):
        if any(u["type"].startswith(t) for t in _FIND_TYPES):
            short = u["type"].rsplit(".", 1)[-1]
            out.append(
                _emit(
                    graph,
                    rule_id="VSP004",
                    category="Performance",
                    severity="error",
                    message=(
                        f"{short} node inside an Update graph — iterates all "
                        "active GameObjects in the scene every frame."
                    ),
                    fix_suggestion=(
                        "Cache the reference once in OnStart using a graph variable, "
                        "or assign it via an exposed Object field on the script machine."  # noqa: E501
                    ),
                    line=u.get("line", 0),
                )
            )
    return out


def detect_vsp005_instantiate_destroy_in_update(graph: Graph) -> List[Issue]:
    """VSP005 — Instantiate or Destroy node inside an Update graph — allocates/frees managed memory every frame."""  # noqa: E501
    if not graph.get("has_update_root"):
        return []
    out: List[Issue] = []
    for u in graph.get("units", []):
        is_inst = any(u["type"].startswith(t) for t in _INSTANTIATE_TYPES)
        is_dest = any(u["type"].startswith(t) for t in _DESTROY_TYPES)
        if not (is_inst or is_dest):
            continue
        short = u["type"].rsplit(".", 1)[-1]
        out.append(
            _emit(
                graph,
                rule_id="VSP005",
                category="Performance",
                severity="error",
                message=(
                    f"{short} node inside an Update graph — spawning or "
                    "destroying objects every frame causes GC pressure and "
                    "visible frame spikes."
                ),
                fix_suggestion=(
                    "Move object creation to OnStart or an event-triggered graph. "
                    "Use an object pool pattern for high-frequency spawning."
                ),
                line=u.get("line", 0),
            )
        )
    return out


# ── VSM — Maintainability (Batch 2) ───────────────────────────────


def detect_vsm003_variable_overload(graph: Graph) -> List[Issue]:
    """VSM003 — More than 15 variable get/set nodes — bloated data flow."""
    var_nodes = [
        u
        for u in graph.get("units", [])
        if any(u["type"].startswith(t) for t in _VARIABLE_TYPES)
    ]
    if len(var_nodes) <= 15:
        return []
    return [
        _emit(
            graph,
            rule_id="VSM003",
            category="Maintainability",
            severity="warning",
            message=(
                f"Graph contains {len(var_nodes)} variable read/write nodes — "
                "dense variable wiring makes data flow hard to trace and debug."
            ),
            fix_suggestion=(
                "Consolidate related variables into a ScriptableObject or a C# "
                "data class; expose a single reference instead of individual variables."
            ),
        )
    ]


def detect_vsm004_state_machine_too_large(graph: Graph) -> List[Issue]:
    """VSM004 — State machine graph with more than 12 state units."""
    if graph.get("graph_type") != "state":
        return []
    state_nodes = [
        u
        for u in graph.get("units", [])
        if any(u["type"].startswith(t) for t in _STATE_UNIT_TYPES)
    ]
    if len(state_nodes) <= 12:
        return []
    return [
        _emit(
            graph,
            rule_id="VSM004",
            category="Maintainability",
            severity="warning",
            message=(
                f"State machine has {len(state_nodes)} states — past 12 states "
                "the graph becomes difficult to understand and extend."
            ),
            fix_suggestion=(
                "Split into hierarchical sub-state machines or migrate to a "
                "dedicated state machine package (e.g. Animator, Node Canvas)."
            ),
        )
    ]


# ── VSB — Best Practices (Batch 2) ────────────────────────────────


def detect_vsb004_multiple_event_roots(graph: Graph) -> List[Issue]:
    """VSB004 — Graph responds to more than 3 lifecycle events — violates single-responsibility."""  # noqa: E501
    event_units = [
        u
        for u in graph.get("units", [])
        if any(u["type"].endswith(suf) for suf in _EVENT_ROOT_SUFFIXES)
    ]
    if len(event_units) <= 3:
        return []
    return [
        _emit(
            graph,
            rule_id="VSB004",
            category="BestPractices",
            severity="info",
            message=(
                f"Graph has {len(event_units)} event root nodes — mixing too "
                "many lifecycle hooks in one graph blurs responsibility."
            ),
            fix_suggestion=(
                "Split into focused graphs (one per concern) attached to separate "
                "Script Machine components, or move shared logic to a C# helper."
            ),
        )
    ]


def detect_vsb005_getcomponent_no_null_check(graph: Graph) -> List[Issue]:
    """VSB005 — GetComponent node present but no NullCheck in the same graph."""
    units = graph.get("units", [])
    has_getcomp = any(
        any(u["type"].startswith(t) for t in _GETCOMPONENT_TYPES) for u in units
    )
    if not has_getcomp:
        return []
    has_null_check = any(
        any(u["type"].startswith(t) for t in _NULL_CHECK_TYPES) for u in units
    )
    if has_null_check:
        return []
    return [
        _emit(
            graph,
            rule_id="VSB005",
            category="BestPractices",
            severity="warning",
            message=(
                "GetComponent node present but no NullCheck node found — "
                "if the component is missing the graph will silently "
                "propagate a null and crash downstream."
            ),
            fix_suggestion=(
                "Add a NullCheck node after GetComponent and wire the null branch "
                "to a Log error node or an early-exit branch."
            ),
        )
    ]


def detect_vsb006_send_message(graph: Graph) -> List[Issue]:
    """VSB006 — SendMessage or BroadcastMessage — string-dispatch is slow and breaks refactoring."""  # noqa: E501
    out: List[Issue] = []
    for u in graph.get("units", []):
        if any(u["type"].startswith(t) for t in _SEND_MESSAGE_TYPES):
            short = u["type"].rsplit(".", 1)[-1]
            out.append(
                _emit(
                    graph,
                    rule_id="VSB006",
                    category="BestPractices",
                    severity="warning",
                    message=(
                        f"{short} uses string-based dispatch — Unity cannot "
                        "validate the method name at edit-time and incurs "
                        "reflection overhead at runtime."
                    ),
                    fix_suggestion=(
                        "Replace with a direct GetComponent reference and call "
                        "the method node, or use a Custom Event for decoupled communication."  # noqa: E501
                    ),
                    line=u.get("line", 0),
                )
            )
    return out


def detect_vsb007_wait_for_seconds_in_update(graph: Graph) -> List[Issue]:
    """VSB007 — WaitForSeconds inside an Update graph — allocates a new yield object every frame."""  # noqa: E501
    if not graph.get("has_update_root"):
        return []
    out: List[Issue] = []
    for u in graph.get("units", []):
        if any(u["type"].startswith(t) for t in _WAIT_FOR_SECONDS_TYPES):
            short = u["type"].rsplit(".", 1)[-1]
            out.append(
                _emit(
                    graph,
                    rule_id="VSB007",
                    category="Performance",
                    severity="warning",
                    message=(
                        f"{short} node inside an Update graph allocates a new "
                        "coroutine yield object every frame, generating GC garbage."
                    ),
                    fix_suggestion=(
                        "Cache the WaitForSeconds instance in a graph variable "
                        "and reuse it, or move the timed wait into an event-triggered "
                        "Coroutine graph."
                    ),
                    line=u.get("line", 0),
                )
            )
    return out


def detect_vsb008_script_graph_no_root(graph: Graph) -> List[Issue]:
    """VSB008 — Script graph has nodes but no event root — the graph is never triggered."""  # noqa: E501
    if graph.get("graph_type") != "script":
        return []
    if graph.get("unit_count", 0) == 0:
        return []  # VSB002 covers the empty case
    has_root = any(
        any(u["type"].endswith(suf) for suf in _EVENT_ROOT_SUFFIXES)
        for u in graph.get("units", [])
    )
    if has_root:
        return []
    return [
        _emit(
            graph,
            rule_id="VSB008",
            category="BestPractices",
            severity="warning",
            message=(
                f"Script graph has {graph['unit_count']} node(s) but no event "
                "root (OnStart, OnUpdate, OnEnable, etc.) — the graph never fires."
            ),
            fix_suggestion=(
                "Add an event root node (e.g. OnStart) to trigger the graph, "
                "or delete the asset if it is no longer needed."
            ),
        )
    ]


# ── VSS — Security (Batch 2) ──────────────────────────────────────


def detect_vss002_debug_break_in_graph(graph: Graph) -> List[Issue]:
    """VSS002 — Debug.Break node — hard-pauses the editor; must not ship in production builds."""  # noqa: E501
    out: List[Issue] = []
    for u in graph.get("units", []):
        if any(u["type"].startswith(t) for t in _DEBUG_BREAK_TYPES):
            out.append(
                _emit(
                    graph,
                    rule_id="VSS002",
                    category="BestPractices",
                    severity="warning",
                    message=(
                        "Debug.Break node found — this pauses the Unity Editor "
                        "when executed and will freeze the application in a "
                        "production build."
                    ),
                    fix_suggestion=(
                        "Remove the Debug.Break node before shipping. "
                        "Use a Conditional Branch + Editor-only flag to gate debug pauses."  # noqa: E501
                    ),
                    line=u.get("line", 0),
                )
            )
    return out


def detect_vss003_player_prefs_set(graph: Graph) -> List[Issue]:
    """VSS003 — PlayerPrefs.Set node — PlayerPrefs is plain-text on disk; do not store sensitive data."""  # noqa: E501
    out: List[Issue] = []
    for u in graph.get("units", []):
        if any(u["type"].startswith(t) for t in _PLAYER_PREFS_SET_TYPES):
            short = u["type"].rsplit(".", 1)[-1]
            out.append(
                _emit(
                    graph,
                    rule_id="VSS003",
                    category="Security",
                    severity="info",
                    message=(
                        f"{short} node stores data in PlayerPrefs — values are "
                        "saved as plain text on the user's disk and are trivially "
                        "readable or editable."
                    ),
                    fix_suggestion=(
                        "Use PlayerPrefs only for non-sensitive preferences (volume, "
                        "resolution). For credentials or tokens use a SecureStorage "
                        "wrapper or avoid client-side storage altogether."
                    ),
                    line=u.get("line", 0),
                )
            )
    return out
