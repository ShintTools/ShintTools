# core/modules/naming/__init__.py
#
# Asset Naming Bot module.
# Re-exports public functions from the rules so other modules
# can import directly: from modules.naming import scan_asset_paths
#
# Current rules: UE5 naming conventions (ue5_naming_rules.py)
# Phase 2: add Unity naming rules

from naming.rules import run_all_naming_rules
from naming.rules.ue5_naming_rules import apply_asset_rename, scan_asset_paths

__all__ = [
    "scan_asset_paths",
    "apply_asset_rename",
    "run_all_naming_rules",
]
