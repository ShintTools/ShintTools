# core/modules/naming/rules/ue5_naming_rules.py
#
# UE5 Asset Naming Rules.
# Detects naming convention violations from asset paths.
#
# Sprint 4: replace type inference with real AssetRegistry class lookups.
# Current: pure Python, no I/O, folder-based type inference.

import re
from pathlib import Path
from typing import Dict, List

# Type alias for issue dictionary
Issue = Dict


# NAMING RULES — folder-to-prefix mapping
#
# Each rule maps a folder name (lowercase) to the required prefix
# and human-readable asset type. If an asset lives inside a matching
# folder but its filename doesn't start with the correct prefix,
# it's flagged as a violation.

_ASSET_RULES: List[Dict] = [
    # Textures
    {"folder": "textures",      "prefix": "T_",    "type": "Texture2D"},
    {"folder": "texture",       "prefix": "T_",    "type": "Texture2D"},

    # Static Meshes
    {"folder": "staticmeshes",  "prefix": "SM_",   "type": "StaticMesh"},
    {"folder": "staticmesh",    "prefix": "SM_",   "type": "StaticMesh"},
    {"folder": "meshes",        "prefix": "SM_",   "type": "StaticMesh"},

    # Skeletal Meshes
    {"folder": "skeletalmesh",  "prefix": "SK_",   "type": "SkeletalMesh"},
    {"folder": "characters",    "prefix": "SK_",   "type": "SkeletalMesh"},

    # Materials
    {"folder": "materials",     "prefix": "M_",    "type": "Material"},
    {"folder": "material",      "prefix": "M_",    "type": "Material"},

    # Blueprints
    {"folder": "blueprints",    "prefix": "BP_",   "type": "Blueprint"},
    {"folder": "blueprint",     "prefix": "BP_",   "type": "Blueprint"},

    # Sounds
    {"folder": "sounds",        "prefix": "SFX_",  "type": "SoundCue"},
    {"folder": "sound",         "prefix": "SFX_",  "type": "SoundCue"},

    # Particles
    {"folder": "particles",     "prefix": "P_",    "type": "ParticleSystem"},
    {"folder": "particle",      "prefix": "P_",    "type": "ParticleSystem"},

    # Animations
    {"folder": "animations",    "prefix": "A_",    "type": "AnimSequence"},
    {"folder": "animation",     "prefix": "A_",    "type": "AnimSequence"},

    # Widgets
    {"folder": "widgets",       "prefix": "WBP_",  "type": "WidgetBlueprint"},
    {"folder": "ui",            "prefix": "WBP_",  "type": "WidgetBlueprint"},

    # DataTables
    {"folder": "datatables",    "prefix": "DT_",   "type": "DataTable"},
    {"folder": "datatable",     "prefix": "DT_",   "type": "DataTable"},

    # DataAssets
    {"folder": "dataassets",    "prefix": "DA_",   "type": "DataAsset"},
]

# VALID PREFIXES — any asset using one of these is considered conformant

_VALID_PREFIXES = {
    "T_", "SM_", "SK_", "M_", "MI_", "BP_", "SFX_", "S_",
    "P_", "NS_", "A_", "ABP_", "WBP_", "DT_", "DA_", "FX_",
    "PC_", "GI_", "GM_", "LV_",
}

# HELPER FUNCTIONS


def _infer_rule(path_lower: str) -> Dict | None:
    """
    Return the first matching naming rule for a given asset path.
    Matches by checking if the path contains a known folder name.
    Example: '/Content/Textures/HeroSword' matches the 'textures' rule.
    """
    for rule in _ASSET_RULES:
        if f"/{rule['folder']}/" in path_lower or path_lower.startswith(rule["folder"] + "/"):
            return rule
    return None


def _has_valid_prefix(stem: str) -> bool:
    """
    Check if the asset filename already starts with a valid prefix.
    If it does, we skip it — no violation.
    """
    return any(stem.startswith(p) for p in _VALID_PREFIXES)


def _suggest_name(stem: str, prefix: str) -> str:
    """
    Generate the suggested corrected name.
    Strips any existing incorrect short prefix (e.g. 'tex_Hero' → 'Hero')
    and prepends the correct one (e.g. 'T_Hero').
    """
    clean = re.sub(r'^[a-zA-Z]{1,4}_', '', stem) if '_' in stem[:5] else stem
    return f"{prefix}{clean}"


# SCANNER — main entry point


def scan_asset_paths(asset_paths: List[str]) -> List[Issue]:
    """
    Scan a list of relative asset paths and return naming issues.
    Optimized for speed: pure Python, no I/O, < 10 s for 50k assets.

    For each asset path:
      1. If the filename already has a valid prefix → skip
      2. Try to infer the expected type from the folder name
      3. If folder is known → flag with specific suggestion
      4. If folder is unknown → flag as generic missing prefix
    """
    issues: List[Issue] = []

    for path in asset_paths:
        p      = Path(path)
        stem   = p.stem
        path_l = path.lower().replace("\\", "/")

        # Already valid — skip immediately
        if _has_valid_prefix(stem):
            continue

        rule = _infer_rule(path_l)
        if rule is None:
            # Unknown folder — flag as generic missing prefix
            issues.append({
                "asset_path":     path,
                "current_name":   stem,
                "suggested_name": stem,   # no suggestion possible without type info
                "reason":         "Asset name has no recognised UE5 naming prefix.",
                "asset_type":     "Unknown",
            })
            continue

        # Known folder — suggest the correct prefix
        issues.append({
            "asset_path":     path,
            "current_name":   stem,
            "suggested_name": _suggest_name(stem, rule["prefix"]),
            "reason":         f"Missing prefix '{rule['prefix']}' for {rule['type']}.",
            "asset_type":     rule["type"],
        })

    return issues


# RENAME STUB


def apply_asset_rename(asset_path: str, new_name: str) -> bool:
    """
    Rename an asset.
    Sprint 4: implement via UE Python bindings (unreal.AssetTools.rename_assets).
    Currently a stub that always returns True (rename acknowledged, not executed).
    """
    # TODO Sprint 4: call unreal.AssetTools.rename_assets([...])
    return True