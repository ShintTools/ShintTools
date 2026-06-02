"""Unity Visual Scripting graph rules.

20 detectors covering performance, maintainability, best practices, and
security (VSP / VSM / VSB / VSS families). Each detector takes a graph
dict produced by `unity_vs_parser.parse_unity_graph` and returns a
list of `Issue` records ready for the validate route.

Rules work with the actual node structure from the embedded JSON:
  - Nodes identified by $type (e.g. "Unity.VisualScripting.Update")
  - InvokeMember nodes with member.name to detect method calls (e.g. Debug.Log)
  - Connection graph to detect orphans, unsafe patterns, etc.

Rule IDs:
  VSP001  Log in Update           - Debug.Log inside an Update graph
  VSP002  Unsafe Cast             - Cast node without null-check
  VSP003  GetComponent in Update  - Component lookup every frame
  VSP004  Find in Update          - Scene scan every frame
  VSP005  Instantiate/Destroy in Update - Memory alloc/free every frame
  VSM001  Graph too large         - > 50 nodes
  VSM002  Disconnected node       - Node with no inbound or outbound edges
  VSM003  Variable overload       - > 15 variable get/set nodes
  VSM004  State machine too large - State graph > 12 states
  VSB001  Orphan custom event     - CustomEvent with no trigger
  VSB002  Empty graph             - 0 nodes
  VSB003  Deep flow chain         - Likely spaghetti (heuristic)
  VSB004  Multiple event roots    - > 3 lifecycle hooks
  VSB005  GetComponent no null    - GetComponent without NullCheck
  VSB006  SendMessage             - String-based dispatch
  VSB007  WaitForSeconds in Update - Yield object alloc per frame
  VSB008  Script graph no root    - Nodes but no event root
  VSS001  Hardcoded secret        - String literal with secret-like name
  VSS002  Debug.Break in graph    - Hard pause in editor/runtime
  VSS003  PlayerPrefs.Set         - Plain-text storage of data
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

Issue = Dict[str, Any]
Graph = Dict[str, Any]
Unit = Dict[str, Any]
Connection = Dict[str, str]


# Type-name suffixes for each category. We compare against the trailing
# segment after the last "." so the same constant catches both fully
# qualified (`Unity.VisualScripting.Update`) and stripped
# (`Update`) names that show up in the wild.
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

_FIND_SUFFIXES = (
    "FindGameObject",
    "FindObjectOfType",
    "FindObjectsOfType",
    "FindWithTag",
)
_INSTANTIATE_OR_DESTROY_SUFFIXES = ("Instantiate", "Destroy", "DestroyImmediate")
_CAST_SUFFIXES = ("Cast", "GenericCast", "TypeCheck", "IsValid")
_NULL_CHECK_SUFFIXES = ("NullCheck", "IsNull")
_VARIABLE_ACCESS_SUFFIXES = (
    "GetVariable",
    "SetVariable",
    "GetGraphVariable",
    "SetGraphVariable",
    "GetObjectVariable",
    "SetObjectVariable",
    "GetSceneVariable",
    "SetSceneVariable",
    "GetApplicationVariable",
    "SetApplicationVariable",
)
_STATE_SUFFIXES = ("StateUnit", "AnyState", "StartState")
_SEND_MESSAGE_SUFFIXES = (
    "SendMessage",
    "SendMessageUpwards",
    "BroadcastMessage",
)
_WAIT_FOR_SECONDS_SUFFIXES = (
    "WaitForSeconds",
    "WaitForSecondsRealtime",
    "WaitForEndOfFrame",
    "WaitForFixedUpdate",
    "WaitWhile",
    "WaitUntil",
)
_DEBUG_BREAK_SUFFIXES = ("DebugBreak", "Debug.Break", "BreakPoint")
_PLAYER_PREFS_SET_SUFFIXES = (
    "PlayerPrefs.SetString",
    "PlayerPrefs.SetInt",
    "PlayerPrefs.SetFloat",
    "SetPlayerPrefs",
)

# Member names + target types for `InvokeMember` nodes, which is how
# Unity VS stores most Unity API calls (Debug.Log, GameObject.Find,
# GetComponent, etc.) instead of dedicated subclasses.
_GETCOMPONENT_MEMBER_NAMES = frozenset(
    {
        "GetComponent",
        "GetComponentInChildren",
        "GetComponentInParent",
        "GetComponents",
    }
)
_FIND_MEMBER_NAMES = frozenset(
    {
        "Find",
        "FindGameObject",
        "FindObjectOfType",
        "FindObjectsOfType",
        "FindWithTag",
    }
)
_INSTANTIATE_DESTROY_MEMBER_NAMES = frozenset(
    {
        "Instantiate",
        "Destroy",
        "DestroyImmediate",
    }
)
_SEND_MESSAGE_MEMBER_NAMES = frozenset(
    {
        "SendMessage",
        "SendMessageUpwards",
        "BroadcastMessage",
    }
)


def _invoked_member(unit: Unit) -> Optional[Dict[str, Any]]:
    """Return the `member` dict if `unit` is an `InvokeMember` node.

    InvokeMember is how Unity VS stores most Unity API method calls
    (Debug.Log, GameObject.GetComponent, PlayerPrefs.SetString, ...).
    The `member` dict holds `name` (method) and `targetType` (class).

    Real Unity VS assets store `member` as a top-level field on the node
    (extracted by the parser into `unit["member"]`). Synthetic/test assets
    may store it inside `defaultValues["member"]` — we check both.
    """
    if not unit["type"].endswith("InvokeMember"):
        return None
    member = unit.get("member") or unit.get("default_values", {}).get("member")
    return member if isinstance(member, dict) else None


def _is_debug_log_call(unit: Unit) -> bool:
    """True for Debug.Log invocations (via `InvokeMember`)."""
    member = _invoked_member(unit)
    if not member:
        return False
    return (
        member.get("name") == "Log" and member.get("targetType") == "UnityEngine.Debug"
    )  # noqa: E501


def _is_getcomponent_call(unit: Unit) -> bool:
    """True for GetComponent / GetComponentInChildren / etc. calls."""
    member = _invoked_member(unit)
    if not member:
        return False
    return member.get("name") in _GETCOMPONENT_MEMBER_NAMES


def _is_find_call(unit: Unit) -> bool:
    """True for any scene-scanning Find* node or InvokeMember call."""
    member = _invoked_member(unit)
    if member and member.get("name") in _FIND_MEMBER_NAMES:
        return True
    return any(unit["type"].endswith(suffix) for suffix in _FIND_SUFFIXES)


def _is_instantiate_or_destroy(unit: Unit) -> bool:
    """True for Instantiate / Destroy nodes or InvokeMember calls."""
    member = _invoked_member(unit)
    if member and member.get("name") in _INSTANTIATE_DESTROY_MEMBER_NAMES:
        return True
    return any(
        unit["type"].endswith(suffix) for suffix in _INSTANTIATE_OR_DESTROY_SUFFIXES
    )


def _is_cast_or_type_check(unit: Unit) -> bool:
    """True for Cast / GenericCast / TypeCheck / IsValid nodes."""
    return any(unit["type"].endswith(suffix) for suffix in _CAST_SUFFIXES)


def _is_custom_event(unit: Unit) -> bool:
    """True for CustomEvent receiver nodes (not the Trigger variant)."""
    type_name = unit["type"]
    return type_name.endswith("CustomEvent") and not type_name.endswith(
        "TriggerCustomEvent"
    )


def _is_custom_event_trigger(unit: Unit) -> bool:
    """True for TriggerCustomEvent nodes."""
    return unit["type"].endswith("TriggerCustomEvent")


def _is_null_check(unit: Unit) -> bool:
    """True for NullCheck / IsNull nodes or InvokeMember IsNull calls."""
    if any(unit["type"].endswith(suffix) for suffix in _NULL_CHECK_SUFFIXES):
        return True
    member = _invoked_member(unit)
    if not member:
        return False
    return member.get("name") == "IsNull"


def _is_variable_access(unit: Unit) -> bool:
    """True for any Get/Set variable node."""
    return any(unit["type"].endswith(suffix) for suffix in _VARIABLE_ACCESS_SUFFIXES)


def _is_state(unit: Unit) -> bool:
    """True for any FSM state node."""
    return any(unit["type"].endswith(suffix) for suffix in _STATE_SUFFIXES)


def _is_event_root(unit: Unit) -> bool:
    """True for any lifecycle event root that triggers the graph."""
    return any(unit["type"].endswith(suffix) for suffix in _EVENT_ROOT_SUFFIXES)


def _is_send_message_call(unit: Unit) -> bool:
    """True for SendMessage / BroadcastMessage nodes or InvokeMember calls."""
    member = _invoked_member(unit)
    if member and member.get("name") in _SEND_MESSAGE_MEMBER_NAMES:
        return True
    return any(unit["type"].endswith(suffix) for suffix in _SEND_MESSAGE_SUFFIXES)


def _is_wait_for_seconds(unit: Unit) -> bool:
    """True for any yield/wait coroutine node."""
    return any(unit["type"].endswith(suffix) for suffix in _WAIT_FOR_SECONDS_SUFFIXES)


def _is_debug_break(unit: Unit) -> bool:
    """True for Debug.Break / BreakPoint nodes or InvokeMember calls."""
    member = _invoked_member(unit)
    if (
        member
        and member.get("name") == "Break"
        and member.get("targetType") == "UnityEngine.Debug"
    ):  # noqa: E501
        return True
    return any(unit["type"].endswith(suffix) for suffix in _DEBUG_BREAK_SUFFIXES)


def _is_playerprefs_set(unit: Unit) -> bool:
    """True for PlayerPrefs.Set* nodes or InvokeMember calls."""
    member = _invoked_member(unit)
    if member:
        member_name = member.get("name", "")
        if (
            isinstance(member_name, str)
            and member_name.startswith("Set")
            and member.get("targetType") == "UnityEngine.PlayerPrefs"
        ):
            return True
    return any(unit["type"].endswith(suffix) for suffix in _PLAYER_PREFS_SET_SUFFIXES)


def _has_inbound_edges(unit_guid: str, connections: List[Connection]) -> bool:
    """Whether `unit_guid` is the destination of any connection."""
    return any(conn["destination_unit"] == unit_guid for conn in connections)


def _has_outbound_edges(unit_guid: str, connections: List[Connection]) -> bool:
    """Whether `unit_guid` is the source of any connection."""
    return any(conn["source_unit"] == unit_guid for conn in connections)


def _downstream_units(unit_guid: str, connections: List[Connection]) -> List[str]:
    """Return GUIDs of every unit directly downstream of `unit_guid`."""
    return [
        conn["destination_unit"]
        for conn in connections
        if conn["source_unit"] == unit_guid
    ]


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
    """Build a single Issue with the same key shape every validate route expects."""
    return {
        "asset_path": graph.get("file_path", ""),
        "line": line,
        "severity": severity,
        "rule_id": rule_id,
        "category": category,
        "message": message,
        "snippet": "",
        "fix_suggestion": fix_suggestion,
        "is_auto_fixable": False,
    }


# ── VSP - Performance ──────────────────────────────────────────────


def detect_vsp001_log_in_update(graph: Graph) -> List[Issue]:
    """VSP001 - Debug.Log inside a graph that runs every frame."""
    if not graph.get("has_update_root"):
        return []
    out: List[Issue] = []
    for u in graph.get("units", []):
        if _is_debug_log_call(u):
            out.append(
                _emit(
                    graph,
                    rule_id="VSP001",
                    category="Performance",
                    severity="warning",
                    message="Debug.Log inside Update graph - console serialization happens every frame.",  # noqa: E501
                    fix_suggestion="Gate the Log behind a state change branch or move to a one-shot event.",  # noqa: E501
                )
            )
    return out


def detect_vsp002_unsafe_cast(graph: Graph) -> List[Issue]:
    """VSP002 - Cast node without a NullCheck immediately downstream.

    A failed Cast in Unity VS quietly emits a null on the converted
    pin, so the next node receives null without any flow-control hint.
    We BFS one hop from each Cast and flag it if none of the directly
    connected destinations is a NullCheck.
    """
    issues: List[Issue] = []
    connections = graph.get("connections", [])
    units_by_guid = {unit["guid"]: unit for unit in graph.get("units", [])}

    for unit in graph.get("units", []):
        if not _is_cast_or_type_check(unit):
            continue
        downstream_guids = _downstream_units(unit["guid"], connections)
        has_null_check_downstream = any(
            guid in units_by_guid and _is_null_check(units_by_guid[guid])
            for guid in downstream_guids
        )
        if has_null_check_downstream:
            continue
        issues.append(
            _emit(
                graph,
                rule_id="VSP002",
                category="Security",
                severity="warning",
                message="Cast node without null-check downstream - could pass null to dependent nodes.",  # noqa: E501
                fix_suggestion="Add a NullCheck node to handle failed casts.",
            )
        )
    return issues


# ── VSM - Maintainability ──────────────────────────────────────────


def detect_vsm001_graph_too_large(graph: Graph) -> List[Issue]:
    """VSM001 - > 50 nodes is hard to read and slow to load in the editor."""
    if graph.get("unit_count", 0) <= 50:
        return []
    return [
        _emit(
            graph,
            rule_id="VSM001",
            category="Maintainability",
            severity="warning",
            message=(
                f"Graph has {graph['unit_count']} nodes - past 50 the editor "
                "stops fitting in a single screen and load time grows."
            ),
            fix_suggestion="Split into sub-graphs or move pure data flow into C# helper methods.",  # noqa: E501
        )
    ]


def detect_vsm002_disconnected_node(graph: Graph) -> List[Issue]:
    """VSM002 - Node with no inbound and no outbound connections.

    Event roots are exempt: they're entry points and never have inbound
    edges by definition, so flagging them would be a constant false
    positive on graphs that only have OnStart/OnUpdate.
    """
    issues: List[Issue] = []
    connections = graph.get("connections", [])
    for unit in graph.get("units", []):
        if _is_event_root(unit):
            continue
        unit_guid = unit["guid"]
        if _has_inbound_edges(unit_guid, connections):
            continue
        if _has_outbound_edges(unit_guid, connections):
            continue
        issues.append(
            _emit(
                graph,
                rule_id="VSM002",
                category="Maintainability",
                severity="info",
                message="Node has no inbound or outbound connections - it is orphaned and has no effect.",  # noqa: E501
                fix_suggestion="Delete the node or connect it to the graph flow.",
            )
        )
    return issues


# ── VSB - Best practices ───────────────────────────────────────────


def detect_vsb001_orphan_custom_event(graph: Graph) -> List[Issue]:
    """VSB001 - CustomEvent declared but never triggered (or vice versa)."""
    has_def = any(_is_custom_event(u) for u in graph.get("units", []))
    has_trig = any(_is_custom_event_trigger(u) for u in graph.get("units", []))
    if has_def and not has_trig:
        return [
            _emit(
                graph,
                rule_id="VSB001",
                category="BestPractices",
                severity="info",
                message="CustomEvent declared but never triggered.",
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
                message="TriggerCustomEvent fired but no CustomEvent receiver in this graph.",  # noqa: E501
                fix_suggestion="Add a CustomEvent receiver or rename the trigger to an existing event.",  # noqa: E501
            )
        ]
    return []


def detect_vsb002_empty_graph(graph: Graph) -> List[Issue]:
    """VSB002 - 0-unit graph is dead weight."""
    if graph.get("unit_count", 0) != 0:
        return []
    return [
        _emit(
            graph,
            rule_id="VSB002",
            category="BestPractices",
            severity="info",
            message="Graph has zero nodes - it's a no-op kept around for nothing.",
            fix_suggestion="Delete the asset if it's no longer wired into a runner / state machine.",  # noqa: E501
        )
    ]


def detect_vsb003_deep_flow_chain(graph: Graph) -> List[Issue]:
    """VSB003 - long sequential chain in one path is hard to follow.

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
                "nodes - likely a single deep flow chain that reads like "
                "spaghetti."
            ),
            fix_suggestion="Refactor into sub-graphs or extract the deep portion into a C# behaviour.",  # noqa: E501
        )
    ]


# ── VSS - Security ─────────────────────────────────────────────────


# Field names that almost always identify a secret when seen alongside
# a non-empty string literal. We match on the *key* (not the value) so
# random base64 blobs in unrelated nodes don't trigger.
_SECRET_KEY_PATTERN = re.compile(
    r"(?:api[_-]?key|password|passwd|secret|token|bearer|auth|credential|private[_-]?key)",  # noqa: E501
    re.IGNORECASE,
)

# Below this length a literal is almost certainly a placeholder, not a
# real credential — skip to keep noise down.
_MIN_SECRET_LENGTH = 6


def _looks_like_secret_value(value: Any) -> bool:
    """A non-trivial string is the only thing we treat as a candidate secret."""
    return isinstance(value, str) and len(value.strip()) >= _MIN_SECRET_LENGTH


def _scan_default_values_for_secrets(default_values: Dict[str, Any]) -> List[str]:
    """Return the secret-like keys present in a unit's default_values.

    The walk is shallow on purpose: Visual Scripting nodes expose their
    user-set literals as direct top-level entries in `defaultValues`,
    e.g. ``{"apiKey": "sk-..."}``. Deeper traversal would mostly catch
    Unity bookkeeping fields (member info, type references) which never
    hold real secrets.
    """
    matched_keys: List[str] = []
    for key, value in default_values.items():
        if not _SECRET_KEY_PATTERN.search(str(key)):
            continue
        if _looks_like_secret_value(value):
            matched_keys.append(str(key))
    return matched_keys


def detect_vss001_hardcoded_secret(graph: Graph) -> List[Issue]:
    """VSS001 - String literal in a node's default_values whose field name
    looks like a credential (apiKey, password, token, ...).

    We match on the field name rather than the value so legitimate
    user-facing strings ("Press F to pay respects") never trigger; the
    minimum-length filter then drops obvious placeholders ("xxx").
    """
    issues: List[Issue] = []
    for unit in graph.get("units", []):
        default_values = unit.get("default_values", {})
        if not isinstance(default_values, dict):
            continue
        matched_keys = _scan_default_values_for_secrets(default_values)
        if not matched_keys:
            continue
        issues.append(
            _emit(
                graph,
                rule_id="VSS001",
                category="Security",
                severity="error",
                message=(
                    f"Node embeds a hardcoded credential in field(s): "
                    f"{', '.join(matched_keys)}. Anyone with the asset can read it."
                ),
                fix_suggestion=(
                    "Load secrets from a server endpoint at runtime, or from a "
                    "user-supplied config file outside the project; never commit "
                    "real credentials into graph assets."
                ),
            )
        )
    return issues


# ── VSP - Performance (Batch 2) ────────────────────────────────────


def detect_vsp003_getcomponent_in_update(graph: Graph) -> List[Issue]:
    """VSP003 - GetComponent call inside an Update graph."""
    if not graph.get("has_update_root"):
        return []
    out: List[Issue] = []
    for u in graph.get("units", []):
        if _is_getcomponent_call(u):
            out.append(
                _emit(
                    graph,
                    rule_id="VSP003",
                    category="Performance",
                    severity="warning",
                    message="GetComponent inside Update graph - component lookup every frame.",  # noqa: E501
                    fix_suggestion="Cache the component in OnStart and reuse from a graph variable.",  # noqa: E501
                )
            )
    return out


def detect_vsp004_find_in_update(graph: Graph) -> List[Issue]:
    """VSP004 - FindObjectOfType or scene search inside an Update graph."""
    if not graph.get("has_update_root"):
        return []
    out: List[Issue] = []
    for u in graph.get("units", []):
        if _is_find_call(u):
            out.append(
                _emit(
                    graph,
                    rule_id="VSP004",
                    category="Performance",
                    severity="error",
                    message="Find call inside Update graph - full scene scan every frame.",  # noqa: E501
                    fix_suggestion="Cache the reference once in OnStart, or use an exposed Object field.",  # noqa: E501
                )
            )
    return out


def detect_vsp005_instantiate_destroy_in_update(graph: Graph) -> List[Issue]:
    """VSP005 - Instantiate or Destroy inside an Update graph."""
    if not graph.get("has_update_root"):
        return []
    out: List[Issue] = []
    for u in graph.get("units", []):
        if _is_instantiate_or_destroy(u):
            out.append(
                _emit(
                    graph,
                    rule_id="VSP005",
                    category="Performance",
                    severity="error",
                    message="Instantiate or Destroy inside Update graph - memory alloc/free every frame.",  # noqa: E501
                    fix_suggestion="Move to OnStart or use object pooling.",
                )
            )
    return out


# ── VSM - Maintainability (Batch 2) ───────────────────────────────


def detect_vsm003_variable_overload(graph: Graph) -> List[Issue]:
    """VSM003 - More than 15 variable get/set nodes."""
    var_nodes = [u for u in graph.get("units", []) if _is_variable_access(u)]
    if len(var_nodes) <= 15:
        return []
    return [
        _emit(
            graph,
            rule_id="VSM003",
            category="Maintainability",
            severity="warning",
            message=f"Graph has {len(var_nodes)} variable read/write nodes - hard to trace data flow.",  # noqa: E501
            fix_suggestion="Group related variables into a data class or ScriptableObject.",  # noqa: E501
        )
    ]


def detect_vsm004_state_machine_too_large(graph: Graph) -> List[Issue]:
    """VSM004 - State machine with > 12 states."""
    if graph.get("graph_type") != "state":
        return []
    state_nodes = [u for u in graph.get("units", []) if _is_state(u)]
    if len(state_nodes) <= 12:
        return []
    return [
        _emit(
            graph,
            rule_id="VSM004",
            category="Maintainability",
            severity="warning",
            message=f"State machine has {len(state_nodes)} states - difficult to understand.",  # noqa: E501
            fix_suggestion="Split into hierarchical sub-state machines.",
        )
    ]


# ── VSB - Best Practices (Batch 2) ────────────────────────────────


def detect_vsb004_multiple_event_roots(graph: Graph) -> List[Issue]:
    """VSB004 - Graph has > 3 lifecycle event roots."""
    event_units = [u for u in graph.get("units", []) if _is_event_root(u)]
    if len(event_units) <= 3:
        return []
    return [
        _emit(
            graph,
            rule_id="VSB004",
            category="BestPractices",
            severity="info",
            message=f"Graph has {len(event_units)} event roots - mixed concerns in one graph.",  # noqa: E501
            fix_suggestion="Split into focused graphs on separate Script Machine components.",  # noqa: E501
        )
    ]


def detect_vsb005_getcomponent_no_null_check(graph: Graph) -> List[Issue]:
    """VSB005 - GetComponent present but no NullCheck in graph."""
    units = graph.get("units", [])
    has_getcomp = any(_is_getcomponent_call(u) for u in units)
    if not has_getcomp:
        return []
    has_null_check = any(_is_null_check(u) for u in units)
    if has_null_check:
        return []
    return [
        _emit(
            graph,
            rule_id="VSB005",
            category="BestPractices",
            severity="warning",
            message="GetComponent without NullCheck - could crash on missing component.",  # noqa: E501
            fix_suggestion="Add a NullCheck node after GetComponent.",
        )
    ]


def detect_vsb006_send_message(graph: Graph) -> List[Issue]:
    """VSB006 - SendMessage or BroadcastMessage call."""
    out: List[Issue] = []
    for u in graph.get("units", []):
        if _is_send_message_call(u):
            out.append(
                _emit(
                    graph,
                    rule_id="VSB006",
                    category="BestPractices",
                    severity="warning",
                    message="SendMessage uses string-based dispatch - slow and breaks refactoring.",  # noqa: E501
                    fix_suggestion="Use direct GetComponent calls or Custom Events instead.",  # noqa: E501
                )
            )
    return out


def detect_vsb007_wait_for_seconds_in_update(graph: Graph) -> List[Issue]:
    """VSB007 - WaitForSeconds inside an Update graph."""
    if not graph.get("has_update_root"):
        return []
    out: List[Issue] = []
    for u in graph.get("units", []):
        if _is_wait_for_seconds(u):
            out.append(
                _emit(
                    graph,
                    rule_id="VSB007",
                    category="Performance",
                    severity="warning",
                    message="WaitForSeconds inside Update graph - allocates yield object every frame.",  # noqa: E501
                    fix_suggestion="Cache the WaitForSeconds instance in a graph variable.",  # noqa: E501
                )
            )
    return out


def detect_vsb008_script_graph_no_root(graph: Graph) -> List[Issue]:
    """VSB008 - Script graph has nodes but no event root."""
    if graph.get("graph_type") != "script":
        return []
    if graph.get("unit_count", 0) == 0:
        return []
    has_root = any(_is_event_root(u) for u in graph.get("units", []))
    if has_root:
        return []
    return [
        _emit(
            graph,
            rule_id="VSB008",
            category="BestPractices",
            severity="warning",
            message="Script graph has nodes but no event root - graph never fires.",
            fix_suggestion="Add an event root node (OnStart, OnUpdate, etc) or delete the asset.",  # noqa: E501
        )
    ]


# ── VSS - Security (Batch 2) ──────────────────────────────────────


def detect_vss002_debug_break_in_graph(graph: Graph) -> List[Issue]:
    """VSS002 - Debug.Break node found."""
    out: List[Issue] = []
    for u in graph.get("units", []):
        if _is_debug_break(u):
            out.append(
                _emit(
                    graph,
                    rule_id="VSS002",
                    category="BestPractices",
                    severity="warning",
                    message="Debug.Break pauses the editor and will freeze production builds.",  # noqa: E501
                    fix_suggestion="Remove before shipping or gate with Editor-only flag.",  # noqa: E501
                )
            )
    return out


def detect_vss003_player_prefs_set(graph: Graph) -> List[Issue]:
    """VSS003 - PlayerPrefs.Set call found."""
    out: List[Issue] = []
    for u in graph.get("units", []):
        if _is_playerprefs_set(u):
            out.append(
                _emit(
                    graph,
                    rule_id="VSS003",
                    category="Security",
                    severity="info",
                    message="PlayerPrefs values are stored as plain text on disk.",
                    fix_suggestion="Use only for non-sensitive data (volume, resolution, etc).",  # noqa: E501
                )
            )
    return out
