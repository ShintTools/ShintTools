# core/modules/code_validator/rules/cpp/ue5_cpp_rules.py
#
# Thin runner that imports all C++ rules from category modules
# and exposes run_all_cpp_rules() as the single entry point.
#
# Rule modules:
#   cpp/cpp_performance.py       — CP001-CP016  (15 rules)
#   cpp/cpp_best_practices.py    — CB001-CB032  (31 rules)
#   cpp/cpp_security.py          — CS001-CS012  (10 rules)
#   cpp/cpp_maintainability.py   — CM001-CM008  (8 rules)
# Total: 64 rules
#
# Shared helpers live in _cpp_helpers.py

from typing import List

# ── Best Practices (CB) ──────────────────────────────
from code_validator.rules.cpp.cpp_best_practices import (  # noqa: E402
    detect_auto_without_obvious_type,
    detect_blueprint_pure_side_effects,
    detect_c_style_cast,
    detect_const_ref_uproperty,
    detect_empty_if_body,
    detect_ensure_not_always,
    detect_exposed_on_spawn_no_default,
    detect_float_no_suffix,
    detect_fstring_as_identifier,
    detect_hardcoded_path,
    detect_infinite_loop,
    detect_lambda_implicit_capture,
    detect_log_verbose_shipping,
    detect_magic_numbers,
    detect_missing_override,
    detect_missing_super_beginplay,
    detect_non_virtual_destructor,
    detect_nullptr_deref,
    detect_printf,
    detect_public_member_without_uproperty,
    detect_raw_c_array,
    detect_raw_delete,
    detect_raw_new,
    detect_runtime_load,
    detect_stl_usage,
    detect_string_concat_in_loop,
    detect_string_literal_no_text_macro,
    detect_system_headers,
    detect_timer_lambda_raw_this,
    detect_ufunction_missing_category,
    detect_uproperty_nullptr,
)

# ── Maintainability (CM) ──────────────────────────────
from code_validator.rules.cpp.cpp_maintainability import (  # noqa: E402
    detect_debug_message,
    detect_deep_nesting,
    detect_duplicate_include,
    detect_empty_destructor,
    detect_file_too_long,
    detect_long_function,
    detect_todo_comments,
    detect_too_many_parameters,
)

# ── Performance (CP) ─────────────────────────────────
from code_validator.rules.cpp.cpp_performance import (  # noqa: E402
    detect_ensure_in_tick,
    detect_find_object_in_tick,
    detect_forceinline_large_function,
    detect_fstring_by_value,
    detect_garbage_collect_call,
    detect_get_all_actors_in_tick,
    detect_get_component_in_tick,
    detect_heavy_math_in_tick,
    detect_large_tick,
    detect_log_error_in_tick,
    detect_new_object_in_loop,
    detect_sleep_on_game_thread,
    detect_string_ops_in_tick,
    detect_tarray_copy_in_loop,
    detect_tick_enabled_in_constructor,
)

# ── Security (CS) ─────────────────────────────────────
from code_validator.rules.cpp.cpp_security import (  # noqa: E402
    detect_array_no_bounds_check,
    detect_cast_no_check,
    detect_division_no_zero_check,
    detect_getowner_no_check,
    detect_getworld_no_check,
    detect_hardcoded_secret,
    detect_http_insecure,
    detect_overlap_actor_no_check,
    detect_spawnactor_no_check,
    detect_weak_ptr_no_check,
)

from core.modules.code_validator.rules.cpp._cpp_helpers import (
    RULE_TO_PATTERN,
    Issue,
    _fixer,
)

# ── RUNNER ────────────────────────────────────────────


def run_all_cpp_rules(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Runs all deterministic C++ rules against the given
    file content and returns a merged list of issues.

    Performance (CP):      CP001-CP016  (15 rules)
    Best Practices (CB):   CB001-CB032  (31 rules)
    Security (CS):         CS001-CS012  (10 rules)
    Maintainability (CM):  CM001-CM008  (8 rules)
    """
    issues: List[Issue] = []

    # Performance
    issues += detect_find_object_in_tick(content, file_path)
    issues += detect_get_component_in_tick(content, file_path)
    issues += detect_large_tick(content, file_path)
    issues += detect_log_error_in_tick(content, file_path)
    issues += detect_sleep_on_game_thread(content, file_path)
    issues += detect_get_all_actors_in_tick(content, file_path)
    issues += detect_tick_enabled_in_constructor(content, file_path)
    issues += detect_heavy_math_in_tick(content, file_path)
    issues += detect_string_ops_in_tick(content, file_path)
    issues += detect_forceinline_large_function(content, file_path)
    issues += detect_fstring_by_value(content, file_path)
    issues += detect_tarray_copy_in_loop(content, file_path)
    issues += detect_new_object_in_loop(content, file_path)
    issues += detect_ensure_in_tick(content, file_path)
    issues += detect_garbage_collect_call(content, file_path)

    # Best Practices
    issues += detect_infinite_loop(content, file_path)
    issues += detect_runtime_load(content, file_path)
    issues += detect_raw_new(content, file_path)
    issues += detect_raw_delete(content, file_path)
    issues += detect_stl_usage(content, file_path)
    issues += detect_printf(content, file_path)
    issues += detect_system_headers(content, file_path)
    issues += detect_float_no_suffix(content, file_path)
    issues += detect_uproperty_nullptr(content, file_path)
    issues += detect_magic_numbers(content, file_path)
    issues += detect_empty_if_body(content, file_path)
    issues += detect_c_style_cast(content, file_path)
    issues += detect_nullptr_deref(content, file_path)
    issues += detect_hardcoded_path(content, file_path)
    issues += detect_auto_without_obvious_type(content, file_path)
    issues += detect_string_concat_in_loop(content, file_path)
    issues += detect_public_member_without_uproperty(content, file_path)
    issues += detect_raw_c_array(content, file_path)
    issues += detect_non_virtual_destructor(content, file_path)
    issues += detect_fstring_as_identifier(content, file_path)
    issues += detect_lambda_implicit_capture(content, file_path)
    issues += detect_ensure_not_always(content, file_path)
    issues += detect_missing_override(content, file_path)
    issues += detect_missing_super_beginplay(content, file_path)
    issues += detect_ufunction_missing_category(content, file_path)
    issues += detect_exposed_on_spawn_no_default(content, file_path)
    issues += detect_timer_lambda_raw_this(content, file_path)
    issues += detect_log_verbose_shipping(content, file_path)
    issues += detect_string_literal_no_text_macro(content, file_path)
    issues += detect_blueprint_pure_side_effects(content, file_path)
    issues += detect_const_ref_uproperty(content, file_path)

    # Security
    issues += detect_getworld_no_check(content, file_path)
    issues += detect_spawnactor_no_check(content, file_path)
    issues += detect_cast_no_check(content, file_path)
    issues += detect_division_no_zero_check(content, file_path)
    issues += detect_array_no_bounds_check(content, file_path)
    issues += detect_getowner_no_check(content, file_path)
    issues += detect_overlap_actor_no_check(content, file_path)
    issues += detect_weak_ptr_no_check(content, file_path)
    issues += detect_http_insecure(content, file_path)
    issues += detect_hardcoded_secret(content, file_path)

    # Maintainability
    issues += detect_debug_message(content, file_path)
    issues += detect_long_function(content, file_path)
    issues += detect_todo_comments(content, file_path)
    issues += detect_file_too_long(content, file_path)
    issues += detect_too_many_parameters(content, file_path)
    issues += detect_deep_nesting(content, file_path)
    issues += detect_duplicate_include(content, file_path)
    issues += detect_empty_destructor(content, file_path)

    # Inject context window (2 lines before + issue line + 2 after)
    # so the plugin can show a before/after diff without re-reading.
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
        issue["context_line_start"] = start + 1  # 1-based

        # Compute context_after using the fixer so the plugin
        # shows actual corrected code, not description text.
        #
        # Fallback chain:
        #   1. Try the rule's real fix pattern.
        #   2. If it returns unchanged code (edge case the fixer
        #      can't handle), fall back to mark_for_review so the
        #      AFTER panel shows a [SHINTTOOLS REVIEW] marker
        #      instead of being empty.
        after_context = ""
        rule_id = issue.get("rule_id", "")
        if (
            _fixer is not None
            and issue.get("is_auto_fixable")
            and rule_id in RULE_TO_PATTERN
        ):
            fixed_code = content
            try:
                fixed_code, _, _ = _fixer.fix(rule_id, content, line_no)
            except Exception:
                fixed_code = content  # fall through to fallback

            # Fallback: fixer couldn't transform the line — mark
            # it for manual review so the AFTER panel isn't empty.
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
                # Allow extra lines for multi-line fixes
                f_end = min(
                    len(fixed_lines),
                    start + len(window) + 4,
                )
                after_context = "\n".join(fixed_lines[start:f_end])
        issue["context_after"] = after_context

    return issues
