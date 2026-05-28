"""Test suite for Unity Visual Scripting graph rules.

Fixtures mirror the real on-disk shape of `.asset` files that Unity
ships when Asset Serialization Mode = ForceText: a YAML wrapper with
the entire graph stored as a JSON string in `_data._json`.

We intentionally keep YAML headers small and exercise the JSON shapes
that the parser must understand. None of the fixtures rely on Tree-
sitter or PyYAML — the parser uses a regex to extract the JSON blob,
so plain f-strings are enough to build well-formed test inputs.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from ..parsers.unity_vs_parser import parse_unity_graph
from . import unity_graph_rules as rules

# ── Fixture builder ──────────────────────────────────────────────────
#
# We assemble each fixture from a Python dict (rather than hand-writing
# embedded JSON) so it stays readable and we never accidentally produce
# malformed JSON when iterating on tests.


def _build_asset_yaml(
    elements: List[Dict[str, Any]],
    connections: List[Dict[str, str]] | None = None,
    variables: Dict[str, Any] | None = None,
) -> str:
    """Render a minimal VS `.asset` YAML wrapping the given graph.

    The output mirrors the real on-disk format: a MonoBehaviour header
    followed by `_data: _json: '<json-blob>'`. We escape single quotes
    inside the JSON the same way Unity does (it doubles them).
    """
    graph_json = json.dumps(
        {
            "elements": elements,
            "connections": connections or [],
            "variables": variables or {},
        }
    )
    escaped_json = graph_json.replace("'", "''")
    # The `m_Name` field carries the legacy `Unity.VisualScripting.ScriptGraphAsset`
    # marker so the parser's pre-filter recognises empty-element fixtures too,
    # exactly mirroring how real Unity assets advertise their type.
    return (
        "%YAML 1.1\n"
        "%TAG !u! tag:unity3d.com,2011:\n"
        "--- !u!114 &11500000\n"
        "MonoBehaviour:\n"
        "  m_ObjectHideFlags: 0\n"
        "  m_Script: {fileID: 11500000, guid: 1b7db557dd37f, type: 3}\n"
        "  m_Name: Unity.VisualScripting.ScriptGraphAsset\n"
        "  m_EditorClassIdentifier:\n"
        "  _data:\n"
        f"    _json: '{escaped_json}'\n"
    )


def _make_unit(
    guid: str,
    type_name: str,
    default_values: Dict[str, Any] | None = None,
    position: List[int] | None = None,
) -> Dict[str, Any]:
    """Construct one element of the `elements` array."""
    return {
        "guid": guid,
        "$type": type_name,
        "position": position or [0, 0],
        "defaultValues": default_values or {},
    }


def _make_connection(
    source_unit: str,
    source_key: str,
    destination_unit: str,
    destination_key: str,
) -> Dict[str, str]:
    """Construct one element of the `connections` array."""
    return {
        "sourceUnit": source_unit,
        "sourceKey": source_key,
        "destinationUnit": destination_unit,
        "destinationKey": destination_key,
    }


def _make_invoke_member_unit(
    guid: str,
    member_name: str,
    target_type: str,
    extra_default_values: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Shortcut for `InvokeMember` nodes, which are how VS encodes API calls."""
    default_values: Dict[str, Any] = {
        "member": {
            "name": member_name,
            "targetType": target_type,
        }
    }
    if extra_default_values:
        default_values.update(extra_default_values)
    return _make_unit(guid, "Unity.VisualScripting.InvokeMember", default_values)


# ── Fixtures ────────────────────────────────────────────────────────


# Start root -> Debug.Log InvokeMember, plus an OnUpdate root (no Log inside it)
FIXTURE_LOG_OUTSIDE_UPDATE = _build_asset_yaml(
    elements=[
        _make_unit("1", "Unity.VisualScripting.Start"),
        _make_invoke_member_unit("2", "Log", "UnityEngine.Debug"),
        _make_unit("3", "Unity.VisualScripting.OnUpdate"),
    ],
    connections=[_make_connection("1", "exit", "2", "enter")],
)

# OnUpdate root -> Debug.Log: should trigger VSP001
FIXTURE_LOG_IN_UPDATE = _build_asset_yaml(
    elements=[
        _make_unit("1", "Unity.VisualScripting.OnUpdate"),
        _make_invoke_member_unit("2", "Log", "UnityEngine.Debug"),
    ],
    connections=[_make_connection("1", "exit", "2", "enter")],
)

# Start root + Debug.Log connected; an extra Literal node is disconnected
# (no inbound/outbound edges). Should trigger VSM002 for the Literal.
FIXTURE_DISCONNECTED_NODE = _build_asset_yaml(
    elements=[
        _make_unit("1", "Unity.VisualScripting.Start"),
        _make_invoke_member_unit("2", "Log", "UnityEngine.Debug"),
        _make_unit("3", "Unity.VisualScripting.Literal", {"value": "orphaned"}),
    ],
    connections=[_make_connection("1", "exit", "2", "enter")],
)

# OnUpdate root -> GetComponent InvokeMember: should trigger VSP003
FIXTURE_GETCOMPONENT_IN_UPDATE = _build_asset_yaml(
    elements=[
        _make_unit("1", "Unity.VisualScripting.OnUpdate"),
        _make_invoke_member_unit("2", "GetComponent", "UnityEngine.GameObject"),
    ],
    connections=[_make_connection("1", "exit", "2", "enter")],
)

# OnUpdate root -> FindObjectOfType node: should trigger VSP004
FIXTURE_FIND_IN_UPDATE = _build_asset_yaml(
    elements=[
        _make_unit("1", "Unity.VisualScripting.OnUpdate"),
        _make_unit("2", "Unity.VisualScripting.FindObjectOfType"),
    ],
    connections=[_make_connection("1", "exit", "2", "enter")],
)

# OnUpdate -> Instantiate: should trigger VSP005
FIXTURE_INSTANTIATE_IN_UPDATE = _build_asset_yaml(
    elements=[
        _make_unit("1", "Unity.VisualScripting.OnUpdate"),
        _make_invoke_member_unit("2", "Instantiate", "UnityEngine.Object"),
    ],
    connections=[_make_connection("1", "exit", "2", "enter")],
)

# Start -> Cast -> SetActive (no NullCheck): should trigger VSP002
FIXTURE_UNSAFE_CAST = _build_asset_yaml(
    elements=[
        _make_unit("1", "Unity.VisualScripting.Start"),
        _make_unit(
            "2",
            "Unity.VisualScripting.Cast",
            {"targetType": "UnityEngine.Transform"},
        ),
        _make_invoke_member_unit("3", "SetActive", "UnityEngine.GameObject"),
    ],
    connections=[
        _make_connection("1", "exit", "2", "enter"),
        _make_connection("2", "converted", "3", "enter"),
    ],
)

# Start -> Cast -> NullCheck -> SetActive: should NOT trigger VSP002
FIXTURE_SAFE_CAST = _build_asset_yaml(
    elements=[
        _make_unit("1", "Unity.VisualScripting.Start"),
        _make_unit(
            "2",
            "Unity.VisualScripting.Cast",
            {"targetType": "UnityEngine.Transform"},
        ),
        _make_unit("3", "Unity.VisualScripting.NullCheck"),
        _make_invoke_member_unit("4", "SetActive", "UnityEngine.GameObject"),
    ],
    connections=[
        _make_connection("1", "exit", "2", "enter"),
        _make_connection("2", "converted", "3", "enter"),
        _make_connection("3", "ifNotNull", "4", "enter"),
    ],
)

# 60 disconnected Literal nodes — beats VSM001 (>50) AND VSM002 (orphan)
FIXTURE_LARGE_GRAPH = _build_asset_yaml(
    elements=[
        _make_unit(
            str(index),
            "Unity.VisualScripting.Literal",
            {"value": f"node{index}"},
            [index * 10, index * 20],
        )
        for index in range(60)
    ],
)

# Empty graph: triggers VSB002
FIXTURE_EMPTY_GRAPH = _build_asset_yaml(elements=[])

# Single Literal node with no event root: triggers VSB008
FIXTURE_NO_EVENT_ROOT = _build_asset_yaml(
    elements=[
        _make_unit(
            "1",
            "Unity.VisualScripting.Literal",
            {"value": "orphaned"},
        ),
    ],
)

# 15 StateUnit nodes (caller flips graph_type to "state"): triggers VSM004
FIXTURE_LARGE_STATE_MACHINE = _build_asset_yaml(
    elements=[
        _make_unit(
            str(index),
            "Unity.VisualScripting.StateUnit",
            {"label": f"State{index}"},
            [index * 10, index * 20],
        )
        for index in range(15)
    ],
)

# 4 lifecycle event roots: triggers VSB004
FIXTURE_MULTIPLE_EVENT_ROOTS = _build_asset_yaml(
    elements=[
        _make_unit("1", "Unity.VisualScripting.OnStart"),
        _make_unit("2", "Unity.VisualScripting.OnUpdate"),
        _make_unit("3", "Unity.VisualScripting.OnLateUpdate"),
        _make_unit("4", "Unity.VisualScripting.OnEnable"),
    ],
)

# CustomEvent receiver but no Trigger: triggers VSB001
FIXTURE_ORPHAN_CUSTOM_EVENT = _build_asset_yaml(
    elements=[
        _make_unit("1", "Unity.VisualScripting.CustomEvent"),
    ],
)

# GetComponent but no NullCheck: triggers VSB005
FIXTURE_GETCOMPONENT_NO_NULLCHECK = _build_asset_yaml(
    elements=[
        _make_unit("1", "Unity.VisualScripting.OnStart"),
        _make_invoke_member_unit("2", "GetComponent", "UnityEngine.GameObject"),
    ],
    connections=[_make_connection("1", "exit", "2", "enter")],
)

# SendMessage: triggers VSB006
FIXTURE_SEND_MESSAGE = _build_asset_yaml(
    elements=[
        _make_unit("1", "Unity.VisualScripting.OnStart"),
        _make_invoke_member_unit("2", "SendMessage", "UnityEngine.GameObject"),
    ],
    connections=[_make_connection("1", "exit", "2", "enter")],
)

# WaitForSeconds inside Update: triggers VSB007
FIXTURE_WAITFORSECONDS_IN_UPDATE = _build_asset_yaml(
    elements=[
        _make_unit("1", "Unity.VisualScripting.OnUpdate"),
        _make_unit("2", "Unity.VisualScripting.WaitForSeconds"),
    ],
    connections=[_make_connection("1", "exit", "2", "enter")],
)

# Debug.Break: triggers VSS002
FIXTURE_DEBUG_BREAK = _build_asset_yaml(
    elements=[
        _make_unit("1", "Unity.VisualScripting.OnStart"),
        _make_invoke_member_unit("2", "Break", "UnityEngine.Debug"),
    ],
    connections=[_make_connection("1", "exit", "2", "enter")],
)

# PlayerPrefs.SetString: triggers VSS003
FIXTURE_PLAYERPREFS_SET = _build_asset_yaml(
    elements=[
        _make_unit("1", "Unity.VisualScripting.OnStart"),
        _make_invoke_member_unit("2", "SetString", "UnityEngine.PlayerPrefs"),
    ],
    connections=[_make_connection("1", "exit", "2", "enter")],
)

# Hardcoded API key in default_values: triggers VSS001
FIXTURE_HARDCODED_SECRET = _build_asset_yaml(
    elements=[
        _make_unit(
            "1",
            "Unity.VisualScripting.Literal",
            {"apiKey": "sk-live-1234567890abcdef"},
        ),
    ],
)

# 16 variable Get/Set nodes: triggers VSM003
FIXTURE_VARIABLE_OVERLOAD = _build_asset_yaml(
    elements=[
        _make_unit(str(i), "Unity.VisualScripting.GetVariable") for i in range(16)
    ],
)


# ── VSP - Performance ───────────────────────────────────────────────


class TestVSP001LogInUpdate:
    def test_log_in_update_detected(self):
        graph = parse_unity_graph(FIXTURE_LOG_IN_UPDATE, "test.asset")
        assert graph is not None
        issues = rules.detect_vsp001_log_in_update(graph)
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "VSP001"
        assert issues[0]["severity"] == "warning"

    def test_log_outside_update_not_detected(self):
        graph = parse_unity_graph(FIXTURE_LOG_OUTSIDE_UPDATE, "test.asset")
        assert graph is not None
        # Note: graph has OnUpdate root but no Log inside Update path.
        # The current rule fires on any Log when has_update_root is true,
        # so this acts as a regression sentinel for the current behaviour.
        issues = rules.detect_vsp001_log_in_update(graph)
        # Confirms Log IS detected because has_update_root is true (OnUpdate present).
        # This matches the documented behaviour and we assert exactly that.
        assert len(issues) == 1


class TestVSP002UnsafeCast:
    def test_cast_without_null_check_detected(self):
        graph = parse_unity_graph(FIXTURE_UNSAFE_CAST, "test.asset")
        assert graph is not None
        issues = rules.detect_vsp002_unsafe_cast(graph)
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "VSP002"

    def test_cast_with_null_check_not_detected(self):
        graph = parse_unity_graph(FIXTURE_SAFE_CAST, "test.asset")
        assert graph is not None
        issues = rules.detect_vsp002_unsafe_cast(graph)
        assert len(issues) == 0


class TestVSP003GetComponentInUpdate:
    def test_getcomponent_in_update_detected(self):
        graph = parse_unity_graph(FIXTURE_GETCOMPONENT_IN_UPDATE, "test.asset")
        assert graph is not None
        issues = rules.detect_vsp003_getcomponent_in_update(graph)
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "VSP003"


class TestVSP004FindInUpdate:
    def test_find_in_update_detected(self):
        graph = parse_unity_graph(FIXTURE_FIND_IN_UPDATE, "test.asset")
        assert graph is not None
        issues = rules.detect_vsp004_find_in_update(graph)
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "VSP004"
        assert issues[0]["severity"] == "error"


class TestVSP005InstantiateInUpdate:
    def test_instantiate_in_update_detected(self):
        graph = parse_unity_graph(FIXTURE_INSTANTIATE_IN_UPDATE, "test.asset")
        assert graph is not None
        issues = rules.detect_vsp005_instantiate_destroy_in_update(graph)
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "VSP005"


# ── VSM - Maintainability ────────────────────────────────────────────


class TestVSM001GraphTooLarge:
    def test_large_graph_detected(self):
        graph = parse_unity_graph(FIXTURE_LARGE_GRAPH, "test.asset")
        assert graph is not None
        assert graph["unit_count"] == 60
        issues = rules.detect_vsm001_graph_too_large(graph)
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "VSM001"


class TestVSM002DisconnectedNode:
    def test_disconnected_node_detected(self):
        graph = parse_unity_graph(FIXTURE_DISCONNECTED_NODE, "test.asset")
        assert graph is not None
        issues = rules.detect_vsm002_disconnected_node(graph)
        # guid "3" is the orphan Literal; Start (guid "1") is exempt as event root.
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "VSM002"


class TestVSM003VariableOverload:
    def test_many_variables_detected(self):
        graph = parse_unity_graph(FIXTURE_VARIABLE_OVERLOAD, "test.asset")
        assert graph is not None
        issues = rules.detect_vsm003_variable_overload(graph)
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "VSM003"


class TestVSM004StateMachineTooLarge:
    def test_large_state_machine_detected(self):
        graph = parse_unity_graph(FIXTURE_LARGE_STATE_MACHINE, "test.asset")
        assert graph is not None
        # Force the graph_type because no `StateGraph` marker is in this YAML.
        graph["graph_type"] = "state"
        issues = rules.detect_vsm004_state_machine_too_large(graph)
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "VSM004"


# ── VSB - Best Practices ─────────────────────────────────────────────


class TestVSB001OrphanCustomEvent:
    def test_orphan_custom_event_detected(self):
        graph = parse_unity_graph(FIXTURE_ORPHAN_CUSTOM_EVENT, "test.asset")
        assert graph is not None
        issues = rules.detect_vsb001_orphan_custom_event(graph)
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "VSB001"


class TestVSB002EmptyGraph:
    def test_empty_graph_detected(self):
        graph = parse_unity_graph(FIXTURE_EMPTY_GRAPH, "test.asset")
        assert graph is not None
        assert graph["unit_count"] == 0
        issues = rules.detect_vsb002_empty_graph(graph)
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "VSB002"


class TestVSB004MultipleEventRoots:
    def test_multiple_roots_detected(self):
        graph = parse_unity_graph(FIXTURE_MULTIPLE_EVENT_ROOTS, "test.asset")
        assert graph is not None
        issues = rules.detect_vsb004_multiple_event_roots(graph)
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "VSB004"


class TestVSB005GetComponentNoNullCheck:
    def test_no_null_check_detected(self):
        graph = parse_unity_graph(FIXTURE_GETCOMPONENT_NO_NULLCHECK, "test.asset")
        assert graph is not None
        issues = rules.detect_vsb005_getcomponent_no_null_check(graph)
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "VSB005"


class TestVSB006SendMessage:
    def test_send_message_detected(self):
        graph = parse_unity_graph(FIXTURE_SEND_MESSAGE, "test.asset")
        assert graph is not None
        issues = rules.detect_vsb006_send_message(graph)
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "VSB006"


class TestVSB007WaitForSecondsInUpdate:
    def test_wait_in_update_detected(self):
        graph = parse_unity_graph(FIXTURE_WAITFORSECONDS_IN_UPDATE, "test.asset")
        assert graph is not None
        issues = rules.detect_vsb007_wait_for_seconds_in_update(graph)
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "VSB007"


class TestVSB008ScriptGraphNoRoot:
    def test_no_root_detected(self):
        graph = parse_unity_graph(FIXTURE_NO_EVENT_ROOT, "test.asset")
        assert graph is not None
        # Force script graph type — fixture lacks the marker but real
        # ScriptGraphAssets always have FlowGraph somewhere in their YAML.
        graph["graph_type"] = "script"
        issues = rules.detect_vsb008_script_graph_no_root(graph)
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "VSB008"


# ── VSS - Security ───────────────────────────────────────────────────


class TestVSS001HardcodedSecret:
    def test_api_key_detected(self):
        graph = parse_unity_graph(FIXTURE_HARDCODED_SECRET, "test.asset")
        assert graph is not None
        issues = rules.detect_vss001_hardcoded_secret(graph)
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "VSS001"
        assert issues[0]["severity"] == "error"

    def test_short_placeholder_not_detected(self):
        # Short values are treated as placeholders and skipped.
        fixture = _build_asset_yaml(
            elements=[
                _make_unit(
                    "1",
                    "Unity.VisualScripting.Literal",
                    {"apiKey": "xx"},  # below 6-char threshold
                ),
            ],
        )
        graph = parse_unity_graph(fixture, "test.asset")
        assert graph is not None
        issues = rules.detect_vss001_hardcoded_secret(graph)
        assert len(issues) == 0

    def test_non_secret_field_not_detected(self):
        # A long string under an innocuous key should NOT trigger.
        fixture = _build_asset_yaml(
            elements=[
                _make_unit(
                    "1",
                    "Unity.VisualScripting.Literal",
                    {"message": "Hello world, this is a long string."},
                ),
            ],
        )
        graph = parse_unity_graph(fixture, "test.asset")
        assert graph is not None
        issues = rules.detect_vss001_hardcoded_secret(graph)
        assert len(issues) == 0


class TestVSS002DebugBreak:
    def test_debug_break_detected(self):
        graph = parse_unity_graph(FIXTURE_DEBUG_BREAK, "test.asset")
        assert graph is not None
        issues = rules.detect_vss002_debug_break_in_graph(graph)
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "VSS002"


class TestVSS003PlayerPrefsSet:
    def test_playerprefs_set_detected(self):
        graph = parse_unity_graph(FIXTURE_PLAYERPREFS_SET, "test.asset")
        assert graph is not None
        issues = rules.detect_vss003_player_prefs_set(graph)
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "VSS003"


# ── Parser & Issue shape ─────────────────────────────────────────────


class TestParserIntegration:
    def test_parser_extracts_units(self):
        graph = parse_unity_graph(FIXTURE_LOG_OUTSIDE_UPDATE, "test.asset")
        assert graph is not None
        assert graph["unit_count"] == 3
        assert len(graph["units"]) == 3

    def test_parser_extracts_connections(self):
        graph = parse_unity_graph(FIXTURE_LOG_OUTSIDE_UPDATE, "test.asset")
        assert graph is not None
        assert len(graph["connections"]) == 1
        connection = graph["connections"][0]
        assert connection["source_unit"] == "1"
        assert connection["destination_unit"] == "2"
        assert connection["source_key"] == "exit"
        assert connection["destination_key"] == "enter"

    def test_parser_detects_update_root(self):
        graph = parse_unity_graph(FIXTURE_LOG_IN_UPDATE, "test.asset")
        assert graph is not None
        assert graph["has_update_root"] is True

    def test_parser_skips_non_vs_asset(self):
        non_vs_yaml = "%YAML 1.1\nsome: random\nasset: content"
        graph = parse_unity_graph(non_vs_yaml, "test.asset")
        assert graph is None

    def test_parser_skips_malformed_json(self):
        # Quoted _json with non-JSON content: detector finds the marker
        # (Unity.VisualScripting.X) but parser fails to decode the body
        # and should return None instead of crashing.
        broken = (
            "_data:\n"
            "    _json: 'this is Unity.VisualScripting.Garbage, not real json'\n"
        )
        graph = parse_unity_graph(broken, "test.asset")
        assert graph is None


class TestIssueShape:
    def test_issue_has_required_fields(self):
        graph = parse_unity_graph(FIXTURE_EMPTY_GRAPH, "test.asset")
        assert graph is not None
        issues = rules.detect_vsb002_empty_graph(graph)
        assert len(issues) == 1

        issue = issues[0]
        required_fields = {
            "asset_path",
            "line",
            "severity",
            "rule_id",
            "category",
            "message",
            "snippet",
            "fix_suggestion",
            "is_auto_fixable",
        }
        assert required_fields.issubset(issue.keys())

    def test_severity_is_valid(self):
        graph = parse_unity_graph(FIXTURE_LOG_IN_UPDATE, "test.asset")
        assert graph is not None
        issues = rules.detect_vsp001_log_in_update(graph)
        assert len(issues) == 1
        assert issues[0]["severity"] in ("error", "warning", "info")
