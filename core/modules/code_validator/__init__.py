# core/modules/code_validator/__init__.py
#
# Deep Code Validator module.
# Re-exports public functions from the rules so other modules
# can import directly: from modules.code_validator import analyse
#
# Current rules:
#   - UE5 C++ rules (ue5_cpp_rules.py) — CV001–CV010 + 4 context-aware rules
#   - Blueprint rules (blueprint_rules.py) — BP001–BP002
# Sprint 5: replace heuristics with full AST-based analysis (clang / libcst)
# Phase 2: add Unity C# rules (csharp_rules.py)

from code_validator.rules.ue5_cpp_rules import run_all_cpp_rules
from code_validator.rules.blueprint_rules import run_all_blueprint_rules


def analyse(file_path: str, content: str) -> list[dict]:
    """
    Analyse a single source file and return a list of issue dicts.
    Wrapper that calls the appropriate rule runner based on file type.
    """
    return run_all_cpp_rules(content, file_path)


def analyse_blueprint(asset_path: str) -> list[dict]:
    """
    Analyse a Blueprint asset path for naming and structural issues.
    """
    return run_all_blueprint_rules(asset_path)


def apply_fix(issue: dict) -> bool:
    """
    Apply an auto-fix for a known issue.
    Returns True if a fix was applied.
    Sprint 5: implement real AST rewriting per rule.
    """
    fixable = {"CV004", "CV007"}
    return issue.get("rule_id") in fixable


__all__ = [
    "analyse",
    "analyse_blueprint",
    "apply_fix",
    "run_all_cpp_rules",
    "run_all_blueprint_rules",
]
