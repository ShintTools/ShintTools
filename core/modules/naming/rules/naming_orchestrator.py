# core/modules/naming/rules/naming_orchestrator.py
#
# Orchestrator that imports all naming rules
# and exposes run_all_naming_rules() as the single entry point.
#
# Rule modules:
#   ue5_naming_rules.py — NM001-NM018 (18 rules)
#
# Total: 18 rules

from typing import Any, Dict, List

from code_validator.rules._rule_metadata import enrich_issue
from naming.rules.ue5_naming_rules import (
    detect_consecutive_underscores,
    detect_double_prefix,
    detect_duplicate_names,
    detect_generic_name,
    detect_lowercase_names,
    detect_missing_prefix,
    detect_missing_tex_suffix,
    detect_name_too_long,
    detect_name_too_short,
    detect_non_pascal_case,
    detect_number_start,
    detect_redundant_type_in_name,
    detect_spaces_in_name,
    detect_special_chars,
    detect_trailing_underscore,
    detect_version_suffix,
    detect_wrong_folder,
    detect_wrong_prefix_for_type,
)

# Type aliases
Issue = Dict[str, Any]
AssetRecord = Dict[str, str]

# ── RUNNER ────────────────────────────────────────────


def run_all_naming_rules(asset_records: List[AssetRecord]) -> List[Issue]:
    """Run NM001–NM018 against a list of asset record dicts.

    Each record must have: asset_path (str), asset_type (str).
    Returns a merged list of all naming issues found.
    Called by POST /assets/scan in api/routes/assets.py.
    """
    all_issues: List[Issue] = []

    all_issues += detect_missing_prefix(asset_records)
    all_issues += detect_spaces_in_name(asset_records)
    all_issues += detect_special_chars(asset_records)
    all_issues += detect_lowercase_names(asset_records)
    all_issues += detect_duplicate_names(asset_records)
    all_issues += detect_missing_tex_suffix(asset_records)
    all_issues += detect_non_pascal_case(asset_records)
    all_issues += detect_name_too_long(asset_records)
    all_issues += detect_wrong_folder(asset_records)
    all_issues += detect_double_prefix(asset_records)
    all_issues += detect_number_start(asset_records)
    all_issues += detect_consecutive_underscores(asset_records)
    all_issues += detect_trailing_underscore(asset_records)
    all_issues += detect_generic_name(asset_records)
    all_issues += detect_version_suffix(asset_records)
    all_issues += detect_wrong_prefix_for_type(asset_records)
    all_issues += detect_name_too_short(asset_records)
    all_issues += detect_redundant_type_in_name(asset_records)

    # Enrich every issue with `rule_name` (humanized title) and
    # `rule_explanation` (first paragraph of the detector's docstring).
    # The LLM uses these as authoritative grounding and customer-facing
    # copy; the internal `rule_id` stays for fixer routing and scoring.
    for issue in all_issues:
        enrich_issue(issue)

    return all_issues
