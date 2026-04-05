# core/modules/naming/rules/ue5_naming_rules.py
#
# UE5 Asset Naming Rules — ShintTools Naming Validator
#
# Detects naming convention violations from asset paths.
# All rules return severity "warning", category "Best Practices".
#
# Each rule receives List[AssetRecord] where AssetRecord is:
#   { "asset_path": str, "asset_type": str }
# asset_type comes from UE5 AssetRegistry via the plugin.
# Falls back to folder inference when asset_type is empty or Unknown.
#
# Rule index:
#   NM001 — detect_missing_prefix         : asset lacks required type prefix
#   NM002 — detect_spaces_in_name         : name contains whitespace
#   NM003 — detect_special_chars          : name contains illegal characters
#   NM004 — detect_lowercase_names        : name starts with lowercase letter
#   NM005 — detect_duplicate_names        : same base name in multiple folders
#   NM006 — detect_missing_tex_suffix     : Texture2D missing channel suffix
#   NM007 — detect_non_pascal_case        : name not PascalCase after prefix
#   NM008 — detect_name_too_long          : name exceeds max length (64 chars)
#   NM009 — detect_wrong_folder           : asset type does not match folder
#   NM010 — detect_double_prefix          : duplicated prefix (T_T_Hero)
#   NM011 — detect_number_start           : name starts with a digit
#   NM012 — detect_consecutive_underscores: double underscore in name
#   NM013 — detect_trailing_underscore    : name ends with underscore
#   NM014 — detect_generic_name           : placeholder or generic name
#   NM015 — detect_version_suffix         : version suffix (_v2, _old)

import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

# Type aliases

Issue = Dict[str, Any]
AssetRecord = Dict[str, str]

# ---------------------------------------------------------------------------
# TYPE_TO_EXPECTED_FOLDER
#
# Maps UE5 asset class name → expected folder segment (lowercase).
# Used by NM009 to detect assets in the wrong folder.
# Only includes types where the convention is unambiguous.
# ---------------------------------------------------------------------------

_TYPE_TO_EXPECTED_FOLDER: Dict[str, str] = {
    "Texture2D": "textures",
    "RenderTarget": "rendertargets",
    "TextureCube": "cubemaps",
    "StaticMesh": "meshes",
    "SkeletalMesh": "characters",
    "Material": "materials",
    "MaterialInstance": "materialinstances",
    "MaterialInstanceConstant": "materialinstances",
    "MaterialFunction": "materialfunctions",
    "Blueprint": "blueprints",
    "AnimBlueprint": "animblueprints",
    "WidgetBlueprint": "widgets",
    "SoundCue": "sounds",
    "SoundWave": "audio",
    "AnimSequence": "animations",
    "AnimMontage": "montages",
    "BlendSpace": "blendspaces",
    "PhysicsAsset": "physics",
    "ParticleSystem": "particles",
    "NiagaraSystem": "vfx",
    "DataTable": "datatables",
    "DataAsset": "dataassets",
    "CurveFloat": "curves",
    "UserDefinedEnum": "enums",
    "UserDefinedStruct": "structs",
    "LevelSequence": "sequences",
}

# ---------------------------------------------------------------------------
# Rule metadata
# ---------------------------------------------------------------------------

_NM_SEVERITY: str = "warning"
_NM_CATEGORY: str = "Best Practices"

# ---------------------------------------------------------------------------
# FOLDER_RULES
#
# Each entry maps a folder name segment (lowercase) to the required
# prefix and UE5 asset class name.
# Evaluated in order — first match wins.
#
# Dashboard category grouping (for Raúl's filter UI, to confirm):
#   Textures   : Texture2D, RenderTarget, TextureCube
#   Meshes     : StaticMesh, SkeletalMesh
#   Materials  : Material, MaterialInstance, MaterialFunction,
#                MaterialParameterCollection
#   Blueprints : Blueprint, AnimBlueprint, BlueprintInterface,
#                BlueprintMacroLibrary
#   UI         : WidgetBlueprint
#   Audio      : SoundWave, SoundCue, SoundClass, SoundMix,
#                SoundAttenuation
#   Animations : AnimSequence, AnimMontage, BlendSpace,
#                BlendSpace1D, AimOffsetBlendSpace
#   Physics    : PhysicsAsset, PhysicalMaterial
#   VFX        : ParticleSystem, NiagaraSystem, NiagaraEmitter
#   Data       : DataTable, DataAsset, CurveFloat, CurveVector,
#                CurveLinearColor
#   Misc       : UserDefinedEnum, UserDefinedStruct, LevelSequence
# ---------------------------------------------------------------------------

_FOLDER_RULES: List[Dict[str, str]] = [
    # Textures
    {"folder": "textures", "prefix": "T_", "type": "Texture2D"},
    {"folder": "texture", "prefix": "T_", "type": "Texture2D"},
    {"folder": "rendertargets", "prefix": "RT_", "type": "RenderTarget"},
    {"folder": "cubemaps", "prefix": "TC_", "type": "TextureCube"},
    # Meshes
    {"folder": "staticmeshes", "prefix": "SM_", "type": "StaticMesh"},
    {"folder": "staticmesh", "prefix": "SM_", "type": "StaticMesh"},
    {"folder": "meshes", "prefix": "SM_", "type": "StaticMesh"},
    {"folder": "skeletalmesh", "prefix": "SK_", "type": "SkeletalMesh"},
    {"folder": "characters", "prefix": "SK_", "type": "SkeletalMesh"},
    # Materials
    {"folder": "materials", "prefix": "M_", "type": "Material"},
    {"folder": "material", "prefix": "M_", "type": "Material"},
    {
        "folder": "materialinstances",
        "prefix": "MI_",
        "type": "MaterialInstance",
    },
    {"folder": "matinst", "prefix": "MI_", "type": "MaterialInstance"},
    {
        "folder": "materialfunctions",
        "prefix": "MF_",
        "type": "MaterialFunction",
    },
    # Blueprints
    {"folder": "blueprints", "prefix": "BP_", "type": "Blueprint"},
    {"folder": "blueprint", "prefix": "BP_", "type": "Blueprint"},
    {
        "folder": "animblueprints",
        "prefix": "ABP_",
        "type": "AnimBlueprint",
    },
    {"folder": "abp", "prefix": "ABP_", "type": "AnimBlueprint"},
    # UI / Widgets
    {"folder": "widgets", "prefix": "WBP_", "type": "WidgetBlueprint"},
    {"folder": "ui", "prefix": "WBP_", "type": "WidgetBlueprint"},
    {"folder": "hud", "prefix": "WBP_", "type": "WidgetBlueprint"},
    # Audio
    {"folder": "sounds", "prefix": "SC_", "type": "SoundCue"},
    {"folder": "sound", "prefix": "SC_", "type": "SoundCue"},
    {"folder": "audio", "prefix": "SW_", "type": "SoundWave"},
    {"folder": "soundwaves", "prefix": "SW_", "type": "SoundWave"},
    {"folder": "music", "prefix": "SW_", "type": "SoundWave"},
    # Animations
    {"folder": "animations", "prefix": "AS_", "type": "AnimSequence"},
    {"folder": "animation", "prefix": "AS_", "type": "AnimSequence"},
    {"folder": "anim", "prefix": "AS_", "type": "AnimSequence"},
    {"folder": "montages", "prefix": "AM_", "type": "AnimMontage"},
    {"folder": "blendspaces", "prefix": "BS_", "type": "BlendSpace"},
    # Physics
    {"folder": "physics", "prefix": "PA_", "type": "PhysicsAsset"},
    {
        "folder": "physicsmaterials",
        "prefix": "PM_",
        "type": "PhysicalMaterial",
    },
    # VFX / Particles
    {"folder": "particles", "prefix": "PS_", "type": "ParticleSystem"},
    {"folder": "particle", "prefix": "PS_", "type": "ParticleSystem"},
    {"folder": "vfx", "prefix": "NS_", "type": "NiagaraSystem"},
    {"folder": "niagara", "prefix": "NS_", "type": "NiagaraSystem"},
    {"folder": "effects", "prefix": "NS_", "type": "NiagaraSystem"},
    # Data
    {"folder": "datatables", "prefix": "DT_", "type": "DataTable"},
    {"folder": "datatable", "prefix": "DT_", "type": "DataTable"},
    {"folder": "dataassets", "prefix": "DA_", "type": "DataAsset"},
    {"folder": "dataasset", "prefix": "DA_", "type": "DataAsset"},
    {"folder": "curves", "prefix": "CF_", "type": "CurveFloat"},
    # Misc
    {"folder": "enums", "prefix": "E_", "type": "UserDefinedEnum"},
    {"folder": "structs", "prefix": "F_", "type": "UserDefinedStruct"},
    {"folder": "sequences", "prefix": "LS_", "type": "LevelSequence"},
]

# All valid prefixes — any asset already using one of these is conformant.
_ALL_VALID_PREFIXES: frozenset = frozenset(rule["prefix"] for rule in _FOLDER_RULES)

# Regex: characters that are NOT valid in a UE5 asset name.
_ILLEGAL_CHAR_PATTERN: re.Pattern = re.compile(r"[^A-Za-z0-9_]")

# Regex: strips short incorrect prefix before applying the correct one.
# Example: "tex_HeroSword" → strip "tex_" → suggest "T_HeroSword"
_SHORT_PREFIX_PATTERN: re.Pattern = re.compile(r"^[a-zA-Z]{1,4}_")


# Shared helpers


def _build_issue(
    *,
    rule_id: str,
    asset_path: str,
    current_name: str,
    suggested_name: str,
    asset_type: str,
    message: str,
) -> Issue:
    """Return a fully-populated naming issue dict."""
    return {
        "asset_path": asset_path,
        "current_name": current_name,
        "suggested_name": suggested_name,
        "severity": _NM_SEVERITY,
        "rule_id": rule_id,
        "category": _NM_CATEGORY,
        "asset_type": asset_type,
        "message": message,
    }


def _infer_folder_rule(
    normalised_path: str,
) -> Optional[Dict[str, str]]:
    """Return the first matching folder rule for the given path.

    Receives a lowercase, forward-slash normalised path string.
    Matches by checking if the path contains a known folder segment.
    Example: '/content/textures/herosword' matches 'textures'.
    Sprint 4: replace with AssetRegistry class lookups.
    """
    for folder_rule in _FOLDER_RULES:
        folder_segment = f"/{folder_rule['folder']}/"
        folder_start = folder_rule["folder"] + "/"
        if folder_segment in normalised_path or normalised_path.startswith(
            folder_start
        ):
            return folder_rule
    return None


def _has_valid_prefix(asset_name: str) -> bool:
    """Return True if asset_name already starts with a valid prefix."""
    return any(asset_name.startswith(prefix) for prefix in _ALL_VALID_PREFIXES)


def _suggest_prefixed_name(
    asset_name: str,
    correct_prefix: str,
) -> str:
    """Return the suggested corrected name with the correct prefix.

    Strips any existing short incorrect prefix before prepending the
    correct one. Example: 'tex_HeroSword' → 'T_HeroSword'.
    """
    if "_" in asset_name[:5]:
        stripped_name = _SHORT_PREFIX_PATTERN.sub("", asset_name)
    else:
        stripped_name = asset_name
    return f"{correct_prefix}{stripped_name}"


# NM001 — detect_missing_prefix


def detect_missing_prefix(asset_records: List[AssetRecord]) -> List[Issue]:
    """NM001: flag assets that lack a valid UE5 type prefix.

    Uses asset_type from AssetRegistry when available, otherwise
    infers from folder name. Assets in unrecognised folders are
    flagged with type 'Unknown'.
    """
    issues: List[Issue] = []

    for record in asset_records:
        asset_path = record.get("asset_path", "")
        asset_type = record.get("asset_type", "Unknown") or "Unknown"
        asset_name = Path(asset_path).stem
        normalised_path = asset_path.lower().replace("\\", "/")

        if _has_valid_prefix(asset_name):
            continue

        # Use real asset_type if available, else infer from folder
        folder_rule = _infer_folder_rule(normalised_path)
        resolved_type = (
            asset_type
            if asset_type != "Unknown"
            else (folder_rule["type"] if folder_rule else "Unknown")
        )
        required_prefix = next(
            (rule["prefix"] for rule in _FOLDER_RULES if rule["type"] == resolved_type),
            folder_rule["prefix"] if folder_rule else None,
        )

        if required_prefix is None:
            issues.append(
                _build_issue(
                    rule_id="NM001",
                    asset_path=asset_path,
                    current_name=asset_name,
                    suggested_name=asset_name,
                    asset_type=resolved_type,
                    message=("Asset name has no recognised UE5 naming prefix."),
                )
            )
            continue

        issues.append(
            _build_issue(
                rule_id="NM001",
                asset_path=asset_path,
                current_name=asset_name,
                suggested_name=_suggest_prefixed_name(asset_name, required_prefix),
                asset_type=resolved_type,
                message=(
                    f"Missing prefix '{required_prefix}' " f"for {resolved_type}."
                ),
            )
        )

    return issues


# NM002 — detect_spaces_in_name


def detect_spaces_in_name(asset_records: List[AssetRecord]) -> List[Issue]:
    """NM002: flag asset names that contain spaces.

    Spaces in asset names break code references and cause issues
    in source control and build pipelines.
    Suggests replacing spaces with underscores.
    """
    issues: List[Issue] = []

    for record in asset_records:
        asset_path = record.get("asset_path", "")
        asset_name = Path(asset_path).stem

        if " " not in asset_name:
            continue

        suggested_name = asset_name.replace(" ", "_")
        issues.append(
            _build_issue(
                rule_id="NM002",
                asset_path=asset_path,
                current_name=asset_name,
                suggested_name=suggested_name,
                asset_type="Unknown",
                message=(
                    "Asset name contains spaces. "
                    "Use underscores instead (e.g. 'Hero_Sword')."
                ),
            )
        )

    return issues


# NM003 — detect_special_chars


def detect_special_chars(asset_records: List[AssetRecord]) -> List[Issue]:
    """NM003: flag names containing characters outside [A-Za-z0-9_].

    Special characters break UE5 asset references and cause errors
    in build pipelines. Suggests replacing illegal chars with '_'.
    """
    issues: List[Issue] = []

    for record in asset_records:
        asset_path = record.get("asset_path", "")
        asset_name = Path(asset_path).stem

        illegal_chars = _ILLEGAL_CHAR_PATTERN.findall(asset_name)
        if not illegal_chars:
            continue

        suggested_name = _ILLEGAL_CHAR_PATTERN.sub("_", asset_name)
        unique_illegal = ", ".join(sorted(set(illegal_chars)))
        issues.append(
            _build_issue(
                rule_id="NM003",
                asset_path=asset_path,
                current_name=asset_name,
                suggested_name=suggested_name,
                asset_type="Unknown",
                message=(
                    "Asset name contains illegal characters: " f"{unique_illegal}."
                ),
            )
        )

    return issues


# NM004 — detect_lowercase_names


def detect_lowercase_names(asset_records: List[AssetRecord]) -> List[Issue]:
    """NM004: flag asset names that start with a lowercase letter.

    UE5 convention requires PascalCase or a valid uppercase prefix.
    Names starting with a digit or underscore are skipped — those
    are caught by NM001 or NM003 respectively.
    """
    issues: List[Issue] = []

    for record in asset_records:
        asset_path = record.get("asset_path", "")
        asset_name = Path(asset_path).stem

        if not asset_name:
            continue

        first_char = asset_name[0]
        if not first_char.isalpha() or first_char.isupper():
            continue

        suggested_name = first_char.upper() + asset_name[1:]
        issues.append(
            _build_issue(
                rule_id="NM004",
                asset_path=asset_path,
                current_name=asset_name,
                suggested_name=suggested_name,
                asset_type="Unknown",
                message=(
                    "Asset name starts with lowercase. "
                    "Use PascalCase or a valid prefix "
                    "(e.g. 'T_HeroSword')."
                ),
            )
        )

    return issues


# NM005 — detect_duplicate_names


def detect_duplicate_names(asset_records: List[AssetRecord]) -> List[Issue]:
    """NM005: flag assets sharing the same base name across folders.

    Duplicate names cause confusion when referencing assets in code
    and risk loading the wrong asset at runtime.
    All copies are flagged — not just the second occurrence.
    Detection is case-insensitive.
    """
    name_to_paths: Dict[str, List[str]] = defaultdict(list)
    for record in asset_records:
        asset_path = record.get("asset_path", "")
        asset_name = Path(asset_path).stem
        name_to_paths[asset_name.lower()].append(asset_path)

    issues: List[Issue] = []

    for _normalised_name, paths_with_name in name_to_paths.items():
        if len(paths_with_name) < 2:
            continue

        folder_list = "; ".join(
            str(Path(duplicate_path).parent) for duplicate_path in paths_with_name
        )

        for duplicate_path in paths_with_name:
            original_name = Path(duplicate_path).stem
            issues.append(
                _build_issue(
                    rule_id="NM005",
                    asset_path=duplicate_path,
                    current_name=original_name,
                    suggested_name=original_name,
                    asset_type="Unknown",
                    message=(
                        f"Duplicate asset name '{original_name}' "
                        f"found in multiple folders: {folder_list}."
                    ),
                )
            )

    return issues


# NM006 — detect_missing_tex_suffix

# Valid channel suffixes for Texture2D assets.
# Confirm final list with Raúl / Tech Art before Sprint 5 freeze.
#   _D  = Diffuse / Base Color
#   _N  = Normal map
#   _R  = Roughness
#   _M  = Metallic
#   _E  = Emissive
#   _AO = Ambient Occlusion
#   _H  = Height / Displacement
#   _S  = Specular
_TEXTURE_VALID_SUFFIXES: tuple = (
    "_D",
    "_N",
    "_R",
    "_M",
    "_E",
    "_AO",
    "_H",
    "_S",
)

# Texture prefix — only Texture2D assets are checked for channel suffix.
_TEXTURE_PREFIX: str = "T_"


def detect_missing_tex_suffix(
    asset_records: List[AssetRecord],
) -> List[Issue]:
    """NM006: flag Texture2D assets that have no channel suffix.

    Only assets whose name starts with T_ are evaluated.
    A texture without a suffix like _D or _N is ambiguous —
    developers cannot tell the channel type from the name alone.
    Suggests appending _D as the most common default.
    """
    issues: List[Issue] = []

    for record in asset_records:
        asset_path = record.get("asset_path", "")
        asset_name = Path(asset_path).stem

        if not asset_name.startswith(_TEXTURE_PREFIX):
            continue

        has_valid_suffix = any(
            asset_name.upper().endswith(suffix) for suffix in _TEXTURE_VALID_SUFFIXES
        )
        if has_valid_suffix:
            continue

        suggested_name = asset_name + "_D"
        issues.append(
            _build_issue(
                rule_id="NM006",
                asset_path=asset_path,
                current_name=asset_name,
                suggested_name=suggested_name,
                asset_type="Texture2D",
                message=(
                    f"Texture '{asset_name}' has no channel suffix. "
                    "Append a suffix to identify its type "
                    "(_D, _N, _R, _M, _E, _AO, _H, _S)."
                ),
            )
        )

    return issues


# ---------------------------------------------------------------------------
# NM007 — detect_non_pascal_case
# ---------------------------------------------------------------------------

# Regex: matches an underscore followed by a lowercase letter.
# Detects snake_case after the prefix, e.g. SM_hero_sword.
_SNAKE_CASE_AFTER_PREFIX: re.Pattern = re.compile(r"_[a-z]")

# Regex: extracts the part of the name after the leading prefix.
# Prefix = one or more uppercase letters followed by underscore(s).
# Example: "SM_HeroSword" → prefix "SM_", body "HeroSword"
_PREFIX_STRIP_PATTERN: re.Pattern = re.compile(r"^[A-Z]+_+")


def detect_non_pascal_case(
    asset_records: List[AssetRecord],
) -> List[Issue]:
    """NM007: flag names that are not PascalCase after the prefix.

    Valid:   SM_HeroSword, T_RockWall_D, BP_PlayerCharacter
    Invalid: SM_hero_sword, T_rock_wall, BP_playerCharacter

    Only checks assets that already have a valid prefix — assets
    without a prefix are handled by NM001.
    Suggests a PascalCase version of the body.
    """
    issues: List[Issue] = []

    for record in asset_records:
        asset_path = record.get("asset_path", "")
        asset_name = Path(asset_path).stem

        if not _has_valid_prefix(asset_name):
            continue

        # Strip the leading prefix to get the body (e.g. "HeroSword")
        body = _PREFIX_STRIP_PATTERN.sub("", asset_name)
        if not body:
            continue

        # Flag if the body contains _lowercase (snake_case pattern)
        # or starts with a lowercase letter
        snake_match = _SNAKE_CASE_AFTER_PREFIX.search(body)
        starts_lower = body[0].islower() if body else False

        if not snake_match and not starts_lower:
            continue

        # Build suggested PascalCase body: capitalise each word segment
        pascal_body = "".join(
            word_part.capitalize() for word_part in re.split(r"_+", body) if word_part
        )
        # Re-attach the original prefix
        prefix_match = _PREFIX_STRIP_PATTERN.match(asset_name)
        original_prefix = prefix_match.group(0) if prefix_match else ""
        suggested_name = original_prefix + pascal_body

        issues.append(
            _build_issue(
                rule_id="NM007",
                asset_path=asset_path,
                current_name=asset_name,
                suggested_name=suggested_name,
                asset_type="Unknown",
                message=(
                    f"'{asset_name}' is not PascalCase after the "
                    f"prefix — rename to '{suggested_name}'."
                ),
            )
        )

    return issues


# ---------------------------------------------------------------------------
# NM008 — detect_name_too_long
# ---------------------------------------------------------------------------

# Maximum asset name length in characters (prefix included).
# 64 chars covers most pipeline and source control constraints.
# Confirm with Raúl if the studio uses a different limit.
_MAX_ASSET_NAME_LENGTH: int = 64


def detect_name_too_long(
    asset_records: List[AssetRecord],
) -> List[Issue]:
    """NM008: flag asset names that exceed the maximum length.

    Long names cause truncation issues in some asset management
    tools, source control clients, and engine path length limits.
    The suggested name is the name truncated to the max length —
    the developer should choose a meaningful shorter name manually.
    """
    issues: List[Issue] = []

    for record in asset_records:
        asset_path = record.get("asset_path", "")
        asset_name = Path(asset_path).stem

        if len(asset_name) <= _MAX_ASSET_NAME_LENGTH:
            continue

        suggested_name = asset_name[:_MAX_ASSET_NAME_LENGTH]
        issues.append(
            _build_issue(
                rule_id="NM008",
                asset_path=asset_path,
                current_name=asset_name,
                suggested_name=suggested_name,
                asset_type="Unknown",
                message=(
                    f"Asset name is {len(asset_name)} characters "
                    f"(max: {_MAX_ASSET_NAME_LENGTH}). "
                    "Shorten to a more concise name."
                ),
            )
        )

    return issues


# ---------------------------------------------------------------------------
# NM009 — detect_wrong_folder
# ---------------------------------------------------------------------------


def detect_wrong_folder(
    asset_records: List[AssetRecord],
) -> List[Issue]:
    """NM009: flag assets whose type does not match their folder.

    Uses the real asset_type from UE5 AssetRegistry (sent by the plugin).
    Skips assets with Unknown type — requires real type to be useful.
    Example: a StaticMesh in /Textures/ or a Blueprint in /Materials/.
    """
    issues: List[Issue] = []

    for record in asset_records:
        asset_path = record.get("asset_path", "")
        asset_type = record.get("asset_type", "Unknown") or "Unknown"

        if asset_type == "Unknown":
            continue

        expected_folder = _TYPE_TO_EXPECTED_FOLDER.get(asset_type)
        if expected_folder is None:
            continue

        normalised_path = asset_path.lower().replace("\\", "/")
        folder_rule = _infer_folder_rule(normalised_path)

        if folder_rule is None:
            continue

        actual_folder = folder_rule["folder"]

        # Asset is in correct folder — no issue
        if actual_folder == expected_folder:
            continue

        # Also accept plural/singular variants of the same folder
        # e.g. "texture" and "textures" are both valid for Texture2D
        if actual_folder.rstrip("s") == expected_folder.rstrip("s"):
            continue

        asset_name = Path(asset_path).stem
        issues.append(
            _build_issue(
                rule_id="NM009",
                asset_path=asset_path,
                current_name=asset_name,
                suggested_name=asset_name,
                asset_type=asset_type,
                message=(
                    f"'{asset_name}' is a {asset_type} but is "
                    f"located in '/{actual_folder}/' — move it "
                    f"to '/{expected_folder}/'."
                ),
            )
        )

    return issues


# ---------------------------------------------------------------------------
# NM010 — detect_double_prefix
# ---------------------------------------------------------------------------


def detect_double_prefix(asset_records: List[AssetRecord]) -> List[Issue]:
    """NM010: flag assets with a duplicated prefix (e.g. T_T_HeroSword).
    Happens when an already-prefixed asset is renamed incorrectly.
    """
    issues: List[Issue] = []

    double_prefix_pattern = re.compile(r"^([A-Z]+_)\1")

    for record in asset_records:
        asset_path = record.get("asset_path", "")
        asset_name = Path(asset_path).stem
        prefix_match = double_prefix_pattern.match(asset_name)
        if not prefix_match:
            continue

        duplicated_prefix = prefix_match.group(1)
        suggested_name = asset_name[len(duplicated_prefix) :]
        issues.append(
            _build_issue(
                rule_id="NM010",
                asset_path=asset_path,
                current_name=asset_name,
                suggested_name=suggested_name,
                asset_type="Unknown",
                message=(
                    f"Duplicated prefix '{duplicated_prefix}' "
                    f"in '{asset_name}' — remove one copy."
                ),
            )
        )

    return issues


# ---------------------------------------------------------------------------
# NM011 — detect_number_start
# ---------------------------------------------------------------------------


def detect_number_start(asset_records: List[AssetRecord]) -> List[Issue]:
    """NM011: flag assets whose name starts with a digit (e.g. 123_Hero).
    UE5 asset names starting with a number cause reference issues.
    """
    issues: List[Issue] = []

    for record in asset_records:
        asset_path = record.get("asset_path", "")
        asset_name = Path(asset_path).stem
        if not asset_name or not asset_name[0].isdigit():
            continue

        suggested_name = "A_" + asset_name
        issues.append(
            _build_issue(
                rule_id="NM011",
                asset_path=asset_path,
                current_name=asset_name,
                suggested_name=suggested_name,
                asset_type="Unknown",
                message=(
                    f"'{asset_name}' starts with a number — "
                    "UE5 asset names must start with a letter."
                ),
            )
        )

    return issues


# ---------------------------------------------------------------------------
# NM012 — detect_consecutive_underscores
# ---------------------------------------------------------------------------


def detect_consecutive_underscores(
    asset_records: List[AssetRecord],
) -> List[Issue]:
    """NM012: flag asset names with consecutive underscores (e.g. T__Hero).
    Double underscores are usually a typo and break naming consistency.
    """
    issues: List[Issue] = []
    consecutive_underscore_pattern = re.compile(r"_{2,}")

    for record in asset_records:
        asset_path = record.get("asset_path", "")
        asset_name = Path(asset_path).stem
        if not consecutive_underscore_pattern.search(asset_name):
            continue

        suggested_name = consecutive_underscore_pattern.sub("_", asset_name)
        issues.append(
            _build_issue(
                rule_id="NM012",
                asset_path=asset_path,
                current_name=asset_name,
                suggested_name=suggested_name,
                asset_type="Unknown",
                message=(
                    f"'{asset_name}' contains consecutive "
                    "underscores — replace with a single '_'."
                ),
            )
        )

    return issues


# ---------------------------------------------------------------------------
# NM013 — detect_trailing_underscore
# ---------------------------------------------------------------------------


def detect_trailing_underscore(
    asset_records: List[AssetRecord],
) -> List[Issue]:
    """NM013: flag asset names ending with an underscore (e.g. T_HeroSword_).
    Trailing underscores are always a typo and break naming consistency.
    """
    issues: List[Issue] = []

    for record in asset_records:
        asset_path = record.get("asset_path", "")
        asset_name = Path(asset_path).stem
        if not asset_name.endswith("_"):
            continue

        suggested_name = asset_name.rstrip("_")
        issues.append(
            _build_issue(
                rule_id="NM013",
                asset_path=asset_path,
                current_name=asset_name,
                suggested_name=suggested_name,
                asset_type="Unknown",
                message=(
                    f"'{asset_name}' ends with an underscore "
                    "— remove the trailing '_'."
                ),
            )
        )

    return issues


# ---------------------------------------------------------------------------
# NM014 — detect_generic_name
# ---------------------------------------------------------------------------

# Generic name patterns — words that indicate a placeholder or
# non-descriptive asset name. English only. Case-insensitive.
# Grouped by category for maintainability.
_GENERIC_WORDS: frozenset = frozenset(
    [
        # Placeholders
        "new",
        "test",
        "temp",
        "tmp",
        "old",
        "backup",
        "copy",
        "draft",
        "wip",
        "todo",
        # Type repetition — name just repeats the asset type
        "texture",
        "mesh",
        "material",
        "blueprint",
        "sound",
        "animation",
        "asset",
        "object",
        "actor",
        # Generic content words
        "default",
        "sample",
        "example",
        "untitled",
        "unnamed",
        "placeholder",
        "dummy",
        "generic",
        "template",
    ]
)

# Regex: name body is only digits after the prefix
_ONLY_DIGITS_AFTER_PREFIX: re.Pattern = re.compile(r"^[A-Z]+_\d+$")


def detect_generic_name(asset_records: List[AssetRecord]) -> List[Issue]:
    """NM014: flag assets with generic or placeholder names.
    Uses folder inference to give context-aware messages.
    Only flags names that are obviously non-descriptive.
    """
    issues: List[Issue] = []

    for record in asset_records:
        asset_path = record.get("asset_path", "")
        asset_name = Path(asset_path).stem
        normalised_path = asset_path.lower().replace("\\", "/")

        # Check name-only-digits pattern first (e.g. T_001, SM_1)
        if _ONLY_DIGITS_AFTER_PREFIX.match(asset_name):
            folder_rule = _infer_folder_rule(normalised_path)
            asset_type = folder_rule["type"] if folder_rule else "Unknown"
            issues.append(
                _build_issue(
                    rule_id="NM014",
                    asset_path=asset_path,
                    current_name=asset_name,
                    suggested_name=asset_name,
                    asset_type=asset_type,
                    message=(
                        f"'{asset_name}' uses only digits after "
                        "the prefix — use a descriptive name."
                    ),
                )
            )
            continue

        # Strip valid prefix to get the name body
        prefix_match = _PREFIX_STRIP_PATTERN.match(asset_name)
        body = _PREFIX_STRIP_PATTERN.sub("", asset_name) if prefix_match else asset_name

        # Check if the body (lowercased) is a generic word
        # optionally followed by digits (e.g. Texture1, Mesh02)
        body_stripped = re.sub(r"\d+$", "", body).lower()
        if body_stripped not in _GENERIC_WORDS:
            continue

        folder_rule = _infer_folder_rule(normalised_path)
        asset_type = folder_rule["type"] if folder_rule else "Unknown"
        issues.append(
            _build_issue(
                rule_id="NM014",
                asset_path=asset_path,
                current_name=asset_name,
                suggested_name=asset_name,
                asset_type=asset_type,
                message=(
                    f"'{asset_name}' is a generic placeholder "
                    "name — use a descriptive name that "
                    "identifies the asset's content or purpose."
                ),
            )
        )

    return issues


# ---------------------------------------------------------------------------
# NM015 — detect_version_suffix
# ---------------------------------------------------------------------------

# Version and status suffixes that indicate the asset name
# is being used as a version control mechanism.
# All lowercase for case-insensitive comparison.
_VERSION_SUFFIXES: tuple = (
    "_v1",
    "_v2",
    "_v3",
    "_v4",
    "_v5",
    "_v01",
    "_v02",
    "_v03",
    "_old",
    "_new",
    "_final",
    "_copy",
    "_temp",
    "_tmp",
    "_backup",
    "_bak",
    "_test",
    "_wip",
    "_draft",
)


def detect_version_suffix(asset_records: List[AssetRecord]) -> List[Issue]:
    """NM015: flag assets using version or status suffixes in their name.
    These indicate source control is not being used correctly.
    Examples: T_HeroSword_v2, SM_Rock_old, BP_Player_FINAL.
    """
    issues: List[Issue] = []

    for record in asset_records:
        asset_path = record.get("asset_path", "")
        asset_name = Path(asset_path).stem
        lower_name = asset_name.lower()

        matched_suffix = next(
            (suffix for suffix in _VERSION_SUFFIXES if lower_name.endswith(suffix)),
            None,
        )
        if not matched_suffix:
            continue

        suggested_name = asset_name[: -len(matched_suffix)]
        issues.append(
            _build_issue(
                rule_id="NM015",
                asset_path=asset_path,
                current_name=asset_name,
                suggested_name=suggested_name,
                asset_type="Unknown",
                message=(
                    f"'{asset_name}' uses a version/status "
                    f"suffix '{matched_suffix}' — use source "
                    "control for versioning instead."
                ),
            )
        )

    return issues


# ---------------------------------------------------------------------------
# Entry point — called by api/routes/assets.py
# ---------------------------------------------------------------------------


def run_all_naming_rules(asset_records: List[AssetRecord]) -> List[Issue]:
    """Run NM001–NM015 against a list of asset record dicts.

    Each record must have: asset_path (str), asset_type (str).
    Returns a merged list of all naming issues found.
    Called by POST /assets/scan in api/routes/assets.py.
    """
    all_issues: List[Issue] = []

    all_issues += detect_missing_prefix(asset_records)
    all_issues += detect_spaces_in_name(asset_records)
    all_issues += detect_special_chars(asset_records)
    all_issues += detect_lowercase_names(asset_records)
    all_issues += detect_duplicate_names(asset_records)
    all_issues += detect_missing_tex_suffix(asset_records)
    all_issues += detect_non_pascal_case(asset_records)
    all_issues += detect_name_too_long(asset_records)
    all_issues += detect_wrong_folder(asset_records)
    all_issues += detect_double_prefix(asset_records)
    all_issues += detect_number_start(asset_records)
    all_issues += detect_consecutive_underscores(asset_records)
    all_issues += detect_trailing_underscore(asset_records)
    all_issues += detect_generic_name(asset_records)
    all_issues += detect_version_suffix(asset_records)

    return all_issues


# Backward-compatible alias — remove once assets.py import is updated.
def scan_asset_paths(asset_paths: List[str]) -> List[Issue]:
    """Backward-compatible wrapper — accepts List[str]."""
    records = [{"asset_path": p, "asset_type": "Unknown"} for p in asset_paths]
    return run_all_naming_rules(records)


# ---------------------------------------------------------------------------
# Rename stub
# ---------------------------------------------------------------------------


def apply_asset_rename(asset_path: str, new_name: str) -> bool:
    """Rename an asset.

    Sprint 4: implement via unreal.AssetTools.rename_assets([...]).
    Currently a stub — always returns True.
    """
    # TODO Sprint 4: call UE Python bindings here
    return True
