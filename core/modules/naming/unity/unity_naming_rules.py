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
    "Texture2D": "T",
    "RenderTexture": "RT",
    "Cubemap": "Cube",
    "Sprite": "SP",
    "Material": "M",
    "Mesh": "SM",
    "Model": "SM",
    "GameObject": "P",  # prefabs come through as GameObject
    "ScriptableObject": "SO",
    "AnimationClip": "A",
    "AnimatorController": "AC",
    "AvatarMask": "AM",
    "AudioClip": "Audio",
    "AudioMixer": "MIX",
    "Shader": "S",
    "ShaderGraph": "SG",
    "VisualEffectAsset": "VFX",
    "SceneAsset": "Scene",
    "TerrainData": "Terrain",
    "PhysicMaterial": "PM",
    "Font": "Font",
    "TextAsset": "Text",
    "TimelineAsset": "Timeline",
    "ComputeShader": "CS",
    "LightmapParameters": "LM",
    "FlareTexture": "Flare",
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
    "Texture2D": "textures",
    "RenderTexture": "rendertextures",
    "Cubemap": "cubemaps",
    "Sprite": "sprites",
    "Material": "materials",
    "Mesh": "meshes",
    "Model": "meshes",
    "GameObject": "prefabs",
    "ScriptableObject": "scriptableobjects",
    "AnimationClip": "animations",
    "AnimatorController": "animators",
    "AudioClip": "audio",
    "AudioMixer": "audio",
    "Shader": "shaders",
    "ShaderGraph": "shaders",
    "VisualEffectAsset": "vfx",
    "SceneAsset": "scenes",
    "TerrainData": "terrains",
    "PhysicMaterial": "physics",
    "Font": "fonts",
    "TextAsset": "data",
    "TimelineAsset": "timelines",
    "ComputeShader": "shaders",
}


# Cached reverse lookup: every prefix value that's a legitimate prefix
# for SOME type. Used by detect_unity_wrong_prefix_for_type to tell apart
# "no prefix" from "valid prefix but for a different type".
_KNOWN_PREFIXES: set = {p for p in _UNITY_TYPE_TO_PREFIX.values()}


def _name_of(asset_path: str) -> str:
    return Path(asset_path).stem


def _emit(
    rule_id: str,
    asset_path: str,
    asset_type: str,
    message: str,
    fix_suggestion: Optional[str] = None,
) -> Issue:
    return {
        "rule_id": rule_id,
        "severity": "warning",
        "asset_path": asset_path,
        "asset_type": asset_type,
        "message": message,
        "fix_suggestion": fix_suggestion or "",
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
        # Skip names with no alphanumeric characters (e.g. "___") — the
        # fix would produce a worse name like "T____" with no semantic value.
        if not any(c.isalnum() for c in name):
            continue
        # Already correctly prefixed?
        if name.startswith(prefix + "_"):
            continue
        # Suggest the prefix-prepended name.
        out.append(
            _emit(
                "NMU001",
                r["asset_path"],
                t,
                f"{t} should start with `{prefix}_` (got `{name}`).",
                fix_suggestion=f"{prefix}_{name}",
            )
        )
    return out


# ── NMU009 ──────────────────────────────────────────────────────────────────


def detect_unity_wrong_folder(records: List[AssetRecord]) -> List[Issue]:
    """Asset stored in a folder that doesn't match the conventional
    location for its type.

    Detection: only flags when the asset is NOT under any path segment
    matching the expected folder name (case-insensitive). Doesn't
    enforce exact depth — `Assets/Game/Heroes/Textures/T_Hero.png` is
    fine for a Texture2D.
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
        if segments and segments[-1].endswith(
            (
                ".meta",
                ".asset",
                ".prefab",
                ".png",
                ".jpg",
                ".jpeg",
                ".fbx",
                ".mat",
                ".cs",
                ".controller",
                ".anim",
                ".wav",
                ".mp3",
                ".ogg",
                ".shader",
                ".shadergraph",
                ".vfx",
                ".unity",
            )
        ):
            segments = segments[:-1]
        if expected in segments:
            continue
        out.append(
            _emit(
                "NMU009",
                r["asset_path"],
                t,
                f"{t} is not stored under a `{expected}` folder.",
            )
        )
    return out


# ── NMU002 ──────────────────────────────────────────────────────────────────


def detect_unity_path_outside_assets(records: List[AssetRecord]) -> List[Issue]:
    """Asset path does not start with `Assets/`.

    Unity requires all project assets to live inside the Assets/ folder.
    Paths that don't start with Assets/ indicate an incorrect root, which
    causes AssetDatabase errors and platform builds to fail.
    """
    out: List[Issue] = []
    for r in records:
        path = (r.get("asset_path") or "").replace("\\", "/")
        if not path:
            continue
        if not (path.startswith("Assets/") or path == "Assets"):
            out.append(
                _emit(
                    "NMU002",
                    r["asset_path"],
                    r.get("asset_type", ""),
                    f"Asset path must start with `Assets/` (got `{path}`).",
                )
            )
    return out


# ── NMU003 ──────────────────────────────────────────────────────────────────


def detect_unity_backslash_in_path(records: List[AssetRecord]) -> List[Issue]:
    r"""Asset path uses backslash (`\`) instead of forward slash (`/`).

    Unity's AssetDatabase always uses forward slashes. Backslashes cause
    path resolution failures on macOS/Linux CI and in package builds.
    Replace every `\` with `/`.
    """
    out: List[Issue] = []
    for r in records:
        path = r.get("asset_path") or ""
        if "\\" in path:
            fixed = path.replace("\\", "/")
            out.append(
                _emit(
                    "NMU003",
                    r["asset_path"],
                    r.get("asset_type", ""),
                    "Path contains backslashes; use forward slashes.",
                    fix_suggestion=fixed,
                )
            )
    return out


# ── NMU004 ──────────────────────────────────────────────────────────────────

_VALID_SCRIPT_FOLDERS = {"scripts", "editor", "plugins", "runtime", "tests"}


def detect_unity_script_misplaced(records: List[AssetRecord]) -> List[Issue]:
    """C# script is not inside a Scripts/, Editor/, Plugins/, or Runtime/ folder.

    Loose .cs files at the Assets root or in art/audio folders break
    Assembly Definition boundaries and make compile order unpredictable.
    Move the script to the appropriate folder for its role.
    """
    out: List[Issue] = []
    for r in records:
        path = (r.get("asset_path") or "").replace("\\", "/")
        if not path.lower().endswith(".cs"):
            continue
        folder_segments = [s.lower() for s in path.split("/")[:-1]]
        if any(seg in _VALID_SCRIPT_FOLDERS for seg in folder_segments):
            continue
        out.append(
            _emit(
                "NMU004",
                r["asset_path"],
                r.get("asset_type", ""),
                "C# script is outside Scripts/, Editor/, Plugins/, or Runtime/.",
            )
        )
    return out


# ── NMU005 ──────────────────────────────────────────────────────────────────


def detect_unity_resources_folder(records: List[AssetRecord]) -> List[Issue]:
    """Asset is stored under a Resources/ folder.

    Assets inside Resources/ are always included in the build and loaded
    into memory on startup, even if never referenced at runtime. Prefer
    Addressables or direct asset references to avoid bloating build size
    and memory usage.
    """
    out: List[Issue] = []
    for r in records:
        path = (r.get("asset_path") or "").replace("\\", "/")
        folder_segments = [s.lower() for s in path.split("/")[:-1]]
        if "resources" in folder_segments:
            out.append(
                _emit(
                    "NMU005",
                    r["asset_path"],
                    r.get("asset_type", ""),
                    "Asset is under Resources/; prefer Addressables or"
                    " direct references.",
                )
            )
    return out


# ── NMU006 ──────────────────────────────────────────────────────────────────


def detect_unity_streaming_assets(records: List[AssetRecord]) -> List[Issue]:
    """Asset is stored under StreamingAssets/.

    Files there are copied verbatim into the build output and bypass
    Unity's asset pipeline (no compression, no type checking). Reserve
    StreamingAssets/ for data that must be read via raw file I/O at
    runtime (videos, external config). Everything else belongs under
    Assets/.
    """
    out: List[Issue] = []
    for r in records:
        path = (r.get("asset_path") or "").replace("\\", "/")
        folder_segments = [s.lower() for s in path.split("/")[:-1]]
        if "streamingassets" in folder_segments:
            out.append(
                _emit(
                    "NMU006",
                    r["asset_path"],
                    r.get("asset_type", ""),
                    "Asset is under StreamingAssets/; verify this is intentional.",
                )
            )
    return out


# ── NMU007 ──────────────────────────────────────────────────────────────────

_EDITOR_ONLY_TYPES = {
    "DefaultAsset",
    "EditorBuildSettings",
    "EditorSettings",
    "BuildReport",
}


def detect_unity_editor_folder_misuse(records: List[AssetRecord]) -> List[Issue]:
    """Non-editor asset is stored inside an Editor/ folder.

    Assets under Editor/ are stripped from non-editor builds by Unity.
    Art assets, prefabs, ScriptableObjects, and other runtime assets
    placed here will be missing at runtime. Only .cs editor scripts and
    editor-specific asset types belong under Editor/.
    """
    out: List[Issue] = []
    for r in records:
        path = (r.get("asset_path") or "").replace("\\", "/")
        folder_segments = [s.lower() for s in path.split("/")[:-1]]
        if "editor" not in folder_segments:
            continue
        t = (r.get("asset_type") or "").strip()
        if t in _EDITOR_ONLY_TYPES:
            continue
        if path.lower().endswith(".cs"):
            continue
        out.append(
            _emit(
                "NMU007",
                r["asset_path"],
                t,
                f"{t or 'Asset'} is under Editor/ and will be stripped"
                " from runtime builds.",
            )
        )
    return out


# ── NMU008 ──────────────────────────────────────────────────────────────────


def detect_unity_scene_misplaced(records: List[AssetRecord]) -> List[Issue]:
    """Unity scene file is not stored under a Scenes/ folder.

    Scenes outside Scenes/ are harder to manage in Build Settings and
    break the standard Unity project layout expected by source-control
    and team workflows. Move the scene to Assets/Scenes/ or a subfolder.
    """
    out: List[Issue] = []
    for r in records:
        t = (r.get("asset_type") or "").strip()
        if t != "SceneAsset":
            continue
        path = (r.get("asset_path") or "").replace("\\", "/")
        folder_segments = [s.lower() for s in path.split("/")[:-1]]
        if "scenes" in folder_segments:
            continue
        out.append(
            _emit(
                "NMU008",
                r["asset_path"],
                t,
                "Scene is not under a Scenes/ folder.",
            )
        )
    return out


# ── NMU010 ──────────────────────────────────────────────────────────────────

_SO_VALID_SUFFIXES = ("_Data", "_Config", "_Settings", "_Definition", "_Parameters")


def detect_unity_scriptableobject_suffix(records: List[AssetRecord]) -> List[Issue]:
    """ScriptableObject asset lacks a descriptive suffix (_Data, _Config, _Settings).

    ScriptableObjects serve as data containers and configuration holders.
    A suffix that describes their role (_Data, _Config, _Settings) makes
    their purpose immediately clear and avoids confusion with other asset
    types in the same folder.
    """
    out: List[Issue] = []
    for r in records:
        t = (r.get("asset_type") or "").strip()
        if t != "ScriptableObject":
            continue
        name = _name_of(r.get("asset_path", ""))
        if not name:
            continue
        if any(name.endswith(suf) for suf in _SO_VALID_SUFFIXES):
            continue
        suffix_list = ", ".join(f"`{s}`" for s in _SO_VALID_SUFFIXES[:3])
        out.append(
            _emit(
                "NMU010",
                r["asset_path"],
                t,
                f"ScriptableObject `{name}` should end with {suffix_list}, etc.",
                fix_suggestion=f"{name}_Data",
            )
        )
    return out


# ── NMU011 ──────────────────────────────────────────────────────────────────

_PBR_SUFFIXES = (
    "_Albedo",
    "_BaseColor",
    "_Normal",
    "_Metallic",
    "_Roughness",
    "_AO",
    "_MaskMap",
    "_Emissive",
    "_Height",
)


def detect_unity_texture_pbr_suffix(records: List[AssetRecord]) -> List[Issue]:
    """Texture2D asset has no PBR channel suffix (_Albedo, _Normal,
    _Metallic, etc.). Without one it's impossible to tell from the
    name whether a file is the albedo, normal map, or metallic map.
    Add a suffix matching the texture's role (_Albedo/_BaseColor,
    _Normal, _Metallic, _Roughness, _AO, _MaskMap, _Emissive).
    """
    out: List[Issue] = []
    for r in records:
        t = (r.get("asset_type") or "").strip()
        if t != "Texture2D":
            continue
        name = _name_of(r.get("asset_path", ""))
        if not name:
            continue
        if any(name.endswith(suf) for suf in _PBR_SUFFIXES):
            continue
        suffix_list = ", ".join(f"`{s}`" for s in _PBR_SUFFIXES[:4])
        out.append(
            _emit(
                "NMU011",
                r["asset_path"],
                t,
                f"Texture `{name}` is missing a PBR channel suffix"
                f" ({suffix_list}, …).",
            )
        )
    return out


# ── NMU012 ──────────────────────────────────────────────────────────────────


def detect_unity_uppercase_extension(records: List[AssetRecord]) -> List[Issue]:
    """Asset file extension contains uppercase letters.

    Unity's import pipeline is case-sensitive on Linux (CI and Linux
    builds). `Hero.PNG` and `Hero.png` are the same asset on Windows
    but different on Linux, so this causes import failures that only
    show up in CI. Use a lowercase extension.
    """
    out: List[Issue] = []
    for r in records:
        path = r.get("asset_path") or ""
        ext = Path(path).suffix
        if not ext:
            continue
        if ext == ext.lower():
            continue
        fixed_path = str(Path(path).with_suffix(ext.lower())).replace("\\", "/")
        out.append(
            _emit(
                "NMU012",
                r["asset_path"],
                r.get("asset_type", ""),
                f"Extension `{ext}` should be lowercase"
                f" `{ext.lower()}` (Linux/CI safety).",
                fix_suggestion=fixed_path,
            )
        )
    return out


# ── NMU013 ──────────────────────────────────────────────────────────────────


def detect_unity_parent_dir_in_path(records: List[AssetRecord]) -> List[Issue]:
    """Asset path contains a parent-directory traversal (`..`).

    Paths with `..` components resolve to a location outside the folder
    they appear to be in, which breaks AssetDatabase lookups, addressable
    groups, and cross-platform builds. Normalise the path to remove all
    `..` segments.
    """
    out: List[Issue] = []
    for r in records:
        path = (r.get("asset_path") or "").replace("\\", "/")
        if ".." in path.split("/"):
            out.append(
                _emit(
                    "NMU013",
                    r["asset_path"],
                    r.get("asset_type", ""),
                    "Path contains `..` traversal segments;"
                    " use the canonical absolute path.",
                )
            )
    return out


# ── NMU014 ──────────────────────────────────────────────────────────────────


def detect_unity_double_slash(records: List[AssetRecord]) -> List[Issue]:
    """Asset path contains consecutive forward slashes (`//`).

    Double slashes cause AssetDatabase.LoadAssetAtPath to fail silently —
    the asset exists on disk but cannot be found at runtime. This typically
    results from incorrect string concatenation when building paths
    programmatically. Collapse every `//` to a single `/`.
    """
    out: List[Issue] = []
    for r in records:
        path = (r.get("asset_path") or "").replace("\\", "/")
        if "//" in path:
            fixed = path
            while "//" in fixed:
                fixed = fixed.replace("//", "/")
            out.append(
                _emit(
                    "NMU014",
                    r["asset_path"],
                    r.get("asset_type", ""),
                    "Path contains `//`; collapse to a single `/`.",
                    fix_suggestion=fixed,
                )
            )
    return out


# ── NMU015 ──────────────────────────────────────────────────────────────────

_AUDIO_VALID_SUFFIXES = ("_SFX", "_Music", "_Ambient", "_VO", "_UI", "_Stinger")


def detect_unity_audio_missing_suffix(records: List[AssetRecord]) -> List[Issue]:
    """AudioClip asset lacks a category suffix (_SFX, _Music, _Ambient,
    _VO, _UI). Unity projects commonly organise audio by role —
    _SFX (sound effects), _Music (background tracks), _Ambient
    (environment loops), _VO (voice-over), _UI (interface feedback) —
    so the wrong clip doesn't get assigned to the wrong source.
    """
    out: List[Issue] = []
    for r in records:
        t = (r.get("asset_type") or "").strip()
        if t != "AudioClip":
            continue
        name = _name_of(r.get("asset_path", ""))
        if not name:
            continue
        if any(name.endswith(suf) for suf in _AUDIO_VALID_SUFFIXES):
            continue
        suffix_list = ", ".join(f"`{s}`" for s in _AUDIO_VALID_SUFFIXES[:4])
        out.append(
            _emit(
                "NMU015",
                r["asset_path"],
                t,
                f"AudioClip `{name}` is missing a category suffix"
                f" ({suffix_list}, …).",
            )
        )
    return out


# ── NMU016 ──────────────────────────────────────────────────────────────────


def detect_unity_wrong_prefix_for_type(records: List[AssetRecord]) -> List[Issue]:
    """Name carries a known prefix but it's the wrong one for the asset
    type — e.g. a Material named `T_Concrete.mat` should be
    `M_Concrete.mat`.

    Skips assets with no prefix at all (NMU001 covers that) and
    asset_types we don't map.
    """
    out: List[Issue] = []
    for r in records:
        t = (r.get("asset_type") or "").strip()
        expected_prefix = _UNITY_TYPE_TO_PREFIX.get(t)
        if not expected_prefix:
            continue
        name = _name_of(r.get("asset_path", ""))
        if "_" not in name:
            continue  # no prefix at all — NMU001 handles this case
        current = name.split("_", 1)[0]
        if current == expected_prefix:
            continue
        if current not in _KNOWN_PREFIXES:
            continue  # not a recognised prefix; NMU001 will flag missing
        rest = name.split("_", 1)[1]
        out.append(
            _emit(
                "NMU016",
                r["asset_path"],
                t,
                f"{t} uses prefix `{current}_` but should use `{expected_prefix}_`.",
                fix_suggestion=f"{expected_prefix}_{rest}",
            )
        )
    return out
