# core/modules/naming/rules/unity_naming_rules.py
#
# Unity Asset Naming Rules — ShintTools Naming Validator
#
# Engine-specific counterparts to the three UE5 rules that depend on
# prefix / folder tables. Every other rule in ue5_naming_rules
# (case, special chars, duplicates, length, etc.) is engine-agnostic
# and is reused as-is by the orchestrator.
#
# Convention: UE5-clone style adapted to Unity's C# type names. The
# plugin sends asset_type from AssetDatabase.GetMainAssetTypeAtPath(...)
# which returns the bare C# class name ("Texture2D", "Material",
# "GameObject" for prefabs, "ScriptableObject", "AnimationClip", ...).
#
# Rule IDs:
#   NMU001 — detect_unity_missing_prefix          : asset lacks required prefix
#   NMU009 — detect_unity_wrong_folder            : asset_type does not match folder
#   NMU016 — detect_unity_wrong_prefix_for_type   : valid prefix but wrong for type

from pathlib import Path
from typing import Any, Dict, List, Optional

Issue = Dict[str, Any]
AssetRecord = Dict[str, str]


# ---------------------------------------------------------------------------
# _UNITY_TYPE_TO_PREFIX
#
# Maps Unity asset C# type name → expected name prefix (without the
# trailing underscore). The launcher's plugin sends type values like
# "Texture2D", "Material", "GameObject" (for prefabs), etc.
# ---------------------------------------------------------------------------

_UNITY_TYPE_TO_PREFIX: Dict[str, str] = {
    "Texture2D":           "T",
    "RenderTexture":       "RT",
    "Cubemap":             "Cube",
    "Sprite":              "SP",
    "Material":            "M",
    "Mesh":                "SM",
    "Model":               "SM",
    "GameObject":          "P",     # prefabs come through as GameObject
    "ScriptableObject":    "SO",
    "AnimationClip":       "A",
    "AnimatorController":  "AC",
    "AvatarMask":          "AM",
    "AudioClip":           "Audio",
    "AudioMixer":          "MIX",
    "Shader":              "S",
    "ShaderGraph":         "SG",
    "VisualEffectAsset":   "VFX",
    "SceneAsset":          "Scene",
    "TerrainData":         "Terrain",
    "PhysicMaterial":      "PM",
    "Font":                "Font",
    "TextAsset":           "Text",
    "TimelineAsset":       "Timeline",
    "ComputeShader":       "CS",
    "LightmapParameters":  "LM",
    "FlareTexture":        "Flare",
}


# ---------------------------------------------------------------------------
# _UNITY_TYPE_TO_FOLDER
#
# Maps Unity asset type → expected folder segment (lowercase). Used by
# detect_unity_wrong_folder. Only types where the convention is
# unambiguous are listed; types missing from this map skip the check
# rather than flag a false positive.
# ---------------------------------------------------------------------------

_UNITY_TYPE_TO_FOLDER: Dict[str, str] = {
    "Texture2D":           "textures",
    "RenderTexture":       "rendertextures",
    "Cubemap":             "cubemaps",
    "Sprite":              "sprites",
    "Material":            "materials",
    "Mesh":                "meshes",
    "Model":               "meshes",
    "GameObject":          "prefabs",
    "ScriptableObject":    "scriptableobjects",
    "AnimationClip":       "animations",
    "AnimatorController":  "animators",
    "AudioClip":           "audio",
    "AudioMixer":          "audio",
    "Shader":              "shaders",
    "ShaderGraph":         "shaders",
    "VisualEffectAsset":   "vfx",
    "SceneAsset":          "scenes",
    "TerrainData":         "terrains",
    "PhysicMaterial":      "physics",
    "Font":                "fonts",
    "TextAsset":           "data",
    "TimelineAsset":       "timelines",
    "ComputeShader":       "shaders",
}


# Cached reverse lookup: every prefix value that's a legitimate prefix
# for SOME type. Used by detect_unity_wrong_prefix_for_type to tell apart
# "no prefix" from "valid prefix but for a different type".
_KNOWN_PREFIXES: set = {p for p in _UNITY_TYPE_TO_PREFIX.values()}


def _name_of(asset_path: str) -> str:
    return Path(asset_path).stem


def _emit(rule_id: str, asset_path: str, asset_type: str,
          message: str, fix_suggestion: Optional[str] = None) -> Issue:
    return {
        "rule_id":         rule_id,
        "severity":        "warning",
        "asset_path":      asset_path,
        "asset_type":      asset_type,
        "message":         message,
        "fix_suggestion":  fix_suggestion or "",
        "is_auto_fixable": bool(fix_suggestion),
    }


# ── NMU001 ──────────────────────────────────────────────────────────────────

def detect_unity_missing_prefix(records: List[AssetRecord]) -> List[Issue]:
    """Asset lacks the Unity prefix convention for its type.

    e.g. a Texture2D named `Hero.png` should be `T_Hero.png`. Skipped
    when asset_type is not in _UNITY_TYPE_TO_PREFIX (unknown / first-party
    asset types we don't map).
    """
    out: List[Issue] = []
    for r in records:
        t = (r.get("asset_type") or "").strip()
        prefix = _UNITY_TYPE_TO_PREFIX.get(t)
        if not prefix:
            continue
        name = _name_of(r.get("asset_path", ""))
        if not name:
            continue
        # Already correctly prefixed?
        if name.startswith(prefix + "_"):
            continue
        # Suggest the prefix-prepended name.
        out.append(_emit(
            "NMU001",
            r["asset_path"], t,
            f"{t} should start with `{prefix}_` (got `{name}`).",
            fix_suggestion=f"{prefix}_{name}",
        ))
    return out


# ── NMU009 ──────────────────────────────────────────────────────────────────

def detect_unity_wrong_folder(records: List[AssetRecord]) -> List[Issue]:
    """Asset stored in a folder that doesn't match the conventional
    location for its type.

    Conservative: only flags when the asset is NOT under any path segment
    matching the expected folder name (case-insensitive). Doesn't
    enforce the exact depth, only the presence somewhere in the path,
    so `Assets/Game/Heroes/Textures/T_Hero.png` is fine for a Texture2D.
    """
    out: List[Issue] = []
    for r in records:
        t = (r.get("asset_type") or "").strip()
        expected = _UNITY_TYPE_TO_FOLDER.get(t)
        if not expected:
            continue
        path = (r.get("asset_path") or "").lower().replace("\\", "/")
        segments = [s for s in path.split("/") if s]
        # Skip the file name itself.
        if segments and segments[-1].endswith((".meta", ".asset", ".prefab",
                                               ".png", ".jpg", ".jpeg",
                                               ".fbx", ".mat", ".cs",
                                               ".controller", ".anim",
                                               ".wav", ".mp3", ".ogg",
                                               ".shader", ".shadergraph",
                                               ".vfx", ".unity")):
            segments = segments[:-1]
        if expected in segments:
            continue
        out.append(_emit(
            "NMU009",
            r["asset_path"], t,
            f"{t} is not stored under a `{expected}` folder.",
        ))
    return out


# ── NMU016 ──────────────────────────────────────────────────────────────────

def detect_unity_wrong_prefix_for_type(records: List[AssetRecord]) -> List[Issue]:
    """Name carries a known prefix but it's the wrong one for the asset
    type. e.g. a Material named `T_Concrete.mat` (texture prefix on a
    material) should be `M_Concrete.mat`.

    Skipped when the asset has no prefix at all — that case is covered
    by NMU001 (missing prefix). Skipped for asset_types we don't map.
    """
    out: List[Issue] = []
    for r in records:
        t = (r.get("asset_type") or "").strip()
        expected_prefix = _UNITY_TYPE_TO_PREFIX.get(t)
        if not expected_prefix:
            continue
        name = _name_of(r.get("asset_path", ""))
        if "_" not in name:
            continue   # no prefix at all — NMU001 handles this case
        current = name.split("_", 1)[0]
        if current == expected_prefix:
            continue
        if current not in _KNOWN_PREFIXES:
            continue   # not a recognised prefix; NMU001 will flag missing
        rest = name.split("_", 1)[1]
        out.append(_emit(
            "NMU016",
            r["asset_path"], t,
            f"{t} uses prefix `{current}_` but should use `{expected_prefix}_`.",
            fix_suggestion=f"{expected_prefix}_{rest}",
        ))
    return out
