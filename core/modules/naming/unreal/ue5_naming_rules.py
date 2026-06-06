# core/modules/naming/rules/ue5_naming_rules.py
#
# UE5 Asset Naming Rules — ShintTools Naming Validator
#
# Detects naming convention violations from asset paths.
# All rules return severity "warning". Category is derived from
# the asset_type and maps to Dashboard filters:
#   Widgets, Data, Materials, Textures, Audio, VFX (and "Other").
#
# Each rule receives List[AssetRecord] where AssetRecord is:
#   { "asset_path": str, "asset_type": str }
# asset_type comes from UE5 AssetRegistry via the plugin.
# Falls back to folder inference when asset_type is empty or Unknown.
#
# Rule index:
#   NM001 — detect_missing_prefix           : asset lacks required type prefix
#   NM002 — detect_spaces_in_name           : name contains whitespace
#   NM003 — detect_special_chars            : name contains illegal characters
#   NM004 — detect_lowercase_names          : name starts with lowercase letter
#   NM005 — detect_duplicate_names          : same base name in multiple folders
#   NM006 — detect_missing_tex_suffix       : Texture2D missing channel suffix
#   NM007 — detect_non_pascal_case          : name not PascalCase after prefix
#   NM008 — detect_name_too_long            : name exceeds max length (64 chars)
#   NM009 — detect_wrong_folder             : asset type does not match folder
#   NM010 — detect_double_prefix            : duplicated prefix (T_T_Hero)
#   NM011 — detect_number_start             : name starts with a digit
#   NM012 — detect_consecutive_underscores  : double underscore in name
#   NM013 — detect_trailing_underscore      : name ends with underscore
#   NM014 — detect_generic_name             : placeholder or generic name
#   NM015 — detect_version_suffix           : version suffix (_v2, _old)
#   NM016 — detect_wrong_prefix_for_type    : valid prefix but wrong for type
#   NM017 — detect_name_too_short           : body after prefix < 3 chars
#   NM018 — detect_redundant_type_in_name   : type word repeated in body

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
# TYPE_TO_CATEGORY
#
# Maps UE5 asset_type → Dashboard filter category.
# The Dashboard exposes 8 filterable categories for naming issues:
#   Textures, Meshes, Materials, Blueprints, Widgets, Audio, VFX, Data
#
# Every known UE5 asset type is forced into one of these 8 — there is
# no "Other" bucket. Types that don't fit naturally (Animations,
# Physics, LevelSequence) are routed to the category that best
# matches their usage:
#   - Animations (AnimSequence, AnimMontage, BlendSpace, …)
#     → Meshes   (skeletal-mesh bound, cannot exist without one)
#   - PhysicsAsset
#     → Meshes   (physics body for a mesh)
#   - PhysicalMaterial
#     → Materials (defines physics surface properties — is a material)
#   - LevelSequence
#     → Data     (timeline definition, behaves like configuration data)
# ---------------------------------------------------------------------------

_TYPE_TO_CATEGORY: Dict[str, str] = {
    # ── Textures ──────────────────────────────────────
    "Texture2D": "Textures",
    "Texture": "Textures",
    "TextureCube": "Textures",
    "RenderTarget": "Textures",
    "TextureRenderTarget2D": "Textures",
    "TextureRenderTargetCube": "Textures",
    "MediaTexture": "Textures",
    # ── Meshes ────────────────────────────────────────
    "StaticMesh": "Meshes",
    "SkeletalMesh": "Meshes",
    "Skeleton": "Meshes",
    "DestructibleMesh": "Meshes",
    # Animations are skeletal-mesh bound → grouped with Meshes
    "AnimSequence": "Meshes",
    "AnimMontage": "Meshes",
    "BlendSpace": "Meshes",
    "BlendSpace1D": "Meshes",
    "AimOffsetBlendSpace": "Meshes",
    "AimOffsetBlendSpace1D": "Meshes",
    "AnimComposite": "Meshes",
    "PoseAsset": "Meshes",
    # PhysicsAsset is a physics body attached to a mesh → Meshes
    "PhysicsAsset": "Meshes",
    # ── Materials ─────────────────────────────────────
    "Material": "Materials",
    "MaterialInstance": "Materials",
    "MaterialInstanceConstant": "Materials",
    "MaterialInstanceDynamic": "Materials",
    "MaterialFunction": "Materials",
    "MaterialFunctionInstance": "Materials",
    "MaterialParameterCollection": "Materials",
    "SubsurfaceProfile": "Materials",
    # PhysicalMaterial defines surface physics properties → Materials
    "PhysicalMaterial": "Materials",
    # ── Blueprints ────────────────────────────────────
    "Blueprint": "Blueprints",
    "AnimBlueprint": "Blueprints",
    "BlueprintInterface": "Blueprints",
    "BlueprintGeneratedClass": "Blueprints",
    "BlueprintMacroLibrary": "Blueprints",
    "BlueprintFunctionLibrary": "Blueprints",
    # ── Widgets ───────────────────────────────────────
    "WidgetBlueprint": "Widgets",
    "WidgetBlueprintGeneratedClass": "Widgets",
    # ── Audio ─────────────────────────────────────────
    "SoundCue": "Audio",
    "SoundWave": "Audio",
    "SoundClass": "Audio",
    "SoundMix": "Audio",
    "SoundAttenuation": "Audio",
    "SoundConcurrency": "Audio",
    "MetaSoundSource": "Audio",
    "MetaSoundPatch": "Audio",
    "DialogueVoice": "Audio",
    "DialogueWave": "Audio",
    # ── VFX ───────────────────────────────────────────
    "ParticleSystem": "VFX",
    "NiagaraSystem": "VFX",
    "NiagaraEmitter": "VFX",
    "NiagaraScript": "VFX",
    # ── Data ──────────────────────────────────────────
    "DataTable": "Data",
    "DataAsset": "Data",
    "PrimaryDataAsset": "Data",
    "CurveFloat": "Data",
    "CurveVector": "Data",
    "CurveLinearColor": "Data",
    "UserDefinedEnum": "Data",
    "UserDefinedStruct": "Data",
    "CompositeDataTable": "Data",
    "StringTable": "Data",
    # LevelSequence is a timeline/config asset → Data
    "LevelSequence": "Data",
}

# Final fallback when neither the asset_type nor the folder path
# resolve to a known category. Data is chosen because it's the most
# "meta" bucket (definitions, tables, configuration) and least
# likely to mask a real issue belonging to another category.
_CATEGORY_FALLBACK: str = "Data"

# ---------------------------------------------------------------------------
# Folder-segment → Dashboard category mapping.
#
# Used as a fallback when the asset_type is unknown/empty. Any segment in
# the asset path that matches (case-insensitive) assigns its category.
# First match wins (walks the path from deepest to root).
# ---------------------------------------------------------------------------

_FOLDER_TO_CATEGORY: Dict[str, str] = {
    # ── Textures ──────────────────────────────────────
    "textures": "Textures",
    "texture": "Textures",
    "tex": "Textures",
    "rendertargets": "Textures",
    "rendertarget": "Textures",
    "cubemaps": "Textures",
    "cubemap": "Textures",
    # ── Meshes ────────────────────────────────────────
    "meshes": "Meshes",
    "mesh": "Meshes",
    "staticmeshes": "Meshes",
    "staticmesh": "Meshes",
    "skeletalmeshes": "Meshes",
    "skeletalmesh": "Meshes",
    "characters": "Meshes",
    "character": "Meshes",
    "props": "Meshes",
    "environment": "Meshes",
    "environments": "Meshes",
    "skeletons": "Meshes",
    "skeleton": "Meshes",
    # Animations — mesh-bound, grouped with Meshes
    "animations": "Meshes",
    "animation": "Meshes",
    "anim": "Meshes",
    "anims": "Meshes",
    "montages": "Meshes",
    "blendspaces": "Meshes",
    "poses": "Meshes",
    # Physics — PhysicsAsset is mesh-bound, grouped with Meshes
    "physics": "Meshes",
    # ── Materials ─────────────────────────────────────
    "materials": "Materials",
    "material": "Materials",
    "mat": "Materials",
    "mats": "Materials",
    "materialinstances": "Materials",
    "materialinstance": "Materials",
    "matinst": "Materials",
    "materialfunctions": "Materials",
    "materialfunction": "Materials",
    "shaders": "Materials",
    "shader": "Materials",
    "physicsmaterials": "Materials",
    "physicalmaterials": "Materials",
    # ── Blueprints ────────────────────────────────────
    "blueprints": "Blueprints",
    "blueprint": "Blueprints",
    "bp": "Blueprints",
    "bps": "Blueprints",
    "animblueprints": "Blueprints",
    "animblueprint": "Blueprints",
    "abp": "Blueprints",
    "actors": "Blueprints",
    "actor": "Blueprints",
    "pawns": "Blueprints",
    "pawn": "Blueprints",
    "controllers": "Blueprints",
    "interfaces": "Blueprints",
    "macros": "Blueprints",
    # ── Widgets ───────────────────────────────────────
    "widgets": "Widgets",
    "widget": "Widgets",
    "wbp": "Widgets",
    "ui": "Widgets",
    "hud": "Widgets",
    "menus": "Widgets",
    "menu": "Widgets",
    # ── Audio ─────────────────────────────────────────
    "audio": "Audio",
    "sounds": "Audio",
    "sound": "Audio",
    "soundwaves": "Audio",
    "soundcues": "Audio",
    "music": "Audio",
    "sfx": "Audio",
    "voice": "Audio",
    "dialogue": "Audio",
    "metasounds": "Audio",
    # ── VFX ───────────────────────────────────────────
    "vfx": "VFX",
    "particles": "VFX",
    "particle": "VFX",
    "niagara": "VFX",
    "effects": "VFX",
    "fx": "VFX",
    # ── Data ──────────────────────────────────────────
    "data": "Data",
    "datatables": "Data",
    "datatable": "Data",
    "dataassets": "Data",
    "dataasset": "Data",
    "curves": "Data",
    "curve": "Data",
    "enums": "Data",
    "enum": "Data",
    "structs": "Data",
    "struct": "Data",
    "sequences": "Data",
    "cinematics": "Data",
    "stringtables": "Data",
    "configs": "Data",
    "config": "Data",
}


def _category_for_type(asset_type: str) -> Optional[str]:
    """Return the Dashboard filter category for a UE5 asset type.

    Returns ``None`` when the type is empty or not mapped, so the caller
    can fall through to path-based inference. The final fallback is
    applied by :func:`_resolve_category`, never here.
    """
    if not asset_type:
        return None
    return _TYPE_TO_CATEGORY.get(asset_type)


def _category_from_path(asset_path: str) -> Optional[str]:
    """Return the Dashboard filter category inferred from the folder path.

    Walks the path segments (case-insensitive) and returns the category
    of the first matching folder segment (deepest first). Returns
    ``None`` if no segment matches — the final fallback is applied by
    :func:`_resolve_category`.

    Example:
        "/Game/Environment/Textures/Rocks/bad_name"
        → "Textures"  (matched segment "Textures")
    """
    if not asset_path:
        return None
    # Split on both Unix and Windows separators; drop empties.
    segments = [seg for seg in re.split(r"[\\/]+", asset_path) if seg]
    # Walk from deepest to root so the closest folder wins.
    for segment in reversed(segments):
        category = _FOLDER_TO_CATEGORY.get(segment.lower())
        if category is not None:
            return category
    return None


def _resolve_category(asset_type: str, asset_path: str) -> str:
    """Resolve the Dashboard category with type-first, path-fallback logic.

    Priority:
        1. If ``asset_type`` maps to a known category → use it.
        2. Otherwise, infer from folder segments in ``asset_path``.
        3. Otherwise, ``_CATEGORY_FALLBACK`` (currently ``"Data"``).

    This function **never** returns ``"Other"`` — every asset is
    guaranteed to land in one of the 8 Dashboard categories.
    """
    category = _category_for_type(asset_type)
    if category is not None:
        return category
    category = _category_from_path(asset_path)
    if category is not None:
        return category
    return _CATEGORY_FALLBACK


# ---------------------------------------------------------------------------
# Rule metadata
# ---------------------------------------------------------------------------

_NM_SEVERITY: str = "warning"

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
    fix_suggestion: str,
    asset_type: str,
    message: str,
) -> Issue:
    """Return a fully-populated naming issue dict."""
    return {
        "asset_path": asset_path,
        "current_name": current_name,
        "fix_suggestion": fix_suggestion,
        "severity": _NM_SEVERITY,
        "rule_id": rule_id,
        "category": _resolve_category(asset_type, asset_path),
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
# TYPE_TO_PREFIX
#
# Maps UE5 asset class name → required prefix.
# Built once from _FOLDER_RULES. First match per type wins.
# Used by NM016 to detect assets with a valid but wrong prefix.
# ---------------------------------------------------------------------------

_TYPE_TO_PREFIX: Dict[str, str] = {}
for _fr in _FOLDER_RULES:
    if _fr["type"] not in _TYPE_TO_PREFIX:
        _TYPE_TO_PREFIX[_fr["type"]] = _fr["prefix"]


# NM001 — detect_missing_prefix


def detect_missing_prefix(asset_records: List[AssetRecord]) -> List[Issue]:
    """NM001: flag assets that lack a valid UE5 type prefix.

    UE5 conventions require every asset to start with a short prefix
    identifying its class (SM_, T_, M_, BP_, …). Without one, assets
    are hard to find in the Content Browser and risk colliding with
    other types when referenced by name from code.

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
                    fix_suggestion=asset_name,
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
                fix_suggestion=_suggest_prefixed_name(asset_name, required_prefix),
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

        fix_suggestion = asset_name.replace(" ", "_")
        issues.append(
            _build_issue(
                rule_id="NM002",
                asset_path=asset_path,
                current_name=asset_name,
                fix_suggestion=fix_suggestion,
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

        fix_suggestion = _ILLEGAL_CHAR_PATTERN.sub("_", asset_name)
        unique_illegal = ", ".join(sorted(set(illegal_chars)))
        issues.append(
            _build_issue(
                rule_id="NM003",
                asset_path=asset_path,
                current_name=asset_name,
                fix_suggestion=fix_suggestion,
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

        fix_suggestion = first_char.upper() + asset_name[1:]
        issues.append(
            _build_issue(
                rule_id="NM004",
                asset_path=asset_path,
                current_name=asset_name,
                fix_suggestion=fix_suggestion,
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
    # Cython compiles the explicit `Dict[str, List[str]]` annotation into a
    # strict isinstance(dict) check that REJECTS subclasses, so assigning a
    # `defaultdict(list)` to it raises:
    #   TypeError: Expected dict, got collections.defaultdict
    # at the very first line that touches the variable. Drop the annotation
    # — the local is only used inside this function, the .append/.items
    # calls below don't need a type hint to keep working, and pure-Python
    # callers see the same defaultdict semantics.
    name_to_paths = defaultdict(list)
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
                    fix_suggestion=original_name,
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
# Single-channel and Epic-standard packed suffixes.
#   _D    = Diffuse / Base Color (_BC / _A also accepted as aliases)
#   _N    = Normal map
#   _R    = Roughness
#   _M    = Metallic
#   _E    = Emissive (_EM = emissive mask)
#   _AO   = Ambient Occlusion
#   _H    = Height / Displacement
#   _S    = Specular
#   _O    = Opacity / Alpha mask
#   _ORM  = Packed Occlusion / Roughness / Metallic (Epic standard)
#   _RMA  = Packed Roughness / Metallic / AO
#   _MRA  = Packed Metallic / Roughness / AO
#   _RGH  = Roughness (explicit alias)
#   _MSK  = Generic RGBA mask
#   _LUT  = Look-up table
_TEXTURE_VALID_SUFFIXES: tuple = (
    "_D",
    "_BC",
    "_A",
    "_N",
    "_R",
    "_RGH",
    "_M",
    "_E",
    "_EM",
    "_AO",
    "_H",
    "_S",
    "_O",
    "_ORM",
    "_RMA",
    "_MRA",
    "_MSK",
    "_LUT",
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

        fix_suggestion = asset_name + "_D"
        issues.append(
            _build_issue(
                rule_id="NM006",
                asset_path=asset_path,
                current_name=asset_name,
                fix_suggestion=fix_suggestion,
                asset_type="Texture2D",
                message=(
                    f"Texture '{asset_name}' has no channel suffix. "
                    "Append a suffix to identify its type "
                    "(_D, _N, _R, _M, _E, _AO, _H, _S, _ORM, _RMA, _MSK)."
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
        fix_suggestion = original_prefix + pascal_body

        issues.append(
            _build_issue(
                rule_id="NM007",
                asset_path=asset_path,
                current_name=asset_name,
                fix_suggestion=fix_suggestion,
                asset_type="Unknown",
                message=(
                    f"'{asset_name}' is not PascalCase after the "
                    f"prefix — rename to '{fix_suggestion}'."
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

        fix_suggestion = asset_name[:_MAX_ASSET_NAME_LENGTH]
        issues.append(
            _build_issue(
                rule_id="NM008",
                asset_path=asset_path,
                current_name=asset_name,
                fix_suggestion=fix_suggestion,
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

    A StaticMesh in /Textures/ or a Blueprint in /Materials/ confuses
    teammates browsing the Content Browser and breaks tooling that
    resolves assets by folder convention. Move the asset to its
    expected folder.

    Uses the real asset_type from UE5 AssetRegistry (sent by the plugin).
    Skips assets with Unknown type — requires real type to be useful.
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
                fix_suggestion=asset_name,
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
        fix_suggestion = asset_name[len(duplicated_prefix) :]
        issues.append(
            _build_issue(
                rule_id="NM010",
                asset_path=asset_path,
                current_name=asset_name,
                fix_suggestion=fix_suggestion,
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

        fix_suggestion = "A_" + asset_name
        issues.append(
            _build_issue(
                rule_id="NM011",
                asset_path=asset_path,
                current_name=asset_name,
                fix_suggestion=fix_suggestion,
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

        fix_suggestion = consecutive_underscore_pattern.sub("_", asset_name)
        issues.append(
            _build_issue(
                rule_id="NM012",
                asset_path=asset_path,
                current_name=asset_name,
                fix_suggestion=fix_suggestion,
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

        fix_suggestion = asset_name.rstrip("_")
        issues.append(
            _build_issue(
                rule_id="NM013",
                asset_path=asset_path,
                current_name=asset_name,
                fix_suggestion=fix_suggestion,
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

    Generic names like 'Test', 'New', 'Untitled', or 'Asset1' don't
    describe what the asset actually is, making them impossible to
    find by search and a maintenance burden as the project grows.
    Rename to something descriptive of the asset's purpose.

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
                    fix_suggestion="",
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
                fix_suggestion="",
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

        fix_suggestion = asset_name[: -len(matched_suffix)]
        issues.append(
            _build_issue(
                rule_id="NM015",
                asset_path=asset_path,
                current_name=asset_name,
                fix_suggestion=fix_suggestion,
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
# NM016 — detect_wrong_prefix_for_type
# ---------------------------------------------------------------------------


def detect_wrong_prefix_for_type(
    asset_records: List[AssetRecord],
) -> List[Issue]:
    """NM016: flag assets that carry a valid prefix that doesn't match
    their type. NM001 handles missing prefixes; this catches the mismatched
    case — e.g. a StaticMesh named 'T_Rock' (T_ is valid for Texture2D
    but should be SM_).

    Requires asset_type from AssetRegistry — skips assets with Unknown type.
    """
    issues: List[Issue] = []

    for record in asset_records:
        asset_path = record.get("asset_path", "")
        asset_type = record.get("asset_type", "Unknown") or "Unknown"
        asset_name = Path(asset_path).stem

        if asset_type == "Unknown":
            continue

        # Only check assets that already have a valid prefix
        if not _has_valid_prefix(asset_name):
            continue

        # Get the expected prefix for this asset type
        expected_prefix = _TYPE_TO_PREFIX.get(asset_type)
        if expected_prefix is None:
            continue

        # Check if the asset name starts with the expected prefix
        if asset_name.startswith(expected_prefix):
            continue

        # Asset has a valid prefix but it's wrong for its type
        fix_suggestion = _suggest_prefixed_name(asset_name, expected_prefix)
        issues.append(
            _build_issue(
                rule_id="NM016",
                asset_path=asset_path,
                current_name=asset_name,
                fix_suggestion=fix_suggestion,
                asset_type=asset_type,
                message=(
                    f"'{asset_name}' has prefix for a different "
                    f"type — expected '{expected_prefix}' for "
                    f"{asset_type}. Rename to '{fix_suggestion}'."
                ),
            )
        )

    return issues


# ---------------------------------------------------------------------------
# NM017 — detect_name_too_short
# ---------------------------------------------------------------------------

# Minimum body length after the prefix.
# Names like SM_R, T_A, BP_X are not descriptive enough.
_MIN_BODY_LENGTH: int = 3


def detect_name_too_short(
    asset_records: List[AssetRecord],
) -> List[Issue]:
    """NM017: flag asset names whose body is too short after the prefix.

    A name like 'SM_R' or 'T_AB' has a valid prefix but the body
    (1-2 characters) is not descriptive enough to identify the asset.
    Only checks assets that have a valid prefix — assets without one
    are handled by NM001.
    """
    issues: List[Issue] = []

    for record in asset_records:
        asset_path = record.get("asset_path", "")
        asset_name = Path(asset_path).stem

        if not _has_valid_prefix(asset_name):
            continue

        body = _PREFIX_STRIP_PATTERN.sub("", asset_name)

        # Skip if body is long enough or empty (empty is caught by
        # other rules)
        if not body or len(body) >= _MIN_BODY_LENGTH:
            continue

        issues.append(
            _build_issue(
                rule_id="NM017",
                asset_path=asset_path,
                current_name=asset_name,
                fix_suggestion=asset_name,
                asset_type="Unknown",
                message=(
                    f"'{asset_name}' has only {len(body)} "
                    f"character(s) after the prefix (min: "
                    f"{_MIN_BODY_LENGTH}) — use a longer, "
                    "descriptive name."
                ),
            )
        )

    return issues


# ---------------------------------------------------------------------------
# NM018 — detect_redundant_type_in_name
# ---------------------------------------------------------------------------

# Words derived from asset class names that should not appear in the
# body after the prefix. Lowercase for comparison.
_REDUNDANT_TYPE_WORDS: Dict[str, frozenset] = {
    "Texture2D": frozenset({"texture", "tex"}),
    "StaticMesh": frozenset({"staticmesh", "mesh", "static"}),
    "SkeletalMesh": frozenset({"skeletalmesh", "skeletal", "skel"}),
    "Material": frozenset({"material", "mat"}),
    "MaterialInstance": frozenset({"materialinstance", "matinstance", "matinst"}),
    "MaterialFunction": frozenset({"materialfunction", "matfunc"}),
    "Blueprint": frozenset({"blueprint", "bp"}),
    "AnimBlueprint": frozenset({"animblueprint", "animbp"}),
    "WidgetBlueprint": frozenset({"widgetblueprint", "widget"}),
    "SoundCue": frozenset({"soundcue", "cue"}),
    "SoundWave": frozenset({"soundwave", "wave"}),
    "AnimSequence": frozenset({"animsequence", "animseq"}),
    "AnimMontage": frozenset({"animmontage", "montage"}),
    "ParticleSystem": frozenset({"particlesystem", "particle"}),
    "NiagaraSystem": frozenset({"niagarasystem", "niagara"}),
    "DataTable": frozenset({"datatable"}),
    "DataAsset": frozenset({"dataasset"}),
}


def detect_redundant_type_in_name(
    asset_records: List[AssetRecord],
) -> List[Issue]:
    """NM018: flag names that redundantly include the asset type word.

    The type prefix already identifies the asset class — repeating
    the type in the body is noise.
    Examples: SM_StaticMeshRock → SM_Rock, T_TextureWall → T_Wall,
              M_MaterialGround → M_Ground.

    Requires asset_type from AssetRegistry for accurate detection.
    Skips assets with Unknown type.
    """
    issues: List[Issue] = []

    for record in asset_records:
        asset_path = record.get("asset_path", "")
        asset_type = record.get("asset_type", "Unknown") or "Unknown"
        asset_name = Path(asset_path).stem

        if asset_type == "Unknown":
            continue

        if not _has_valid_prefix(asset_name):
            continue

        redundant_words = _REDUNDANT_TYPE_WORDS.get(asset_type)
        if not redundant_words:
            continue

        body = _PREFIX_STRIP_PATTERN.sub("", asset_name)
        if not body:
            continue

        body_lower = body.lower()

        # Check if the body starts with a redundant type word
        matched_word = None
        for word in redundant_words:
            if body_lower.startswith(word):
                # Ensure it's a word boundary — next char should be
                # uppercase, underscore, digit, or end of string
                rest = body[len(word) :]
                if not rest or rest[0].isupper() or rest[0] == "_" or rest[0].isdigit():
                    matched_word = word
                    break

        if not matched_word:
            continue

        # Build suggested name: prefix + body without the redundant word
        prefix_match = _PREFIX_STRIP_PATTERN.match(asset_name)
        original_prefix = prefix_match.group(0) if prefix_match else ""
        cleaned_body = body[len(matched_word) :]
        # Strip leading underscore if present after removal
        cleaned_body = cleaned_body.lstrip("_")
        if cleaned_body:
            fix_suggestion = original_prefix + cleaned_body
        else:
            fix_suggestion = asset_name  # Can't suggest empty body

        issues.append(
            _build_issue(
                rule_id="NM018",
                asset_path=asset_path,
                current_name=asset_name,
                fix_suggestion=fix_suggestion,
                asset_type=asset_type,
                message=(
                    f"'{asset_name}' repeats the type word "
                    f"'{matched_word}' after the prefix — the "
                    f"prefix already identifies the type. "
                    f"Rename to '{fix_suggestion}'."
                ),
            )
        )

    return issues


# ---------------------------------------------------------------------------
# Entry point — called by api/routes/assets.py
# ---------------------------------------------------------------------------


def run_all_naming_rules(asset_records: List[AssetRecord]) -> List[Issue]:
    """Run NM001–NM018 against a list of asset record dicts.

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
    all_issues += detect_wrong_prefix_for_type(asset_records)
    all_issues += detect_name_too_short(asset_records)
    all_issues += detect_redundant_type_in_name(asset_records)

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
