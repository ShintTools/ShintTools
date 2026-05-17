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
        "snippet": "",        # VS has no source snippet — kept for shape parity
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
            out.append(_emit(
                graph,
                rule_id="VSP001", category="Performance", severity="warning",
                message=(
                    f"{u['type'].rsplit('.', 1)[-1]} node sits inside an "
                    "Update graph — the console serialises a string every "
                    "frame which kills editor and runtime perf."
                ),
                fix_suggestion="Gate the Log behind a branch that fires only when state changes, or move it to a one-shot event.",
                line=u.get("line", 0),
            ))
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
            out.append(_emit(
                graph,
                rule_id="VSP002", category="Security", severity="warning",
                message=(
                    "Cast node without explicit null-check downstream — "
                    "Visual Scripting won't stop execution on a failed cast."
                ),
                fix_suggestion="Wire the cast's failure pin to a Null Check before using the result.",
                line=u.get("line", 0),
            ))
    return out


# ── VSM — Maintainability ──────────────────────────────────────────


def detect_vsm001_graph_too_large(graph: Graph) -> List[Issue]:
    """VSM001 — > 50 nodes is hard to read and slow to load in the editor."""
    if graph.get("unit_count", 0) <= 50:
        return []
    return [_emit(
        graph,
        rule_id="VSM001", category="Maintainability", severity="warning",
        message=(
            f"Graph has {graph['unit_count']} nodes — past 50 the editor "
            "stops fitting in a single screen and load time grows."
        ),
        fix_suggestion="Split into sub-graphs or move pure data flow into C# helper methods.",
    )]


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
    has_trig = any(u["type"].endswith("TriggerCustomEvent") for u in graph.get("units", []))
    if has_def and not has_trig:
        return [_emit(
            graph,
            rule_id="VSB001", category="BestPractices", severity="info",
            message="CustomEvent declared but never triggered from any node.",
            fix_suggestion="Either trigger the event from somewhere or remove the declaration.",
        )]
    if has_trig and not has_def:
        return [_emit(
            graph,
            rule_id="VSB001", category="BestPractices", severity="warning",
            message="TriggerCustomEvent fired against an event with no matching CustomEvent receiver in this graph.",
            fix_suggestion="Add a CustomEvent receiver or rename the trigger to an existing event.",
        )]
    return []


def detect_vsb002_empty_graph(graph: Graph) -> List[Issue]:
    """VSB002 — 0-unit graph is dead weight."""
    if graph.get("unit_count", 0) != 0:
        return []
    return [_emit(
        graph,
        rule_id="VSB002", category="BestPractices", severity="info",
        message="Graph has zero nodes — it's a no-op kept around for nothing.",
        fix_suggestion="Delete the asset if it's no longer wired into a runner / state machine.",
    )]


def detect_vsb003_deep_flow_chain(graph: Graph) -> List[Issue]:
    """VSB003 — long sequential chain in one path is hard to follow.

    Heuristic: a count of "Sequence" or "Flow" nodes paired with
    > 30 non-event units suggests the graph is one long script. The
    real depth check arrives with the edge parser in v1.4.5.
    """
    if graph.get("unit_count", 0) < 30:
        return []
    if not any("Sequence" in u["type"] or "Branch" in u["type"]
               for u in graph.get("units", [])):
        return []
    return [_emit(
        graph,
        rule_id="VSB003", category="Maintainability", severity="info",
        message=(
            f"Graph has {graph['unit_count']} nodes plus Sequence/Branch "
            "nodes — likely a single deep flow chain that reads like "
            "spaghetti."
        ),
        fix_suggestion="Refactor into sub-graphs or extract the deep portion into a C# behaviour.",
    )]


# ── VSS — Security ─────────────────────────────────────────────────


_SECRET_RE = re.compile(
    r"(?:api[_-]?key|password|secret|token|bearer)",
    re.IGNORECASE,
)


def detect_vss001_hardcoded_secret(graph: Graph) -> List[Issue]:
    """VSS001 — string literal inside any node containing a secret-ish name.

    Visual Scripting string literals live in the graph YAML as quoted
    values. Phase B scans the raw YAML for `value: "..."` lines with
    secret-like substrings. The parser doesn't expose literal lists
    yet; we fall back to a raw-content scan against the surrounding
    YAML the route forwards via the graph dict (`_raw_content` field
    when injected by the route — empty here).

    Without raw content the rule is a no-op; v1.4.5 will hook the
    parser to surface literals.
    """
    return []  # active in v1.4.5
