# core/modules/naming/rules/naming_orchestrator.py
#
# Orchestrator that imports all naming rules and exposes
# run_all_naming_rules(records, engine) as the single entry point.
#
# Rule modules:
#   ue5_naming_rules.py     — NM001-NM018  (18 UE5 rules)
#   unity_naming_rules.py   — NMU001/009/016 (3 Unity-specific rules)
#
# The three engine-specific rules (missing prefix, wrong folder,
# wrong prefix for type) depend on prefix/folder tables that differ
# between UE5 and Unity. Engine-agnostic checks (spaces, special chars,
# case, duplicates, length, generic names, version suffix, etc.) come
# from ue5_naming_rules and are reused for both engines unchanged —
# their detection logic doesn't reference engine-specific tables.

from typing import Any, Dict, List

from code_validator.shared._rule_metadata import enrich_issue
from naming.unity.unity_naming_rules import (
    detect_unity_missing_prefix,
    detect_unity_wrong_folder,
    detect_unity_wrong_prefix_for_type,
)
from naming.unreal.ue5_naming_rules import (
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


def run_all_naming_rules(
    asset_records: List[AssetRecord],
    engine: str = "unreal",
) -> List[Issue]:
    """Run naming detectors against a list of asset record dicts.

    Each record must have: asset_path (str), asset_type (str).
    `engine` is "unreal" or "unity" and selects which prefix / folder
    table to use for the three engine-specific detectors. Defaults to
    "unreal" to preserve the pre-Unity behaviour for any caller that
    hasn't been updated yet.

    Returns a merged list of all naming issues found.
    Called by POST /assets/scan in api/routes/assets.py.
    """
    all_issues: List[Issue] = []
    engine = (engine or "unreal").lower()

    # Engine-specific: prefix + folder rules need different tables.
    if engine == "unity":
        all_issues += detect_unity_missing_prefix(asset_records)
        all_issues += detect_unity_wrong_folder(asset_records)
        all_issues += detect_unity_wrong_prefix_for_type(asset_records)
    else:
        all_issues += detect_missing_prefix(asset_records)
        all_issues += detect_wrong_folder(asset_records)
        all_issues += detect_wrong_prefix_for_type(asset_records)

    # Engine-agnostic detectors — same logic for both engines.
    all_issues += detect_spaces_in_name(asset_records)
    all_issues += detect_special_chars(asset_records)
    all_issues += detect_lowercase_names(asset_records)
    all_issues += detect_duplicate_names(asset_records)
    all_issues += detect_missing_tex_suffix(asset_records)
    all_issues += detect_non_pascal_case(asset_records)
    all_issues += detect_name_too_long(asset_records)
    all_issues += detect_double_prefix(asset_records)
    all_issues += detect_number_start(asset_records)
    all_issues += detect_consecutive_underscores(asset_records)
    all_issues += detect_trailing_underscore(asset_records)
    all_issues += detect_generic_name(asset_records)
    all_issues += detect_version_suffix(asset_records)
    all_issues += detect_name_too_short(asset_records)
    all_issues += detect_redundant_type_in_name(asset_records)

    # Enrich every issue with `rule_name` (humanized title) and
    # `rule_explanation` (first paragraph of the detector's docstring).
    # The LLM uses these as authoritative grounding and customer-facing
    # copy; the internal `rule_id` stays for fixer routing and scoring.
    for issue in all_issues:
        enrich_issue(issue)

    return all_issues
