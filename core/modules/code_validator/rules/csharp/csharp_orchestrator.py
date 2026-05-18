# core/modules/code_validator/rules/csharp/csharp_orchestrator.py
#
# C# / Unity orchestrator — mirrors cpp_orchestrator for the Unity engine.
#
# The full taxonomy reserves 96 rule IDs across five families:
#
#   CSP001-CSP016  Performance         (16 rules)
#   CSB001-CSB034  Best practices      (34 rules)
#   CSS001-CSS013  Security            (13 rules)
#   CSM001-CSM008  Maintainability     (8 rules)
#   UN001-UN025    Unity-specific      (25 rules)
#
# This file currently registers 59 detectors (batches 1–3). Reserved
# IDs without an implementation yet are still legal in tiers.py so the
# free / indie filter stays stable across rule batches.

from typing import Dict, List

from code_validator.rules._rule_metadata import enrich_issue
from code_validator.rules.csharp._csharp_helpers import CSHARP_RULE_TO_PATTERN, _fixer
from code_validator.rules.csharp.csharp_rules import (  # Batch 1; Batch 2; Batch 3 — Performance; Batch 3 — Best Practices; Batch 3 — Security; Batch 3 — Unity-specific  # noqa: E501
    detect_csb001_empty_catch,
    detect_csb002_todo_comment,
    detect_csb003_catch_exception_broad,
    detect_csb004_infinite_loop,
    detect_csb005_async_void,
    detect_csb006_magic_number,
    detect_csb007_missing_base_start_awake,
    detect_csb008_missing_base_ondestroy,
    detect_csb009_missing_override,
    detect_csb010_hardcoded_path,
    detect_csb011_empty_if_body,
    detect_csb012_event_not_unsubscribed,
    detect_csb013_log_outside_editor_guard,
    detect_csb014_float_no_f_suffix,
    detect_csb015_empty_destructor,
    detect_csb016_commented_out_code,
    detect_csm001_long_method,
    detect_csm002_long_file,
    detect_csm003_class_god_object,
    detect_csm004_too_many_params,
    detect_csm005_deep_nesting,
    detect_csp001_linq_in_update,
    detect_csp002_string_concat_in_loop,
    detect_csp003_heavy_math_in_update,
    detect_csp004_instantiate_in_update,
    detect_csp005_thread_sleep,
    detect_csp006_new_waitforseconds,
    detect_csp007_string_ops_in_update,
    detect_csp008_large_update_body,
    detect_csp009_collection_copy_in_loop,
    detect_csp010_new_object_in_loop,
    detect_csp011_gc_collect,
    detect_csp012_debug_assert_in_update,
    detect_csp013_resources_load_in_update,
    detect_css001_sql_concat,
    detect_css002_hardcoded_secret,
    detect_css003_http_url,
    detect_css004_playerprefs_secret,
    detect_css005_instantiate_no_check,
    detect_css006_getcomponent_no_check,
    detect_css007_direct_cast_no_check,
    detect_css008_division_no_zero_check,
    detect_css009_collision_no_null_check,
    detect_un001_findobject_in_update,
    detect_un002_getcomponent_in_update,
    detect_un003_findobjectoftype_in_update,
    detect_un004_log_in_update,
    detect_un005_sendmessage_use,
    detect_un006_public_field_monobehaviour,
    detect_un007_empty_update,
    detect_un008_camera_main_in_update,
    detect_un009_coroutine_leak,
    detect_un010_physics_in_update,
    detect_un011_transform_in_loop,
    detect_un012_tag_string_compare,
    detect_un013_missing_require_component,
    detect_un014_dont_destroy_non_singleton,
    detect_un015_resources_load,
    detect_un016_scriptableobject_no_menu,
)

Issue = Dict


def run_all_csharp_rules(
    content: str,
    file_path: str,
) -> List[Issue]:
    """Run all implemented C# / Unity rules against a .cs source file.

    Currently covers 59 of the 96 reserved IDs (batches 1–3). The
    validate route maps `engine="unity"` + .cs extension here;
    subsequent rule batches extend this orchestrator without any
    caller-side change.
    """
    issues: List[Issue] = []

    # Performance (CSP*)
    issues += detect_csp001_linq_in_update(content, file_path)
    issues += detect_csp002_string_concat_in_loop(content, file_path)
    issues += detect_csp004_instantiate_in_update(content, file_path)
    issues += detect_csp006_new_waitforseconds(content, file_path)

    # Unity-specific (UN*)
    issues += detect_un001_findobject_in_update(content, file_path)
    issues += detect_un002_getcomponent_in_update(content, file_path)
    issues += detect_un003_findobjectoftype_in_update(content, file_path)
    issues += detect_un004_log_in_update(content, file_path)
    issues += detect_un005_sendmessage_use(content, file_path)
    issues += detect_un006_public_field_monobehaviour(content, file_path)
    issues += detect_un007_empty_update(content, file_path)
    issues += detect_un008_camera_main_in_update(content, file_path)
    issues += detect_un012_tag_string_compare(content, file_path)

    # Best practices (CSB*)
    issues += detect_csb001_empty_catch(content, file_path)
    issues += detect_csb002_todo_comment(content, file_path)
    issues += detect_csb003_catch_exception_broad(content, file_path)
    issues += detect_csb005_async_void(content, file_path)
    issues += detect_csb006_magic_number(content, file_path)

    # Security (CSS*)
    issues += detect_css001_sql_concat(content, file_path)
    issues += detect_css002_hardcoded_secret(content, file_path)
    issues += detect_css003_http_url(content, file_path)
    issues += detect_css004_playerprefs_secret(content, file_path)

    # Maintainability (CSM*)
    issues += detect_csm001_long_method(content, file_path)
    issues += detect_csm002_long_file(content, file_path)
    issues += detect_csm003_class_god_object(content, file_path)
    issues += detect_csm004_too_many_params(content, file_path)
    issues += detect_csm005_deep_nesting(content, file_path)

    # ── Batch 3 ──────────────────────────────────────────────────────────

    # Performance (CSP*) — batch 3
    issues += detect_csp003_heavy_math_in_update(content, file_path)
    issues += detect_csp005_thread_sleep(content, file_path)
    issues += detect_csp007_string_ops_in_update(content, file_path)
    issues += detect_csp008_large_update_body(content, file_path)
    issues += detect_csp009_collection_copy_in_loop(content, file_path)
    issues += detect_csp010_new_object_in_loop(content, file_path)
    issues += detect_csp011_gc_collect(content, file_path)
    issues += detect_csp012_debug_assert_in_update(content, file_path)
    issues += detect_csp013_resources_load_in_update(content, file_path)

    # Best practices (CSB*) — batch 3
    issues += detect_csb004_infinite_loop(content, file_path)
    issues += detect_csb007_missing_base_start_awake(content, file_path)
    issues += detect_csb008_missing_base_ondestroy(content, file_path)
    issues += detect_csb009_missing_override(content, file_path)
    issues += detect_csb010_hardcoded_path(content, file_path)
    issues += detect_csb011_empty_if_body(content, file_path)
    issues += detect_csb012_event_not_unsubscribed(content, file_path)
    issues += detect_csb013_log_outside_editor_guard(content, file_path)
    issues += detect_csb014_float_no_f_suffix(content, file_path)
    issues += detect_csb015_empty_destructor(content, file_path)
    issues += detect_csb016_commented_out_code(content, file_path)

    # Security (CSS*) — batch 3
    issues += detect_css005_instantiate_no_check(content, file_path)
    issues += detect_css006_getcomponent_no_check(content, file_path)
    issues += detect_css007_direct_cast_no_check(content, file_path)
    issues += detect_css008_division_no_zero_check(content, file_path)
    issues += detect_css009_collision_no_null_check(content, file_path)

    # Unity-specific (UN*) — batch 3
    issues += detect_un009_coroutine_leak(content, file_path)
    issues += detect_un010_physics_in_update(content, file_path)
    issues += detect_un011_transform_in_loop(content, file_path)
    issues += detect_un013_missing_require_component(content, file_path)
    issues += detect_un014_dont_destroy_non_singleton(content, file_path)
    issues += detect_un015_resources_load(content, file_path)
    issues += detect_un016_scriptableobject_no_menu(content, file_path)

    # ── Context window + AFTER preview ───────────────────────────────
    _CONTEXT = 2
    source_lines = content.splitlines()
    for issue in issues:
        line_no = issue.get("line", 0)
        if line_no < 1 or not source_lines:
            continue

        start = max(0, line_no - 1 - _CONTEXT)
        end = min(len(source_lines), line_no + _CONTEXT)
        window = source_lines[start:end]
        issue["context_before"] = "\n".join(window)
        issue["context_line_start"] = start + 1

        after_context = ""
        rule_id = issue.get("rule_id", "")
        if (
            _fixer is not None
            and issue.get("is_auto_fixable")
            and rule_id in CSHARP_RULE_TO_PATTERN
        ):
            fixed_code = content
            try:
                fixed_code, _, _ = _fixer.fix(rule_id, content, line_no)
            except Exception:
                fixed_code = content

            if fixed_code == content:
                try:
                    reason = issue.get(
                        "fix_suggestion",
                        "Manual review required",
                    )
                    fixed_code, _, _ = _fixer._apply_mark_for_review(
                        content,
                        line_no,
                        reason,
                    )
                except Exception:
                    fixed_code = content

            if fixed_code != content:
                fixed_lines = fixed_code.splitlines()
                f_end = min(
                    len(fixed_lines),
                    start + len(window) + 4,
                )
                after_context = "\n".join(fixed_lines[start:f_end])

        issue["context_after"] = after_context

    for issue in issues:
        enrich_issue(issue)

    return issues
