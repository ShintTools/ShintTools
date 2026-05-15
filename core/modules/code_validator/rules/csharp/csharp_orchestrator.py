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
# This file currently registers 27 detectors (batches 1 + 2). Reserved
# IDs without an implementation yet are still legal in tiers.py so the
# free / indie filter stays stable across rule batches.

from typing import Dict, List

from code_validator.rules.csharp.csharp_rules import (
    # Batch 1
    detect_csb001_empty_catch,
    detect_csb002_todo_comment,
    detect_csm001_long_method,
    detect_csm002_long_file,
    detect_csm003_class_god_object,
    detect_css001_sql_concat,
    detect_css002_hardcoded_secret,
    detect_un001_findobject_in_update,
    detect_un002_getcomponent_in_update,
    detect_un003_findobjectoftype_in_update,
    detect_un004_log_in_update,
    detect_un005_sendmessage_use,
    detect_un006_public_field_monobehaviour,
    detect_un007_empty_update,
    # Batch 2
    detect_csb003_catch_exception_broad,
    detect_csb005_async_void,
    detect_csb006_magic_number,
    detect_csm004_too_many_params,
    detect_csm005_deep_nesting,
    detect_csp001_linq_in_update,
    detect_csp002_string_concat_in_loop,
    detect_csp004_instantiate_in_update,
    detect_csp006_new_waitforseconds,
    detect_css003_http_url,
    detect_css004_playerprefs_secret,
    detect_un008_camera_main_in_update,
    detect_un012_tag_string_compare,
)

Issue = Dict


def run_all_csharp_rules(
    content: str,
    file_path: str,
) -> List[Issue]:
    """Run all implemented C# / Unity rules against a .cs source file.

    Currently covers 27 of the 96 reserved IDs (batches 1 + 2). The
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

    return issues
