"""Unity Visual Scripting (com.unity.visualscripting) asset parser.

Unity ships VS graphs as YAML `.asset` files when Asset Serialization
Mode is set to ForceText (the default). Each graph is a MonoBehaviour
that points at one of two known scripts:

  * Unity.VisualScripting.ScriptGraphAsset  — function-style graph
  * Unity.VisualScripting.StateGraphAsset   — FSM graph

Inside the YAML there's a deeply nested `data.SerializedKeys` array
where every node ("unit") is serialised with a `_type` (or `$type`)
field naming its concrete Unity.VisualScripting.* class.

This parser is intentionally defensive — Visual Scripting's YAML can
get gnarly fast (RIDs, type aliases, nested generics) and Unity has
shipped two slightly different serialisation shapes. We only extract:

  * `is_visual_scripting`: whether this asset is a VS graph at all
  * `graph_type`: "script" | "state"
  * `units`: list of {type, line} — every node declaration
  * Future: connections, variables, event hooks

That's enough to power rules like "Log node in Update graph",
"orphan custom event", "graph too large", etc. without an AST.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

# Heuristics: distinctive strings Visual Scripting writes into every
# graph asset. Any one match is enough; checking three keeps us
# resilient to format drift between Unity 2021 and 2023.
_VS_MARKERS = (
    "Unity.VisualScripting.ScriptGraphAsset",
    "Unity.VisualScripting.StateGraphAsset",
    "Unity.VisualScripting.ScriptGraph",
    "Unity.VisualScripting.StateGraph",
)

# Top-level unit type lines look like:
#   _type: "Unity.VisualScripting.OnUpdate, ..."
#   $type: Unity.VisualScripting.Log, Assembly-CSharp
# Trailing assembly part is everything after the first comma.
_UNIT_TYPE_RE = re.compile(
    # YAML array entries are written `    - _type: …`, plain fields as
    # `    _type: …`. The optional `- ` covers both shapes.
    r"^\s+(?:-\s+)?(?:_type|\$type):\s*\"?(?P<type>Unity\.VisualScripting\.[\w<>.]+)",
    re.MULTILINE,
)


def is_visual_scripting_asset(content: str) -> bool:
    """Fast pre-filter — peek at the first 4 KB for the VS marker.

    Visual Scripting assets always declare the script reference near
    the top of the file (after the YAML header). 4 KB covers the
    biggest header we've observed in the wild without paying for
    the full file regex match on every .asset Unity ships.
    """
    head = content[:4096]
    return any(marker in head for marker in _VS_MARKERS)


def detect_graph_type(content: str) -> str:
    if "ScriptGraphAsset" in content[:4096] or "ScriptGraph" in content[:4096]:
        return "script"
    if "StateGraphAsset" in content[:4096] or "StateGraph" in content[:4096]:
        return "state"
    return "unknown"


def parse_unity_graph(content: str, file_path: str) -> Optional[Dict]:
    """Parse a Visual Scripting `.asset` YAML into a structured dict.

    Returns None when the file isn't a Visual Scripting asset so the
    caller can skip it cheaply. On a VS asset returns:

        {
          "name":            "MyGraph",
          "file_path":       "Assets/Graphs/MyGraph.asset",
          "graph_type":      "script" | "state" | "unknown",
          "units":           [{"type": "Unity.VisualScripting.Log", "line": 42}, ...],
          "unit_count":      int,
          "connections":     [],  # Phase A placeholder
          "variables":       [],  # Phase A placeholder
          "has_update_root": bool,
        }
    """
    if not is_visual_scripting_asset(content):
        return None

    units: List[Dict] = []
    for m in _UNIT_TYPE_RE.finditer(content):
        # `_type` lines are 1-based from the start of the string.
        line_no = content.count("\n", 0, m.start()) + 1
        units.append({"type": m.group("type"), "line": line_no})

    # Heuristic: any OnUpdate/OnFixedUpdate/Update root means the
    # graph is invoked per-frame. The rules will use this to gate
    # performance-sensitive node checks (eg "Log inside Update").
    has_update_root = any(
        u["type"].endswith(("OnUpdate", "OnFixedUpdate", "OnLateUpdate", "Update"))
        for u in units
    )

    return {
        "name": Path(file_path).stem,
        "file_path": file_path,
        "graph_type": detect_graph_type(content),
        "units": units,
        "unit_count": len(units),
        "connections": [],
        "variables": [],
        "has_update_root": has_update_root,
    }
