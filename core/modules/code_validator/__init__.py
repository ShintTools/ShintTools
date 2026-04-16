# core/modules/code_validator/__init__.py
#
# Deep Code Validator module.
# Re-exports public functions from the rules so other modules
# can import directly: from modules.code_validator import analyse
#
# Current rules:
#   UE5 C++ rules (ue5_cpp_rules.py)
#     Performance:      CP001-CP004
#     Best Practices:   CB001-CB009
#     Security:         CS001-CS003
#     Maintainability:  CM001-CM003
#   Blueprint rules (blueprint_rules.py)
#     Best Practices:   BPB001
#     Performance:      BPP001-BPP002
#     Maintainability:  BPM001-BPM005
# Phase 2: add Unity C# rules (csharp_rules.py)

from code_validator.rules.blueprint_rules import (
    run_all_blueprint_rules,
    run_all_blueprint_rules_from_export,
)
from code_validator.rules.cpp.ue5_cpp_rules import run_all_cpp_rules


def analyse(file_path: str, content: str) -> list[dict]:
    """
    Analyse a single source file and return issues.
    Calls the appropriate rule runner based on file type.
    """
    return run_all_cpp_rules(content, file_path)


def analyse_blueprint(blueprint: dict) -> list[dict]:
    """
    Analyse a Blueprint asset dict exported by the UE5 plugin.
    Receives the full blueprint dict with graphs, variables,
    functions and stats — not just the asset path.
    """
    return run_all_blueprint_rules(blueprint)


def apply_fix(issue: dict) -> bool:
    """
    Apply an auto-fix for a known issue.
    Returns True if a fix was applied.
    Sprint 5: implement real AST rewriting per rule.
    CB006 = printf, MT001 = GEngine debug message.
    """
    fixable = {"CB006", "MT001"}
    return issue.get("rule_id") in fixable


__all__ = [
    "analyse",
    "analyse_blueprint",
    "apply_fix",
    "run_all_cpp_rules",
    "run_all_blueprint_rules",
    "run_all_blueprint_rules_from_export",
]
