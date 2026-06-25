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
    detect_unity_audio_missing_suffix,
    detect_unity_backslash_in_path,
    detect_unity_double_slash,
    detect_unity_editor_folder_misuse,
    detect_unity_missing_prefix,
    detect_unity_parent_dir_in_path,
    detect_unity_path_outside_assets,
    detect_unity_resources_folder,
    detect_unity_scene_misplaced,
    detect_unity_script_misplaced,
    detect_unity_scriptableobject_suffix,
    detect_unity_streaming_assets,
    detect_unity_texture_pbr_suffix,
    detect_unity_uppercase_extension,
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

# ── Unity ID remap ────────────────────────────────────
# Engine-agnostic rules emit NM002-NM018 regardless of engine.
# When scanning Unity assets those NM* IDs confuse the Unity plugin
# (they look like UE5 rules). This table remaps each one to an NMU*
# equivalent so Unity clients only ever see NMU-prefixed findings.
_NM_TO_NMU_UNITY: dict[str, str] = {
    "NM002": "NMU017",  # spaces in name
    "NM003": "NMU018",  # special chars
    "NM004": "NMU019",  # lowercase names
    "NM005": "NMU020",  # duplicate names
    "NM006": "NMU021",  # missing tex suffix
    "NM007": "NMU022",  # non pascal case
    "NM008": "NMU023",  # name too long
    "NM010": "NMU024",  # double prefix
    "NM011": "NMU025",  # number start
    "NM012": "NMU026",  # consecutive underscores
    "NM013": "NMU027",  # trailing underscore
    "NM014": "NMU028",  # generic name
    "NM015": "NMU029",  # version suffix
    "NM017": "NMU030",  # name too short
    "NM018": "NMU031",  # redundant type in name
}

# ── Already-compliant guard ───────────────────────────
# Rules that legitimately emit a fix_suggestion equal to the current name:
# the violation is not about the name itself (a cross-folder collision or
# wrong folder) or there is no actionable rename (no recognised prefix,
# body too short, body reduces to empty). These are preserved; every other
# rule with suggestion == current_name is a no-op and is dropped.
_NAME_PRESERVING_RULES = {"NM001", "NM005", "NM009", "NM017", "NM018"}


def _drop_noop_suggestions(issues: List[Issue]) -> List[Issue]:
    """Remove findings whose suggested name equals the asset's current name.

    A rename rule whose fix matches the current name means the asset already
    follows the convention — surfacing it produces a confusing "rename
    SM_Rock → SM_Rock" suggestion. Runs in NM* id space (before the Unity
    remap). Unity-specific findings carry no ``current_name`` and so pass
    through untouched; only rules in ``_NAME_PRESERVING_RULES`` keep a
    same-name suggestion.
    """
    return [
        issue
        for issue in issues
        if not (
            issue.get("current_name")
            and issue.get("fix_suggestion", "").strip()
            == issue.get("current_name", "").strip()
            and issue.get("rule_id") not in _NAME_PRESERVING_RULES
        )
    ]


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
        all_issues += detect_unity_path_outside_assets(asset_records)
        all_issues += detect_unity_backslash_in_path(asset_records)
        all_issues += detect_unity_script_misplaced(asset_records)
        all_issues += detect_unity_resources_folder(asset_records)
        all_issues += detect_unity_streaming_assets(asset_records)
        all_issues += detect_unity_editor_folder_misuse(asset_records)
        all_issues += detect_unity_scene_misplaced(asset_records)
        all_issues += detect_unity_scriptableobject_suffix(asset_records)
        all_issues += detect_unity_texture_pbr_suffix(asset_records)
        all_issues += detect_unity_uppercase_extension(asset_records)
        all_issues += detect_unity_parent_dir_in_path(asset_records)
        all_issues += detect_unity_double_slash(asset_records)
        all_issues += detect_unity_audio_missing_suffix(asset_records)
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

    # Drop no-op suggestions for assets that already follow the convention.
    all_issues = _drop_noop_suggestions(all_issues)

    # When running for Unity, remap engine-agnostic NM* IDs to NMU* so
    # the Unity plugin never sees UE5-prefixed rule IDs.
    if engine == "unity":
        for issue in all_issues:
            nm_id = issue.get("rule_id", "")
            nmu_id = _NM_TO_NMU_UNITY.get(nm_id)
            if nmu_id:
                issue["rule_id"] = nmu_id

    # Enrich every issue with `rule_name` (humanized title) and
    # `rule_explanation` (first paragraph of the detector's docstring).
    # The LLM uses these as authoritative grounding and customer-facing
    # copy; the internal `rule_id` stays for fixer routing and scoring.
    for issue in all_issues:
        enrich_issue(issue)

    return all_issues
