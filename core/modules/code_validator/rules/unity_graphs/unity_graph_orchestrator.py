"""Unity Visual Scripting orchestrator.

Mirrors `cpp_orchestrator` / `csharp_orchestrator`: runs every detector
over every parsed graph and applies the standard post-detection
enrichment (`enrich_issue` for `rule_name` + `rule_explanation`).
Auto-fix is deferred — YAML editing for graphs is a v1.4.5+ topic.

20 rules (batches 1 + 2):
  VSP001-005  Performance      (5)
  VSM001-004  Maintainability  (4)
  VSB001-008  Best practices   (8)
  VSS001-003  Security         (3)
"""

from __future__ import annotations

from typing import Dict, List

from code_validator.rules._rule_metadata import enrich_issue
from code_validator.rules.unity_graphs.unity_graph_rules import (
    detect_vsb001_orphan_custom_event,
    detect_vsb002_empty_graph,
    detect_vsb003_deep_flow_chain,
    detect_vsb004_multiple_event_roots,
    detect_vsb005_getcomponent_no_null_check,
    detect_vsb006_send_message,
    detect_vsb007_wait_for_seconds_in_update,
    detect_vsb008_script_graph_no_root,
    detect_vsm001_graph_too_large,
    detect_vsm002_disconnected_node,
    detect_vsm003_variable_overload,
    detect_vsm004_state_machine_too_large,
    detect_vsp001_log_in_update,
    detect_vsp002_unsafe_cast,
    detect_vsp003_getcomponent_in_update,
    detect_vsp004_find_in_update,
    detect_vsp005_instantiate_destroy_in_update,
    detect_vss001_hardcoded_secret,
    detect_vss002_debug_break_in_graph,
    detect_vss003_player_prefs_set,
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
        issues += detect_vsp003_getcomponent_in_update(g)
        issues += detect_vsp004_find_in_update(g)
        issues += detect_vsp005_instantiate_destroy_in_update(g)
        # Maintainability
        issues += detect_vsm001_graph_too_large(g)
        issues += detect_vsm002_disconnected_node(g)
        issues += detect_vsm003_variable_overload(g)
        issues += detect_vsm004_state_machine_too_large(g)
        # Best practices
        issues += detect_vsb001_orphan_custom_event(g)
        issues += detect_vsb002_empty_graph(g)
        issues += detect_vsb003_deep_flow_chain(g)
        issues += detect_vsb004_multiple_event_roots(g)
        issues += detect_vsb005_getcomponent_no_null_check(g)
        issues += detect_vsb006_send_message(g)
        issues += detect_vsb007_wait_for_seconds_in_update(g)
        issues += detect_vsb008_script_graph_no_root(g)
        # Security
        issues += detect_vss001_hardcoded_secret(g)
        issues += detect_vss002_debug_break_in_graph(g)
        issues += detect_vss003_player_prefs_set(g)

    for issue in issues:
        enrich_issue(issue)

    return issues
