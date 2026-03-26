# core/modules/code_validator/rules/blueprint_rules.py
#
# Deterministic Blueprint rules for Unreal Engine 5.
# Each rule is a function that receives an asset_path
# and returns a list of issue dicts.
#
# These rules analyse the asset path only (name + folder).
# Sprint 5: replace with full Blueprint bytecode analysis
# using UHT reflection data.
 
from pathlib import Path
from typing import Dict, List
 
# Type alias for issue dictionary
Issue = Dict
 
 
# BLUEPRINT NAMING & STRUCTURE RULES (BP001–BP002)
 
 
# BP001: Blueprint missing BP_ prefix
def detect_missing_bp_prefix(asset_path: str) -> List[Issue]:
    """
    Checks that Blueprint assets use the BP_ prefix.
    UE5 convention requires all Blueprint assets to start
    with BP_ so they're easily identifiable in the Content
    Browser and avoid confusion with C++ classes.
    """
    issues = []
    stem = Path(asset_path).stem
 
    if not stem.startswith("BP_"):
        issues.append({
            "asset_path": asset_path,
            "severity": "warning",
            "rule_id": "BP001",
            "message": "Blueprint asset does not use BP_ prefix.",
            "line": 0,
        })
    return issues
 
 
# BP002: Test Blueprint outside /Tests/ directory
def detect_test_bp_outside_tests(asset_path: str) -> List[Issue]:
    """
    Detects Blueprint assets with 'test' in their name
    that are NOT inside a /Tests/ directory.
    Test assets should be isolated in /Tests/ folders
    so they can be excluded from shipping builds easily.
    """
    issues = []
    path_lower = asset_path.lower()
 
    if "test" in path_lower and "/tests/" not in path_lower:
        issues.append({
            "asset_path": asset_path,
            "severity": "warning",
            "rule_id": "BP002",
            "message": "Test Blueprint outside a /Tests/ directory.",
            "line": 0,
        })
    return issues
 
 
# RUNNER — executes ALL Blueprint rules
 
 
def run_all_blueprint_rules(asset_path: str) -> List[Issue]:
    """
    Runs all deterministic Blueprint rules against the given
    asset path and returns a merged list of issues.
 
    Current rules (2):
        BP001 — missing BP_ prefix
        BP002 — test Blueprint outside /Tests/
    """
    issues = []
    issues += detect_missing_bp_prefix(asset_path)
    issues += detect_test_bp_outside_tests(asset_path)
    return issues