# core/modules/naming/__init__.py
#
# Asset Naming Bot module.
# Re-exports public functions from the rules so other modules
# can import directly: from modules.naming import scan_asset_paths
#
# Current rules: UE5 naming conventions (ue5_naming_rules.py)
# Phase 2: add Unity naming rules

from modules.naming.rules.ue5_naming_rules import (
    scan_asset_paths,
    apply_asset_rename,
)

__all__ = [
    "scan_asset_paths",
    "apply_asset_rename",
]
