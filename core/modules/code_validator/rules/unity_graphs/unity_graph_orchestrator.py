"""Unity Visual Scripting orchestrator.

Mirrors `cpp_orchestrator` / `csharp_orchestrator`: runs every detector
over every parsed graph and applies the standard post-detection
enrichment (`enrich_issue` for `rule_name` + `rule_explanation`).
Auto-fix is deferred — YAML editing for graphs is a v1.4.5+ topic.
"""

from __future__ import annotations

from typing import Dict, List

from code_validator.rules._rule_metadata import enrich_issue
from code_validator.rules.unity_graphs.unity_graph_rules import (
    detect_vsb001_orphan_custom_event,
    detect_vsb002_empty_graph,
    detect_vsb003_deep_flow_chain,
    detect_vsm001_graph_too_large,
    detect_vsm002_disconnected_node,
    detect_vsp001_log_in_update,
    detect_vsp002_unsafe_cast,
    detect_vss001_hardcoded_secret,
)

Issue = Dict
Graph = Dict


def run_all_unity_graph_rules(graphs: List[Graph]) -> List[Issue]:
    """Run every Visual Scripting rule against every parsed graph.

    Each graph dict comes from `unity_vs_parser.parse_unity_graph`. The
    flat issue list is returned ready for the validate route to:
      1. mark is_auto_fixable from the (currently empty) pattern map,
      2. normalise asset_path -> file_path,
      3. apply tier filtering,
      4. compute the summary.
    """
    issues: List[Issue] = []
    for g in graphs:
        # Performance
        issues += detect_vsp001_log_in_update(g)
        issues += detect_vsp002_unsafe_cast(g)
        # Maintainability
        issues += detect_vsm001_graph_too_large(g)
        issues += detect_vsm002_disconnected_node(g)
        # Best practices
        issues += detect_vsb001_orphan_custom_event(g)
        issues += detect_vsb002_empty_graph(g)
        issues += detect_vsb003_deep_flow_chain(g)
        # Security
        issues += detect_vss001_hardcoded_secret(g)

    for issue in issues:
        enrich_issue(issue)

    return issues
