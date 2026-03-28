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
    {"folder": "textures", "prefix": "T_", "type": "Texture2D"},
    {"folder": "texture", "prefix": "T_", "type": "Texture2D"},
    # Static Meshes
    {"folder": "staticmeshes", "prefix": "SM_", "type": "StaticMesh"},
    {"folder": "staticmesh", "prefix": "SM_", "type": "StaticMesh"},
    {"folder": "meshes", "prefix": "SM_", "type": "StaticMesh"},
    # Skeletal Meshes
    {"folder": "skeletalmesh", "prefix": "SK_", "type": "SkeletalMesh"},
    {"folder": "characters", "prefix": "SK_", "type": "SkeletalMesh"},
    # Materials
    {"folder": "materials", "prefix": "M_", "type": "Material"},
    {"folder": "material", "prefix": "M_", "type": "Material"},
    # Blueprints
    {"folder": "blueprints", "prefix": "BP_", "type": "Blueprint"},
    {"folder": "blueprint", "prefix": "BP_", "type": "Blueprint"},
    # Sounds
    {"folder": "sounds", "prefix": "SFX_", "type": "SoundCue"},
    {"folder": "sound", "prefix": "SFX_", "type": "SoundCue"},
    # Particles
    {"folder": "particles", "prefix": "P_", "type": "ParticleSystem"},
    {"folder": "particle", "prefix": "P_", "type": "ParticleSystem"},
    # Animations
    {"folder": "animations", "prefix": "A_", "type": "AnimSequence"},
    {"folder": "animation", "prefix": "A_", "type": "AnimSequence"},
    # Widgets
    {"folder": "widgets", "prefix": "WBP_", "type": "WidgetBlueprint"},
    {"folder": "ui", "prefix": "WBP_", "type": "WidgetBlueprint"},
    # DataTables
    {"folder": "datatables", "prefix": "DT_", "type": "DataTable"},
    {"folder": "datatable", "prefix": "DT_", "type": "DataTable"},
    # DataAssets
    {"folder": "dataassets", "prefix": "DA_", "type": "DataAsset"},
]

# VALID PREFIXES — any asset using one of these is considered conformant

_VALID_PREFIXES = {
    "T_",
    "SM_",
    "SK_",
    "M_",
    "MI_",
    "BP_",
    "SFX_",
    "S_",
    "P_",
    "NS_",
    "A_",
    "ABP_",
    "WBP_",
    "DT_",
    "DA_",
    "FX_",
    "PC_",
    "GI_",
    "GM_",
    "LV_",
}


# HELPER FUNCTIONS


def _infer_rule(path_lower: str) -> Dict | None:
    """
    Return the first matching naming rule for a given asset path.
    Matches by checking if the path contains a known folder name.
    Example: '/Content/Textures/HeroSword' matches the 'textures' rule.
    """
    for naming_rule in _ASSET_RULES:
        folder_segment = f"/{naming_rule['folder']}/"
        folder_prefix = naming_rule["folder"] + "/"
        if folder_segment in path_lower or path_lower.startswith(folder_prefix):
            return naming_rule
    return None


def _has_valid_prefix(asset_name: str) -> bool:
    """
    Check if the asset filename already starts with a valid prefix.
    If it does, we skip it — no violation.
    """
    return any(asset_name.startswith(prefix) for prefix in _VALID_PREFIXES)


def _suggest_name(asset_name: str, correct_prefix: str) -> str:
    """
    Generate the suggested corrected name.
    Strips any existing incorrect short prefix (e.g. 'tex_Hero' → 'Hero')
    and prepends the correct one (e.g. 'T_Hero').
    """
    clean_name = (
        re.sub(r"^[a-zA-Z]{1,4}_", "", asset_name)
        if "_" in asset_name[:5]
        else asset_name
    )
    return f"{correct_prefix}{clean_name}"


def _has_spaces_in_name(asset_name: str) -> bool:
    """
    Returns True if the asset name contains spaces.
    Spaces in asset names break code references and
    cause issues in source control and build pipelines.
    """
    return " " in asset_name


def _has_special_chars(asset_name: str) -> bool:
    """
    Returns True if the asset name contains characters
    other than letters, numbers and underscores.
    Special characters break UE5 asset references and
    cause errors in build pipelines.
    """
    return bool(re.search(r"[^a-zA-Z0-9_]", asset_name))


def _starts_with_lowercase(asset_name: str) -> bool:
    """
    Returns True if the asset name starts with a lowercase letter.
    UE5 assets must use PascalCase or a valid uppercase prefix.
    """
    return bool(asset_name) and asset_name[0].islower()


# DETECTION FUNCTIONS


def detect_missing_prefix(asset_paths: List[str]) -> List[Issue]:
    """
    Detects assets missing a valid UE5 naming prefix.
    Checks folder name to infer the expected prefix and
    suggests the corrected name when possible.
    """
    issues: List[Issue] = []

    for path in asset_paths:
        asset_path_obj = Path(path)
        asset_name = asset_path_obj.stem
        path_lower = path.lower().replace("\\", "/")

        if _has_valid_prefix(asset_name):
            continue

        naming_rule = _infer_rule(path_lower)
        if naming_rule is None:
            issues.append(
                {
                    "asset_path": path,
                    "current_name": asset_name,
                    "suggested_name": asset_name,
                    "reason": "Asset name has no recognised UE5 naming prefix.",
                    "asset_type": "Unknown",
                }
            )
            continue

        issues.append(
            {
                "asset_path": path,
                "current_name": asset_name,
                "suggested_name": _suggest_name(asset_name, naming_rule["prefix"]),
                "reason": (
                    f"Missing prefix '{naming_rule['prefix']}' "
                    f"for {naming_rule['type']}."
                ),
                "asset_type": naming_rule["type"],
            }
        )

    return issues


def detect_spaces_in_name(asset_paths: List[str]) -> List[Issue]:
    """
    Detects asset names that contain spaces.
    UE5 assets must use underscores instead of spaces.
    Example: 'Hero Sword' should be 'Hero_Sword'.
    """
    issues: List[Issue] = []

    for path in asset_paths:
        asset_path_obj = Path(path)
        asset_name = asset_path_obj.stem

        if _has_spaces_in_name(asset_name):
            suggested_name = asset_name.replace(" ", "_")
            issues.append(
                {
                    "asset_path": path,
                    "current_name": asset_name,
                    "suggested_name": suggested_name,
                    "reason": (
                        "Asset name contains spaces — "
                        "use underscores instead (e.g. 'Hero_Sword')."
                    ),
                    "asset_type": "Unknown",
                }
            )

    return issues


def detect_special_chars(asset_paths: List[str]) -> List[Issue]:
    """
    Detects asset names that contain special characters.
    Only letters, numbers and underscores are allowed in
    UE5 asset names.
    Example: 'Hero-Sword' should be 'Hero_Sword'.
    """
    issues: List[Issue] = []

    for path in asset_paths:
        asset_path_obj = Path(path)
        asset_name = asset_path_obj.stem

        if _has_special_chars(asset_name):
            suggested_name = re.sub(r"[^a-zA-Z0-9_]", "_", asset_name)
            issues.append(
                {
                    "asset_path": path,
                    "current_name": asset_name,
                    "suggested_name": suggested_name,
                    "reason": (
                        "Asset name contains special characters — "
                        "only letters, numbers and underscores are allowed."
                    ),
                    "asset_type": "Unknown",
                }
            )

    return issues


def detect_lowercase_names(asset_paths: List[str]) -> List[Issue]:
    """
    Detects asset names that start with a lowercase letter.
    UE5 naming convention requires PascalCase or a valid
    prefix (e.g. T_, SM_, BP_) — never lowercase first letter.
    Example: 'heroSword' should be 'T_HeroSword'.
    """
    issues: List[Issue] = []

    for path in asset_paths:
        asset_path_obj = Path(path)
        asset_name = asset_path_obj.stem

        if _starts_with_lowercase(asset_name):
            suggested_name = asset_name[0].upper() + asset_name[1:]
            issues.append(
                {
                    "asset_path": path,
                    "current_name": asset_name,
                    "suggested_name": suggested_name,
                    "reason": (
                        "Asset name starts with lowercase — "
                        "use PascalCase or a valid prefix (e.g. T_HeroSword)."
                    ),
                    "asset_type": "Unknown",
                }
            )

    return issues


def detect_duplicate_names(asset_paths: List[str]) -> List[Issue]:
    """
    Detects assets that share the same name across different folders.
    Duplicate names cause confusion when referencing assets in code
    and can lead to loading the wrong asset at runtime.
    Rename one of them to make each asset name unique.
    """
    issues: List[Issue] = []

    # Build a map of asset_name -> list of paths that share that name
    name_to_paths: Dict[str, List[str]] = {}
    for path in asset_paths:
        asset_name = Path(path).stem
        if asset_name not in name_to_paths:
            name_to_paths[asset_name] = []
        name_to_paths[asset_name].append(path)

    # Flag any name that appears in more than one path
    for asset_name, paths_with_name in name_to_paths.items():
        if len(paths_with_name) > 1:
            duplicate_list = ", ".join(paths_with_name)
            for duplicate_path in paths_with_name:
                issues.append(
                    {
                        "asset_path": duplicate_path,
                        "current_name": asset_name,
                        "suggested_name": asset_name,
                        "reason": (
                            f"Duplicate asset name '{asset_name}' found in "
                            f"multiple folders: {duplicate_list}"
                        ),
                        "asset_type": "Unknown",
                    }
                )

    return issues


# RUNNER — main entry point


def scan_asset_paths(asset_paths: List[str]) -> List[Issue]:
    """
    Runs all naming rules against the given asset paths
    and returns a merged list of issues.

    Rules: missing prefix, spaces, special chars,
           lowercase names, duplicate names
    """
    issues: List[Issue] = []

    issues += detect_missing_prefix(asset_paths)
    issues += detect_spaces_in_name(asset_paths)
    issues += detect_special_chars(asset_paths)
    issues += detect_lowercase_names(asset_paths)
    issues += detect_duplicate_names(asset_paths)

    return issues


# RENAME STUB


def apply_asset_rename(asset_path: str, new_name: str) -> bool:
    """
    Rename an asset.
    Sprint 4: implement via UE Python bindings.
    Currently a stub that always returns True.
    """
    # TODO Sprint 4: call unreal.AssetTools.rename_assets([...])
    return True
