"""Unity Visual Scripting (com.unity.visualscripting) asset parser.

Unity ships VS graphs as YAML `.asset` files when Asset Serialization
Mode is set to ForceText (the default). Each graph is a MonoBehaviour
that points at one of two known scripts:

  * Unity.VisualScripting.ScriptGraphAsset  — function-style graph
  * Unity.VisualScripting.StateGraphAsset   — FSM graph

The graph data is embedded as a JSON string in the YAML `_data._json`
field. This parser extracts and parses that JSON to obtain:

  * `name`: asset name (from file path)
  * `file_path`: full path to .asset file
  * `graph_type`: "script" | "state" | "unknown"
  * `units`: list of {guid, type, default_values, position}
  * `connections`: list of {source_unit, source_key, destination_unit, destination_key}
  * `variables`: dict of {name: {type, ...}}
  * `unit_count`: number of nodes
  * `has_update_root`: whether any event root is Update/OnUpdate/OnFixedUpdate/OnLateUpdate  # noqa: E501

Rules work with this structure to detect issues like: Log in Update,
unsafe casts, orphan events, disconnected nodes, large graphs, etc.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

_VS_MARKERS = (
    "Unity.VisualScripting.ScriptGraphAsset",
    "Unity.VisualScripting.StateGraphAsset",
    "Unity.VisualScripting.ScriptGraph",
    "Unity.VisualScripting.StateGraph",
)

# Real Unity VS assets reference the MonoScript by GUID (not by class name),
# so the literal class name "Unity.VisualScripting.ScriptGraphAsset" never
# appears in the YAML header. The reliable signal is the embedded `_json`
# field whose value always contains `Unity.VisualScripting.` type names
# (e.g. "$type":"Unity.VisualScripting.FlowGraph").
_VS_EMBEDDED_JSON_HINT = "_json:"
_VS_TYPE_PREFIX = "Unity.VisualScripting."

# Scan window: VS graphs can be hundreds of KB when the embedded JSON
# is large, but the `_json:` field always sits in the first few KB of
# YAML. 16 KB is generous enough to catch the marker without paying
# for full-file regex on every .asset Unity ships.
_VS_HEAD_SCAN_BYTES = 16384


def is_visual_scripting_asset(content: str) -> bool:
    """Fast pre-filter for Visual Scripting `.asset` files.

    Detects either (a) the legacy class-name markers (rare; only appear
    when an asset literally embeds the type name in a comment), or
    (b) the structural signal of a `_json:` YAML field whose contents
    reference any `Unity.VisualScripting.*` type — this is the reliable
    signal for real VS assets shipped by Unity.
    """
    head = content[:_VS_HEAD_SCAN_BYTES]
    if any(marker in head for marker in _VS_MARKERS):
        return True
    return _VS_EMBEDDED_JSON_HINT in head and _VS_TYPE_PREFIX in head


def detect_graph_type(content: str) -> str:
    """Identify script vs state graph from the embedded JSON or YAML hints.

    Inside the JSON blob, a script graph carries `Unity.VisualScripting.FlowGraph`
    (or `ScriptGraph`), a state graph carries `Unity.VisualScripting.StateGraph`.
    Falls back to the YAML markers when the JSON references are absent.
    """
    head = content[:_VS_HEAD_SCAN_BYTES]
    if "FlowGraph" in head or "ScriptGraph" in head:
        return "script"
    if "StateGraph" in head:
        return "state"
    return "unknown"


def _extract_json_string(content: str) -> Optional[str]:
    """Extract the JSON blob from the YAML `_data._json` field.

    The shipped YAML stores the entire graph as a single quoted JSON
    string on the `_json:` line. Single- and double-quoted forms are
    both valid YAML and both appear in Unity-shipped assets. The
    regex is greedy on the value side and stops at the first closing
    quote that matches the opening one — that's correct because Unity
    YAML-escapes embedded quotes inside the JSON, so the literal
    closing quote unambiguously ends the field.
    """
    match = re.search(
        r"_json:\s+(?P<quote>['\"])(?P<body>.*?)(?P=quote)\s*(?:\n|$)",
        content,
        flags=re.DOTALL,
    )
    if not match:
        return None
    return match.group("body")


# Keys that may hold the unit list inside the graph JSON. Real Unity
# assets typically use the nested form `graph.units`, while some
# stripped-down third-party exports flatten it to a top-level
# `elements` array. We try both before giving up.
_UNITS_CONTAINER_KEYS = ("elements", "units")
_CONNECTIONS_CONTAINER_KEYS = ("connections", "edges")
_VARIABLES_CONTAINER_KEYS = ("variables", "vars")


def _resolve_graph_root(graph_data: Any) -> Dict[str, Any]:
    """Walk known wrapper shapes to reach the dict that holds units.

    Unity ships VS graphs wrapped in `{"$content":{"graph":{...}}}`
    for newer schemas, and as a flat `{"elements":[...],...}` for
    simpler/older exports. This helper unwraps the first form so
    downstream code can read `units`/`connections` keys directly.
    """
    if not isinstance(graph_data, dict):
        return {}

    if "$content" in graph_data and isinstance(graph_data["$content"], dict):
        content_inner = graph_data["$content"]
        if "graph" in content_inner and isinstance(content_inner["graph"], dict):
            return content_inner["graph"]
        return content_inner

    if "graph" in graph_data and isinstance(graph_data["graph"], dict):
        return graph_data["graph"]

    return graph_data


def _pick_first_key(container: Dict[str, Any], candidate_keys: tuple) -> Any:
    """Return the first present value among candidate keys, or None."""
    for key in candidate_keys:
        if key in container:
            return container[key]
    return None


def parse_unity_graph(content: str, file_path: str) -> Optional[Dict]:
    """Parse a Visual Scripting `.asset` YAML into a structured dict.

    Returns None when the file isn't a Visual Scripting asset. On success:

        {
          "name":            "MyGraph",
          "file_path":       "Assets/Graphs/MyGraph.asset",
          "graph_type":      "script" | "state" | "unknown",
          "units":           [
            {
              "guid":          "abc123",
              "type":          "Unity.VisualScripting.Update",
              "position":      [x, y],
              "default_values": {...},
            }, ...
          ],
          "connections":     [
            {
              "source_unit":      "guid1",
              "source_key":       "exit",
              "destination_unit": "guid2",
              "destination_key":  "enter",
            }, ...
          ],
          "variables":       {"varName": {"type": "string"}, ...},
          "unit_count":      int,
          "has_update_root": bool,
        }
    """
    if not is_visual_scripting_asset(content):
        return None

    embedded_json_text = _extract_json_string(content)
    if not embedded_json_text:
        return None

    try:
        graph_data = json.loads(embedded_json_text)
    except (json.JSONDecodeError, ValueError):
        return None

    graph_root = _resolve_graph_root(graph_data)

    units: List[Dict[str, Any]] = []
    connections: List[Dict[str, str]] = []
    variables: Dict[str, Dict[str, Any]] = {}
    has_update_root = False

    # Real Unity VS assets mix nodes and connections in the same `elements`
    # array. Connections carry a $type ending in "Connection"; nodes carry
    # a numeric `$id` used as a cross-reference target. We split them here
    # and build an id→guid map so we can resolve {"$ref": "13"} pointers.
    raw_elements = _pick_first_key(graph_root, _UNITS_CONTAINER_KEYS) or []
    id_to_guid: Dict[str, str] = {}
    raw_connection_elements: List[Dict[str, Any]] = []
    raw_node_elements: List[Dict[str, Any]] = []

    for elem in raw_elements:
        if not isinstance(elem, dict):
            continue
        elem_type = elem.get("$type", "")
        if "Connection" in elem_type:
            raw_connection_elements.append(elem)
        else:
            raw_node_elements.append(elem)
            elem_id = elem.get("$id")
            elem_guid = elem.get("guid", "")
            if elem_id is not None and elem_guid:
                id_to_guid[str(elem_id)] = elem_guid

    for raw_unit in raw_node_elements:
        unit_type = raw_unit.get("$type", "")
        unit_guid = raw_unit.get("guid", "")

        if not unit_type or not unit_guid:
            continue

        unit_record: Dict[str, Any] = {
            "guid": unit_guid,
            "type": unit_type,
            "position": raw_unit.get("position", [0, 0]),
            "default_values": raw_unit.get("defaultValues", {}),
            # Real Unity VS assets store `member` as a top-level field on
            # InvokeMember nodes, not nested inside defaultValues.
            "member": raw_unit.get("member"),
        }
        units.append(unit_record)

        if _is_update_event_type(unit_type):
            has_update_root = True

    # Connections may come from a dedicated array (synthetic/test format)
    # or from the mixed elements array (real Unity format).
    raw_connections_dedicated = (
        _pick_first_key(graph_root, _CONNECTIONS_CONTAINER_KEYS) or []
    )

    def _resolve_unit_ref(ref: Any) -> str:
        """Resolve a raw sourceUnit/destinationUnit to a guid string.

        Real Unity VS assets use {"$ref": "<id>"} cross-references; the
        synthetic test format uses plain guid strings directly.
        """
        if isinstance(ref, dict):
            return id_to_guid.get(str(ref.get("$ref", "")), "")
        return str(ref) if ref else ""

    all_raw_connections = list(raw_connections_dedicated) + raw_connection_elements
    for raw_connection in all_raw_connections:
        if not isinstance(raw_connection, dict):
            continue
        connections.append(
            {
                "source_unit": _resolve_unit_ref(raw_connection.get("sourceUnit", "")),
                "source_key": raw_connection.get("sourceKey", ""),
                "destination_unit": _resolve_unit_ref(
                    raw_connection.get("destinationUnit", "")
                ),
                "destination_key": raw_connection.get("destinationKey", ""),
            }
        )

    raw_variables = _pick_first_key(graph_root, _VARIABLES_CONTAINER_KEYS) or {}
    if isinstance(raw_variables, dict):
        for variable_name, variable_info in raw_variables.items():
            if isinstance(variable_info, dict):
                variables[variable_name] = variable_info

    return {
        "name": Path(file_path).stem,
        "file_path": file_path,
        "graph_type": detect_graph_type(content),
        "units": units,
        "connections": connections,
        "variables": variables,
        "unit_count": len(units),
        "has_update_root": has_update_root,
    }


def _is_update_event_type(type_name: str) -> bool:
    """Check if a unit type is an event that fires per-frame."""
    return any(
        type_name.endswith(s)
        for s in (
            "OnUpdate",
            "OnFixedUpdate",
            "OnLateUpdate",
            "Update",
            "FixedUpdate",
            "LateUpdate",
        )
    )
