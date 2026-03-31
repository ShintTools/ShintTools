# core/modules/naming/rules/ue5_naming_rules.py
#
# UE5 Asset Naming Rules — ShintTools Naming Validator
#
# Detects naming convention violations from asset paths.
# All rules return severity "warning", category "Best Practices".
#
# Rule index:
#   NM001 — detect_missing_prefix    : asset lacks required type prefix
#   NM002 — detect_spaces_in_name    : name contains whitespace
#   NM003 — detect_special_chars     : name contains illegal characters
#   NM004 — detect_lowercase_names   : name starts with lowercase letter
#   NM005 — detect_duplicate_names   : same base name in multiple folders
#   NM006 — detect_missing_tex_suffix: Texture2D missing channel suffix
#   NM007 — detect_non_pascal_case   : name not PascalCase after prefix
#   NM008 — detect_name_too_long     : name exceeds max length (64 chars)
#
# Sprint 4: replace _infer_folder_rule() with AssetRegistry lookups.
# Current: pure Python, no I/O, folder-based type inference.

import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

Issue = Dict[str, Any]

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

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# NM001 — detect_missing_prefix
# ---------------------------------------------------------------------------


def detect_missing_prefix(asset_paths: List[str]) -> List[Issue]:
    """NM001: flag assets that lack a valid UE5 type prefix.

    Infers the expected prefix from the asset's folder name.
    Assets in unrecognised folders are flagged with type 'Unknown'.
    Sprint 4: replace folder inference with AssetRegistry lookups.
    """
    issues: List[Issue] = []

    for asset_path in asset_paths:
        asset_path_obj = Path(asset_path)
        asset_name = asset_path_obj.stem
        normalised_path = asset_path.lower().replace("\\", "/")

        if _has_valid_prefix(asset_name):
            continue

        folder_rule = _infer_folder_rule(normalised_path)

        if folder_rule is None:
            issues.append(
                _build_issue(
                    rule_id="NM001",
                    asset_path=asset_path,
                    current_name=asset_name,
                    suggested_name=asset_name,
                    asset_type="Unknown",
                    message=("Asset name has no recognised UE5 naming prefix."),
                )
            )
            continue

        required_prefix = folder_rule["prefix"]
        issues.append(
            _build_issue(
                rule_id="NM001",
                asset_path=asset_path,
                current_name=asset_name,
                suggested_name=_suggest_prefixed_name(asset_name, required_prefix),
                asset_type=folder_rule["type"],
                message=(
                    f"Missing prefix '{required_prefix}' " f"for {folder_rule['type']}."
                ),
            )
        )

    return issues


# ---------------------------------------------------------------------------
# NM002 — detect_spaces_in_name
# ---------------------------------------------------------------------------


def detect_spaces_in_name(asset_paths: List[str]) -> List[Issue]:
    """NM002: flag asset names that contain spaces.

    Spaces in asset names break code references and cause issues
    in source control and build pipelines.
    Suggests replacing spaces with underscores.
    """
    issues: List[Issue] = []

    for asset_path in asset_paths:
        asset_path_obj = Path(asset_path)
        asset_name = asset_path_obj.stem

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


# ---------------------------------------------------------------------------
# NM003 — detect_special_chars
# ---------------------------------------------------------------------------


def detect_special_chars(asset_paths: List[str]) -> List[Issue]:
    """NM003: flag names containing characters outside [A-Za-z0-9_].

    Special characters break UE5 asset references and cause errors
    in build pipelines. Suggests replacing illegal chars with '_'.
    """
    issues: List[Issue] = []

    for asset_path in asset_paths:
        asset_path_obj = Path(asset_path)
        asset_name = asset_path_obj.stem

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


# ---------------------------------------------------------------------------
# NM004 — detect_lowercase_names
# ---------------------------------------------------------------------------


def detect_lowercase_names(asset_paths: List[str]) -> List[Issue]:
    """NM004: flag asset names that start with a lowercase letter.

    UE5 convention requires PascalCase or a valid uppercase prefix.
    Names starting with a digit or underscore are skipped — those
    are caught by NM001 or NM003 respectively.
    """
    issues: List[Issue] = []

    for asset_path in asset_paths:
        asset_path_obj = Path(asset_path)
        asset_name = asset_path_obj.stem

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


# ---------------------------------------------------------------------------
# NM005 — detect_duplicate_names
# ---------------------------------------------------------------------------


def detect_duplicate_names(asset_paths: List[str]) -> List[Issue]:
    """NM005: flag assets sharing the same base name across folders.

    Duplicate names cause confusion when referencing assets in code
    and risk loading the wrong asset at runtime.
    All copies are flagged — not just the second occurrence.
    Detection is case-insensitive.
    """
    name_to_paths: Dict[str, List[str]] = defaultdict(list)
    for asset_path in asset_paths:
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


# ---------------------------------------------------------------------------
# NM006 — detect_missing_tex_suffix
# ---------------------------------------------------------------------------

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
    asset_paths: List[str],
) -> List[Issue]:
    """NM006: flag Texture2D assets that have no channel suffix.

    Only assets whose name starts with T_ are evaluated.
    A texture without a suffix like _D or _N is ambiguous —
    developers cannot tell the channel type from the name alone.
    Suggests appending _D as the most common default.
    """
    issues: List[Issue] = []

    for asset_path in asset_paths:
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
    asset_paths: List[str],
) -> List[Issue]:
    """NM007: flag names that are not PascalCase after the prefix.

    Valid:   SM_HeroSword, T_RockWall_D, BP_PlayerCharacter
    Invalid: SM_hero_sword, T_rock_wall, BP_playerCharacter

    Only checks assets that already have a valid prefix — assets
    without a prefix are handled by NM001.
    Suggests a PascalCase version of the body.
    """
    issues: List[Issue] = []

    for asset_path in asset_paths:
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
    asset_paths: List[str],
) -> List[Issue]:
    """NM008: flag asset names that exceed the maximum length.

    Long names cause truncation issues in some asset management
    tools, source control clients, and engine path length limits.
    The suggested name is the name truncated to the max length —
    the developer should choose a meaningful shorter name manually.
    """
    issues: List[Issue] = []

    for asset_path in asset_paths:
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
# Entry point — called by api/routes/assets.py
# ---------------------------------------------------------------------------


def run_all_naming_rules(asset_paths: List[str]) -> List[Issue]:
    """Run NM001–NM008 against a list of asset path strings.

    Returns a merged list of all naming issues found.
    Called by POST /assets/scan in api/routes/assets.py.
    Update the import there: scan_asset_paths → run_all_naming_rules.
    """
    all_issues: List[Issue] = []

    all_issues += detect_missing_prefix(asset_paths)
    all_issues += detect_spaces_in_name(asset_paths)
    all_issues += detect_special_chars(asset_paths)
    all_issues += detect_lowercase_names(asset_paths)
    all_issues += detect_duplicate_names(asset_paths)
    all_issues += detect_missing_tex_suffix(asset_paths)
    all_issues += detect_non_pascal_case(asset_paths)
    all_issues += detect_name_too_long(asset_paths)

    return all_issues


# Backward-compatible alias — remove once assets.py import is updated.
scan_asset_paths = run_all_naming_rules


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
