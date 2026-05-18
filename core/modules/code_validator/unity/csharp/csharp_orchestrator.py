# core/modules/code_validator/rules/csharp/csharp_orchestrator.py
#
# Orchestrator that imports all C# / Unity rules from category modules
# and exposes run_all_csharp_rules() as the single entry point.
#
# Rule modules:
#   csharp/csharp_performance.py       — CSP001-CSP016  (11 rules)
#   csharp/csharp_best_practices.py    — CSB001-CSB034  (14 rules)
#   csharp/csharp_security.py          — CSS001-CSS013  (9 rules)
#   csharp/csharp_maintainability.py   — CSM001-CSM008  (5 rules)
#   csharp/unity_specific.py           — UN001-UN025     (16 rules)
# Total: 55 rules
#
# The full taxonomy reserves 96 rule IDs across the five families;
# reserved IDs without an implementation yet are still legal in
# tiers.py so the free / indie filter stays stable across rule
# batches.
#
# Shared helpers live in _csharp_helpers.py

from typing import Dict, List

from code_validator.shared._rule_metadata import enrich_issue
from code_validator.unity.csharp._csharp_helpers import CSHARP_RULE_TO_PATTERN, _fixer

# ── Best practices (CSB) ──────────────────────────────
from code_validator.unity.csharp.csharp_best_practices import (  # noqa: E402
    detect_async_void,
    detect_catch_exception_broad,
    detect_commented_out_code,
    detect_empty_catch,
    detect_empty_destructor,
    detect_empty_if_body,
    detect_event_not_unsubscribed,
    detect_float_no_f_suffix,
    detect_hardcoded_path,
    detect_infinite_loop,
    detect_log_outside_editor_guard,
    detect_magic_number,
    detect_missing_override,
    detect_todo_comment,
)

# ── Maintainability (CSM) ─────────────────────────────
from code_validator.unity.csharp.csharp_maintainability import (  # noqa: E402
    detect_class_god_object,
    detect_deep_nesting,
    detect_long_file,
    detect_long_method,
    detect_too_many_params,
)

# ── Performance (CSP) ─────────────────────────────────
from code_validator.unity.csharp.csharp_performance import (  # noqa: E402
    detect_collection_copy_in_loop,
    detect_debug_assert_in_update,
    detect_gc_collect,
    detect_heavy_math_in_update,
    detect_instantiate_in_update,
    detect_large_update_body,
    detect_linq_in_update,
    detect_new_object_in_loop,
    detect_new_waitforseconds,
    detect_string_concat_in_loop,
    detect_string_ops_in_update,
)

# ── Security (CSS) ────────────────────────────────────
from code_validator.unity.csharp.csharp_security import (  # noqa: E402
    detect_collision_no_null_check,
    detect_direct_cast_no_check,
    detect_division_no_zero_check,
    detect_getcomponent_no_check,
    detect_hardcoded_secret,
    detect_http_url,
    detect_instantiate_no_check,
    detect_playerprefs_secret,
    detect_sql_concat,
)

# ── Unity-specific (UN) ───────────────────────────────
from code_validator.unity.csharp.unity_specific import (  # noqa: E402
    detect_camera_main_in_update,
    detect_coroutine_leak,
    detect_dont_destroy_non_singleton,
    detect_empty_update,
    detect_findobject_in_update,
    detect_findobjectoftype_in_update,
    detect_getcomponent_in_update,
    detect_log_in_update,
    detect_missing_require_component,
    detect_physics_in_update,
    detect_public_field_monobehaviour,
    detect_resources_load,
    detect_scriptableobject_no_menu,
    detect_sendmessage_use,
    detect_tag_string_compare,
    detect_transform_in_loop,
)

Issue = Dict


def run_all_csharp_rules(
    content: str,
    file_path: str,
) -> List[Issue]:
    """Run all implemented C# / Unity rules against a .cs source file.

    Currently covers 55 of the 96 reserved IDs. The validate route maps
    `engine="unity"` + .cs extension here; subsequent rule batches extend
    this orchestrator without any caller-side change.
    """
    issues: List[Issue] = []

    # Performance (CSP*)
    issues += detect_linq_in_update(content, file_path)
    issues += detect_string_concat_in_loop(content, file_path)
    issues += detect_instantiate_in_update(content, file_path)
    issues += detect_new_waitforseconds(content, file_path)

    # Unity-specific (UN*)
    issues += detect_findobject_in_update(content, file_path)
    issues += detect_getcomponent_in_update(content, file_path)
    issues += detect_findobjectoftype_in_update(content, file_path)
    issues += detect_log_in_update(content, file_path)
    issues += detect_sendmessage_use(content, file_path)
    issues += detect_public_field_monobehaviour(content, file_path)
    issues += detect_empty_update(content, file_path)
    issues += detect_camera_main_in_update(content, file_path)
    issues += detect_tag_string_compare(content, file_path)

    # Best practices (CSB*)
    issues += detect_empty_catch(content, file_path)
    issues += detect_todo_comment(content, file_path)
    issues += detect_catch_exception_broad(content, file_path)
    issues += detect_async_void(content, file_path)
    issues += detect_magic_number(content, file_path)

    # Security (CSS*)
    issues += detect_sql_concat(content, file_path)
    issues += detect_hardcoded_secret(content, file_path)
    issues += detect_http_url(content, file_path)
    issues += detect_playerprefs_secret(content, file_path)

    # Maintainability (CSM*)
    issues += detect_long_method(content, file_path)
    issues += detect_long_file(content, file_path)
    issues += detect_class_god_object(content, file_path)
    issues += detect_too_many_params(content, file_path)
    issues += detect_deep_nesting(content, file_path)

    # Performance (CSP*) — batch 3
    issues += detect_heavy_math_in_update(content, file_path)
    issues += detect_string_ops_in_update(content, file_path)
    issues += detect_large_update_body(content, file_path)
    issues += detect_collection_copy_in_loop(content, file_path)
    issues += detect_new_object_in_loop(content, file_path)
    issues += detect_gc_collect(content, file_path)
    issues += detect_debug_assert_in_update(content, file_path)

    # Best practices (CSB*) — batch 3
    issues += detect_infinite_loop(content, file_path)
    issues += detect_missing_override(content, file_path)
    issues += detect_hardcoded_path(content, file_path)
    issues += detect_empty_if_body(content, file_path)
    issues += detect_event_not_unsubscribed(content, file_path)
    issues += detect_log_outside_editor_guard(content, file_path)
    issues += detect_float_no_f_suffix(content, file_path)
    issues += detect_empty_destructor(content, file_path)
    issues += detect_commented_out_code(content, file_path)

    # Security (CSS*) — batch 3
    issues += detect_instantiate_no_check(content, file_path)
    issues += detect_getcomponent_no_check(content, file_path)
    issues += detect_direct_cast_no_check(content, file_path)
    issues += detect_division_no_zero_check(content, file_path)
    issues += detect_collision_no_null_check(content, file_path)

    # Unity-specific (UN*) — batch 3
    issues += detect_coroutine_leak(content, file_path)
    issues += detect_physics_in_update(content, file_path)
    issues += detect_transform_in_loop(content, file_path)
    issues += detect_missing_require_component(content, file_path)
    issues += detect_dont_destroy_non_singleton(content, file_path)
    issues += detect_resources_load(content, file_path)
    issues += detect_scriptableobject_no_menu(content, file_path)

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
