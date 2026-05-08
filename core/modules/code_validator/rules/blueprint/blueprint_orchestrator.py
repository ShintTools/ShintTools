# core/modules/code_validator/rules/blueprint/blueprint_orchestrator.py
#
# Orchestrator that imports all Blueprint rules
# and exposes run_all_blueprint_rules() and run_all_blueprint_rules_from_export()
# as the single entry points.
#
# Rule modules:
#   blueprint_rules.py — all 21 Blueprint rules
#
# Total: 21 rules
#   Best Practices (BPB): BPB001-BPB007  (7 rules)
#   Performance (BPP):    BPP001-BPP005  (5 rules)
#   Maintainability (BPM): BPM001-BPM007 (7 rules)
#   Security (BPS):       BPS001, BPS003 (2 rules)

from typing import Dict, List

try:
    from code_validator.parsers.fixers.fix_patterns import build_bp_fix_instruction
except ModuleNotFoundError:
    build_bp_fix_instruction = None  # type: ignore[assignment]

from code_validator.rules._rule_metadata import enrich_issue
from code_validator.rules.blueprint.blueprint_rules import (
    detect_abandoned_blueprint,
    detect_blueprint_no_functions,
    detect_console_command_usage,
    detect_delay_in_tick,
    detect_disconnected_nodes,
    detect_excessive_casts,
    detect_function_no_tooltip,
    detect_generic_variable_name,
    detect_get_all_actors_in_tick,
    detect_heavy_event_tick,
    detect_high_complexity_function,
    detect_large_blueprint,
    detect_large_graph,
    detect_missing_authority_check,
    detect_missing_begin_play_super,
    detect_missing_bp_prefix,
    detect_missing_end_play_super,
    detect_no_functions_large_graph,
    detect_tick_enabled,
    detect_unused_variables,
    detect_variable_no_category,
)

# Type alias for issue dictionary
Issue = Dict[str, object]

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

    # Maintainability
    issues += detect_unused_variables(blueprint)
    issues += detect_disconnected_nodes(blueprint)
    issues += detect_large_blueprint(blueprint)
    issues += detect_high_complexity_function(blueprint)
    issues += detect_large_graph(blueprint)
    issues += detect_blueprint_no_functions(blueprint)
    issues += detect_abandoned_blueprint(blueprint)

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

    # Enrich every issue with `rule_name` (humanized title) and
    # `rule_explanation` (first paragraph of the detector's docstring).
    # The LLM uses these as authoritative grounding and customer-facing
    # copy; the internal `rule_id` stays for fixer routing and scoring.
    for issue in issues:
        enrich_issue(issue)

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
