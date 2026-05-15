# core/modules/code_validator/rules/_rule_metadata.py
#
# Single source of truth for customer-facing rule metadata.
#
# Two products, both keyed by rule_id (e.g. "CS001"):
#   1. RULE_NAMES        — hardcoded humanized title (114 entries).
#                          Shown to customers; used by the LLM in user-
#                          facing answers; never expose rule_id in copy.
#   2. RULE_EXPLANATIONS  — extracted at first use from each detector
#                          function's docstring (first paragraph only,
#                          rule_id prefix stripped). The LLM uses this
#                          as authoritative grounding so a 1.3B model
#                          doesn't have to guess UE5 semantics.
#
# Consumers:
#   - cpp/blueprint/naming orchestrators call enrich_issue() at the end
#     of every run.
#   - The agent prompt instructs the LLM to use rule_name in copy and
#     rule_explanation as ground truth.
#   - Plugin / dashboard can show rule_name as tooltip / detail title.

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Optional

# ── Humanized rule names ───────────────────────────────────────────────────
#
# Order matches the rule_id sequence (CP, CB, CS, CM, BPB, BPP, BPM, BPS, NM).
# Keep entries short (< 50 chars) — they are titles, not explanations.

RULE_NAMES: Dict[str, str] = {
    # ── C++ Performance (CP) ─────────────────────────────
    "CP001": "FindObject in Tick",
    "CP002": "GetComponent in Tick",
    "CP003": "Tick body too long",
    "CP004": "UE_LOG error in Tick",
    "CP005": "Sleep on game thread",
    "CP006": "GetAllActorsOfClass in Tick",
    "CP007": "Tick enabled in constructor",
    "CP008": "Heavy math in Tick",
    "CP009": "String operations in Tick",
    "CP010": "FORCEINLINE on large function",
    "CP011": "FString passed by value",
    "CP012": "TArray copied in loop",
    "CP013": "NewObject in loop",
    "CP015": "ensure() in Tick",
    "CP016": "Manual GarbageCollect call",
    "CP017": "Empty Tick override",
    "CP018": "SpawnActor in Tick",
    # ── C++ Best Practices (CB) ──────────────────────────
    "CB001": "Infinite loop without exit",
    "CB002": "Runtime asset load on game thread",
    "CB003": "Raw new operator",
    "CB004": "Raw delete operator",
    "CB005": "STL container in UE5 code",
    "CB006": "printf instead of UE_LOG",
    "CB007": "System header instead of UE5 header",
    "CB008": "Float literal without f suffix",
    "CB009": "UPROPERTY pointer initialised to nullptr only",
    "CB010": "Magic number in expression",
    "CB011": "Empty if/else body",
    "CB012": "C-style cast",
    "CB013": "Pointer dereference without null-check",
    "CB014": "Hardcoded path",
    "CB015": "auto with non-obvious type",
    "CB016": "String concatenation in loop",
    "CB017": "Public member without UPROPERTY",
    "CB018": "Raw C array instead of TArray",
    "CB019": "Non-virtual destructor in base class",
    "CB020": "FString used as identifier",
    "CB021": "Lambda implicit capture",
    "CB022": "ensure() that should be ensureAlways()",
    "CB023": "Missing override specifier",
    "CB024": "Missing Super::BeginPlay() call",
    "CB025": "UFUNCTION without Category",
    "CB026": "ExposeOnSpawn without default value",
    "CB028": "Timer lambda captures raw this",
    "CB029": "VeryVerbose log in shipping build",
    "CB030": "String literal without TEXT() macro",
    "CB031": "BlueprintPure with side effects",
    "CB032": "UPROPERTY const reference",
    "CB033": "Missing Super::EndPlay() call",
    "CB034": "Raw pointer in UPROPERTY",
    "CB035": "UPROPERTY without Category",
    # ── C++ Security (CS) ─────────────────────────────────
    "CS001": "GetWorld without null-check",
    "CS002": "SpawnActor result not checked",
    "CS003": "Cast<> result not checked",
    "CS004": "Division without zero-check",
    "CS005": "Array access without bounds-check",
    "CS006": "GetOwner without null-check",
    "CS007": "OverlapActor without null-check",
    "CS008": "WeakPtr without IsValid check",
    "CS011": "Insecure HTTP URL",
    "CS012": "Hardcoded secret in source",
    "CS013": "PlayerController without null-check",
    "CS014": "GameInstance without null-check",
    "CS015": "PlayerState without null-check",
    "CS016": "Server RPC without WithValidation",
    "CS017": "Client RPC modifies replicated state",
    # ── C++ Maintainability (CM) ──────────────────────────
    "CM001": "Debug message left in code",
    "CM002": "Function too long",
    "CM003": "TODO/FIXME comment",
    "CM004": "File too long",
    "CM005": "Too many function parameters",
    "CM006": "Deeply nested code",
    "CM007": "Duplicate #include",
    "CM008": "Empty destructor",
    "CM009": "Commented-out code block",
    # ── Blueprint Best Practices (BPB) ────────────────────
    "BPB001": "Blueprint missing BP_ prefix",
    "BPB002": "Blueprint with no functions, only EventGraph",
    "BPB003": "Variable with generic name",
    "BPB004": "Missing Super BeginPlay call in Blueprint",
    "BPB005": "Missing Super EndPlay call in Blueprint",
    "BPB006": "Function without tooltip",
    "BPB007": "Variable without Category",
    # ── Blueprint Performance (BPP) ───────────────────────
    "BPP001": "Tick enabled by default",
    "BPP002": "Excessive Cast nodes",
    "BPP003": "Heavy logic in Event Tick",
    "BPP004": "Delay node in Event Tick",
    "BPP005": "GetAllActorsOfClass in Tick (Blueprint)",
    # ── Blueprint Maintainability (BPM) ───────────────────
    "BPM001": "Unused Blueprint variables",
    "BPM002": "Disconnected Blueprint nodes",
    "BPM003": "Blueprint with too many nodes",
    "BPM004": "Function with high complexity",
    "BPM005": "Graph with too many nodes",
    "BPM006": "Blueprint without functions",
    "BPM007": "Abandoned Blueprint",
    # ── Blueprint Security (BPS) ──────────────────────────
    "BPS001": "Missing authority check before action",
    "BPS003": "ExecuteConsoleCommand in shipping code",
    # ── Asset Naming (NM) ─────────────────────────────────
    "NM001": "Asset missing type prefix",
    "NM002": "Asset name contains spaces",
    "NM003": "Asset name contains special characters",
    "NM004": "Asset name starts with lowercase",
    "NM005": "Duplicate asset name across folders",
    "NM006": "Texture missing channel suffix",
    "NM007": "Asset name not PascalCase",
    "NM008": "Asset name too long",
    "NM009": "Asset in wrong folder",
    "NM010": "Asset name has duplicated prefix",
    "NM011": "Asset name starts with a number",
    "NM012": "Asset name has consecutive underscores",
    "NM013": "Asset name ends with underscore",
    "NM014": "Asset name is generic or placeholder",
    "NM015": "Asset name has version suffix",
    "NM016": "Asset has wrong prefix for its type",
    "NM017": "Asset name too short",
    "NM018": "Asset name redundantly repeats type",
    # ── C# / Unity (engine=unity) — first implementation batch ─────────────
    # Full taxonomy reserves 96 IDs: CSP001-CSP016, CSB001-CSB034,
    # CSS001-CSS013, CSM001-CSM008, UN001-UN025. Only the entries below
    # have detectors today; subsequent batches will fill in the rest.
    "UN001":  "GameObject.Find in Update",
    "UN002":  "GetComponent in Update",
    "UN003":  "FindObjectOfType in Update",
    "UN004":  "Debug.Log in Update",
    "UN005":  "SendMessage / BroadcastMessage usage",
    "UN006":  "Public field on MonoBehaviour",
    "UN007":  "Empty Update method",
    "CSB001": "Empty catch block",
    "CSB002": "TODO / FIXME comment",
    "CSS001": "SQL command built by string concatenation",
    "CSS002": "Hard-coded secret in source",
    "CSM001": "Method exceeds 50 lines",
    "CSM002": "File exceeds 500 lines",
    "CSM003": "Class exposes too many public members",
    # ── Batch 2 ──
    "CSP001": "LINQ operator in Update",
    "CSP002": "String concatenation in loop",
    "CSP004": "Instantiate in Update",
    "CSP006": "new WaitForSeconds per yield",
    "CSB003": "Broad catch (Exception) without rethrow or log",
    "CSB005": "async void non-event-handler",
    "CSB006": "Magic number in expression",
    "CSS003": "Hardcoded http:// URL",
    "CSS004": "PlayerPrefs storing credentials",
    "CSM004": "Method has too many parameters",
    "CSM005": "Method nests too deeply",
    "UN008":  "Camera.main in Update",
    "UN012":  "String comparison with .tag instead of CompareTag",
}


# ── Docstring extraction ───────────────────────────────────────────────────

# Strips a leading "BPB001: ", "NM003: ", etc. when present at the start of
# the first paragraph. C++ docstrings don't carry this prefix; BP and Naming
# do. The id is redundant once we pair the docstring with the rule_id.
_RULE_ID_PREFIX_RE = re.compile(r"^[A-Z]+\d+:\s*")


# Phrases that mark a paragraph as internal implementation notes rather
# than customer-facing material. Used by _first_paragraph below to stop
# concatenating once we hit an impl block. Kept conservative — when in
# doubt, prefer keeping the paragraph (the cost of a slightly verbose
# explanation is much lower than the cost of dropping the WHY).
_IMPL_PARAGRAPH_MARKERS: tuple[str, ...] = (
    "Uses asset_type",
    "Uses the real asset_type",
    "Uses folder inference",
    "Detection ",
    "Detection:",
    "Falls back",
    "Skips assets",
    "Requires asset_type",
    "Requires real type",
    "Only checks",
    "Lookback:",
    "Note:",
    "Implementation:",
    "Sprint ",  # "Sprint 4: …" / "Sprint 5: …" follow-up TODOs
)


def _first_paragraph(docstring: Optional[str]) -> str:
    """Return the customer-facing portion of the docstring as a single
    block of text.

    Different rule families spread their customer-facing material
    differently:

      - C++ rules concentrate everything in paragraph 1 (what +
        why + fix). Paragraph 2 is internal notes ("Lookback: …").
      - Blueprint rules typically use a single paragraph (no blank
        lines) so paragraph 1 IS the whole thing.
      - Naming rules use paragraph 1 for the bare definition and
        paragraph 2 for the why/how. Paragraph 3+ is impl.

    To handle all three uniformly, we walk paragraphs in order and
    keep concatenating until we hit one whose first non-empty line
    starts with a known impl-notes marker (see
    _IMPL_PARAGRAPH_MARKERS). Anything before that boundary is
    treated as customer-facing and joined into a single block —
    that's what the LLM and downstream consumers receive in
    `rule_explanation`.

    The leading "NM001: " / "BPB001: " prefix is stripped from the
    first paragraph; downstream code already pairs the explanation
    with its rule_id, so repeating it is just noise.
    """
    if not docstring:
        return ""

    paragraphs_raw = docstring.strip().split("\n\n")

    customer_facing_paragraphs: list[str] = []
    for raw_paragraph in paragraphs_raw:
        # Collapse internal newlines + indentation so each paragraph
        # becomes a single clean line for both the marker check and
        # the final output.
        collapsed = " ".join(
            line.strip() for line in raw_paragraph.splitlines() if line.strip()
        )
        if not collapsed:
            continue

        # Stop as soon as we recognise an impl-notes paragraph.
        if any(collapsed.startswith(marker) for marker in _IMPL_PARAGRAPH_MARKERS):
            break

        customer_facing_paragraphs.append(collapsed)

    if not customer_facing_paragraphs:
        return ""

    # Strip the rule_id prefix from the very first paragraph only.
    customer_facing_paragraphs[0] = _RULE_ID_PREFIX_RE.sub(
        "", customer_facing_paragraphs[0], count=1
    )

    # Join paragraphs with a single space — the LLM only needs a flat
    # block of grounding text, not formatting.
    return " ".join(p for p in customer_facing_paragraphs if p).strip()


def _build_rule_id_to_function() -> Dict[str, Callable[..., Any]]:
    """Map every rule_id to the detector function that emits it.

    Imports are deferred to call time to keep this module cheap to import
    on its own (the cost is paid once, on the first orchestrator run).
    """
    # Blueprint detectors. Note: detect_get_all_actors_in_tick exists in
    # both cpp_performance and blueprint_rules — alias the BP one to
    # avoid the name collision.
    from code_validator.rules.blueprint.blueprint_rules import (
        detect_abandoned_blueprint,
        detect_blueprint_no_functions,
        detect_console_command_usage,
        detect_delay_in_tick,
        detect_disconnected_nodes,
        detect_excessive_casts,
        detect_function_no_tooltip,
        detect_generic_variable_name,
    )
    from code_validator.rules.blueprint.blueprint_rules import (
        detect_get_all_actors_in_tick as bp_detect_get_all_actors_in_tick,
    )
    from code_validator.rules.blueprint.blueprint_rules import (
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
    from code_validator.rules.cpp.cpp_best_practices import (
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
        detect_missing_super_endplay,
        detect_non_virtual_destructor,
        detect_nullptr_deref,
        detect_printf,
        detect_public_member_without_uproperty,
        detect_raw_c_array,
        detect_raw_delete,
        detect_raw_new,
        detect_raw_pointer_in_uproperty,
        detect_runtime_load,
        detect_stl_usage,
        detect_string_concat_in_loop,
        detect_string_literal_no_text_macro,
        detect_system_headers,
        detect_timer_lambda_raw_this,
        detect_ufunction_missing_category,
        detect_uproperty_missing_category,
        detect_uproperty_nullptr,
    )
    from code_validator.rules.cpp.cpp_maintainability import (
        detect_commented_out_code,
        detect_debug_message,
        detect_deep_nesting,
        detect_duplicate_include,
        detect_empty_destructor,
        detect_file_too_long,
        detect_long_function,
        detect_todo_comments,
        detect_too_many_parameters,
    )
    from code_validator.rules.cpp.cpp_performance import (
        detect_empty_tick_override,
        detect_ensure_in_tick,
        detect_find_object_in_tick,
        detect_forceinline_large_function,
        detect_fstring_by_value,
        detect_garbage_collect_call,
    )
    from code_validator.rules.cpp.cpp_performance import (
        detect_get_all_actors_in_tick as cpp_detect_get_all_actors_in_tick,
    )
    from code_validator.rules.cpp.cpp_performance import (
        detect_get_component_in_tick,
        detect_heavy_math_in_tick,
        detect_large_tick,
        detect_log_error_in_tick,
        detect_new_object_in_loop,
        detect_sleep_on_game_thread,
        detect_spawn_actor_in_tick,
        detect_string_ops_in_tick,
        detect_tarray_copy_in_loop,
        detect_tick_enabled_in_constructor,
    )
    from code_validator.rules.cpp.cpp_security import (
        detect_array_no_bounds_check,
        detect_cast_no_check,
        detect_client_rpc_modifies_replicated,
        detect_division_no_zero_check,
        detect_game_instance_no_check,
        detect_getowner_no_check,
        detect_getworld_no_check,
        detect_hardcoded_secret,
        detect_http_insecure,
        detect_overlap_actor_no_check,
        detect_player_controller_no_check,
        detect_player_state_no_check,
        detect_server_rpc_no_validate,
        detect_spawnactor_no_check,
        detect_weak_ptr_no_check,
    )

    # Naming detectors live under the separate `naming` top-level module.
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

    return {
        # C++ Performance
        "CP001": detect_find_object_in_tick,
        "CP002": detect_get_component_in_tick,
        "CP003": detect_large_tick,
        "CP004": detect_log_error_in_tick,
        "CP005": detect_sleep_on_game_thread,
        "CP006": cpp_detect_get_all_actors_in_tick,
        "CP007": detect_tick_enabled_in_constructor,
        "CP008": detect_heavy_math_in_tick,
        "CP009": detect_string_ops_in_tick,
        "CP010": detect_forceinline_large_function,
        "CP011": detect_fstring_by_value,
        "CP012": detect_tarray_copy_in_loop,
        "CP013": detect_new_object_in_loop,
        "CP015": detect_ensure_in_tick,
        "CP016": detect_garbage_collect_call,
        "CP017": detect_empty_tick_override,
        "CP018": detect_spawn_actor_in_tick,
        # C++ Best Practices
        "CB001": detect_infinite_loop,
        "CB002": detect_runtime_load,
        "CB003": detect_raw_new,
        "CB004": detect_raw_delete,
        "CB005": detect_stl_usage,
        "CB006": detect_printf,
        "CB007": detect_system_headers,
        "CB008": detect_float_no_suffix,
        "CB009": detect_uproperty_nullptr,
        "CB010": detect_magic_numbers,
        "CB011": detect_empty_if_body,
        "CB012": detect_c_style_cast,
        "CB013": detect_nullptr_deref,
        "CB014": detect_hardcoded_path,
        "CB015": detect_auto_without_obvious_type,
        "CB016": detect_string_concat_in_loop,
        "CB017": detect_public_member_without_uproperty,
        "CB018": detect_raw_c_array,
        "CB019": detect_non_virtual_destructor,
        "CB020": detect_fstring_as_identifier,
        "CB021": detect_lambda_implicit_capture,
        "CB022": detect_ensure_not_always,
        "CB023": detect_missing_override,
        "CB024": detect_missing_super_beginplay,
        "CB025": detect_ufunction_missing_category,
        "CB026": detect_exposed_on_spawn_no_default,
        "CB028": detect_timer_lambda_raw_this,
        "CB029": detect_log_verbose_shipping,
        "CB030": detect_string_literal_no_text_macro,
        "CB031": detect_blueprint_pure_side_effects,
        "CB032": detect_const_ref_uproperty,
        "CB033": detect_missing_super_endplay,
        "CB034": detect_raw_pointer_in_uproperty,
        "CB035": detect_uproperty_missing_category,
        # C++ Security
        "CS001": detect_getworld_no_check,
        "CS002": detect_spawnactor_no_check,
        "CS003": detect_cast_no_check,
        "CS004": detect_division_no_zero_check,
        "CS005": detect_array_no_bounds_check,
        "CS006": detect_getowner_no_check,
        "CS007": detect_overlap_actor_no_check,
        "CS008": detect_weak_ptr_no_check,
        "CS011": detect_http_insecure,
        "CS012": detect_hardcoded_secret,
        "CS013": detect_player_controller_no_check,
        "CS014": detect_game_instance_no_check,
        "CS015": detect_player_state_no_check,
        "CS016": detect_server_rpc_no_validate,
        "CS017": detect_client_rpc_modifies_replicated,
        # C++ Maintainability
        "CM001": detect_debug_message,
        "CM002": detect_long_function,
        "CM003": detect_todo_comments,
        "CM004": detect_file_too_long,
        "CM005": detect_too_many_parameters,
        "CM006": detect_deep_nesting,
        "CM007": detect_duplicate_include,
        "CM008": detect_empty_destructor,
        "CM009": detect_commented_out_code,
        # Blueprint Best Practices
        "BPB001": detect_missing_bp_prefix,
        "BPB002": detect_no_functions_large_graph,
        "BPB003": detect_generic_variable_name,
        "BPB004": detect_missing_begin_play_super,
        "BPB005": detect_missing_end_play_super,
        "BPB006": detect_function_no_tooltip,
        "BPB007": detect_variable_no_category,
        # Blueprint Performance
        "BPP001": detect_tick_enabled,
        "BPP002": detect_excessive_casts,
        "BPP003": detect_heavy_event_tick,
        "BPP004": detect_delay_in_tick,
        "BPP005": bp_detect_get_all_actors_in_tick,
        # Blueprint Maintainability
        "BPM001": detect_unused_variables,
        "BPM002": detect_disconnected_nodes,
        "BPM003": detect_large_blueprint,
        "BPM004": detect_high_complexity_function,
        "BPM005": detect_large_graph,
        "BPM006": detect_blueprint_no_functions,
        "BPM007": detect_abandoned_blueprint,
        # Blueprint Security
        "BPS001": detect_missing_authority_check,
        "BPS003": detect_console_command_usage,
        # Asset Naming
        "NM001": detect_missing_prefix,
        "NM002": detect_spaces_in_name,
        "NM003": detect_special_chars,
        "NM004": detect_lowercase_names,
        "NM005": detect_duplicate_names,
        "NM006": detect_missing_tex_suffix,
        "NM007": detect_non_pascal_case,
        "NM008": detect_name_too_long,
        "NM009": detect_wrong_folder,
        "NM010": detect_double_prefix,
        "NM011": detect_number_start,
        "NM012": detect_consecutive_underscores,
        "NM013": detect_trailing_underscore,
        "NM014": detect_generic_name,
        "NM015": detect_version_suffix,
        "NM016": detect_wrong_prefix_for_type,
        "NM017": detect_name_too_short,
        "NM018": detect_redundant_type_in_name,
    }


_RULE_EXPLANATIONS_CACHE: Optional[Dict[str, str]] = None


def _get_explanations() -> Dict[str, str]:
    """Lazy-build and cache the rule_id -> explanation map.

    If the imports inside _build_rule_id_to_function() fail (e.g. a
    detector got renamed and the import list is stale), we fall back
    to an empty dict so enrichment becomes a no-op rather than crashing
    every analyser run. The orchestrators still return their issues
    with rule_name only.
    """
    global _RULE_EXPLANATIONS_CACHE
    if _RULE_EXPLANATIONS_CACHE is None:
        try:
            mapping = _build_rule_id_to_function()
            _RULE_EXPLANATIONS_CACHE = {
                rid: _first_paragraph(fn.__doc__) for rid, fn in mapping.items()
            }
        except Exception:
            _RULE_EXPLANATIONS_CACHE = {}
    return _RULE_EXPLANATIONS_CACHE


# ── Public API ─────────────────────────────────────────────────────────────


def enrich_issue(issue: Dict[str, Any]) -> Dict[str, Any]:
    """Add `rule_name` and `rule_explanation` fields to an issue dict.

    Mutates `issue` in place and also returns it so callers can chain.
    Missing rule_ids (e.g. from a future rule that hasn't been mapped
    yet) leave the issue untouched — never raises.
    """
    rule_id = issue.get("rule_id", "")
    if not rule_id:
        return issue

    if rule_id in RULE_NAMES:
        issue["rule_name"] = RULE_NAMES[rule_id]

    explanations = _get_explanations()
    if rule_id in explanations and explanations[rule_id]:
        issue["rule_explanation"] = explanations[rule_id]

    return issue
