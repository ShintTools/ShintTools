"""Tests for all 15 Unity asset naming rules (NMU001-NMU016).

Each rule has: positive case (fires), negative case (does not fire),
and at least one edge case. Convention: tests assert on the rule_id
field of returned issues rather than on the message text so that
wording changes never break the suite.
"""

import sys
from pathlib import Path

_CORE = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, _CORE)
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "modules"))

from naming.unity.unity_naming_rules import (  # noqa: E402
    detect_unity_audio_missing_suffix,
    detect_unity_backslash_in_path,
    detect_unity_double_slash,
    detect_unity_editor_folder_misuse,
    detect_unity_missing_prefix,
    detect_unity_parent_dir_in_path,
    detect_unity_path_outside_assets,
    detect_unity_resources_folder,
    detect_unity_scene_misplaced,
    detect_unity_script_misplaced,
    detect_unity_scriptableobject_suffix,
    detect_unity_streaming_assets,
    detect_unity_texture_pbr_suffix,
    detect_unity_uppercase_extension,
    detect_unity_wrong_folder,
    detect_unity_wrong_prefix_for_type,
)


def _ids(issues):
    return [i["rule_id"] for i in issues]


# ────────────────────────────────────────────────────────────
# NMU001 — missing type prefix
# ────────────────────────────────────────────────────────────


def test_nmu001_fires_when_prefix_missing():
    r = [{"asset_path": "Assets/Textures/Hero.png", "asset_type": "Texture2D"}]
    assert "NMU001" in _ids(detect_unity_missing_prefix(r))


def test_nmu001_passes_when_prefix_correct():
    r = [{"asset_path": "Assets/Textures/T_Hero.png", "asset_type": "Texture2D"}]
    assert "NMU001" not in _ids(detect_unity_missing_prefix(r))


def test_nmu001_skips_unknown_type():
    r = [{"asset_path": "Assets/Stuff/Foo.asset", "asset_type": "CustomWidget"}]
    assert detect_unity_missing_prefix(r) == []


def test_nmu001_fix_suggestion():
    r = [{"asset_path": "Assets/Textures/Hero.png", "asset_type": "Texture2D"}]
    issues = detect_unity_missing_prefix(r)
    assert issues[0]["fix_suggestion"] == "T_Hero"


# ────────────────────────────────────────────────────────────
# NMU009 — wrong folder for type
# ────────────────────────────────────────────────────────────


def test_nmu009_fires_when_texture_not_in_textures():
    r = [{"asset_path": "Assets/Audio/T_Hero.png", "asset_type": "Texture2D"}]
    assert "NMU009" in _ids(detect_unity_wrong_folder(r))


def test_nmu009_passes_when_folder_matches():
    r = [{"asset_path": "Assets/Textures/T_Hero.png", "asset_type": "Texture2D"}]
    assert detect_unity_wrong_folder(r) == []


def test_nmu009_passes_nested_textures_folder():
    r = [
        {
            "asset_path": "Assets/Characters/Textures/T_Hero.png",
            "asset_type": "Texture2D",
        }
    ]
    assert detect_unity_wrong_folder(r) == []


def test_nmu009_skips_unknown_type():
    r = [{"asset_path": "Assets/Misc/Foo.asset", "asset_type": "CustomWidget"}]
    assert detect_unity_wrong_folder(r) == []


# ────────────────────────────────────────────────────────────
# NMU015 — AudioClip missing category suffix
# ────────────────────────────────────────────────────────────


def test_nmu015_fires_when_audioclip_has_no_suffix():
    r = [{"asset_path": "Assets/Audio/Audio_Footstep.wav", "asset_type": "AudioClip"}]
    assert "NMU015" in _ids(detect_unity_audio_missing_suffix(r))


def test_nmu015_passes_when_audioclip_has_sfx_suffix():
    r = [
        {"asset_path": "Assets/Audio/Audio_Footstep_SFX.wav", "asset_type": "AudioClip"}
    ]
    assert detect_unity_audio_missing_suffix(r) == []


def test_nmu015_passes_when_audioclip_has_music_suffix():
    r = [{"asset_path": "Assets/Audio/Track_Menu_Music.wav", "asset_type": "AudioClip"}]
    assert detect_unity_audio_missing_suffix(r) == []


def test_nmu015_skips_non_audio_types():
    r = [{"asset_path": "Assets/Textures/T_Hero.png", "asset_type": "Texture2D"}]
    assert detect_unity_audio_missing_suffix(r) == []


# ────────────────────────────────────────────────────────────
# NMU016 — wrong prefix for type
# ────────────────────────────────────────────────────────────


def test_nmu016_fires_when_prefix_wrong_for_type():
    r = [{"asset_path": "Assets/Materials/T_Concrete.mat", "asset_type": "Material"}]
    assert "NMU016" in _ids(detect_unity_wrong_prefix_for_type(r))


def test_nmu016_passes_when_prefix_correct():
    r = [{"asset_path": "Assets/Materials/M_Concrete.mat", "asset_type": "Material"}]
    assert detect_unity_wrong_prefix_for_type(r) == []


def test_nmu016_skips_when_no_prefix():
    # No prefix at all → NMU001 handles it; NMU016 must stay silent
    r = [{"asset_path": "Assets/Materials/Concrete.mat", "asset_type": "Material"}]
    assert detect_unity_wrong_prefix_for_type(r) == []


def test_nmu016_fix_suggestion():
    r = [{"asset_path": "Assets/Materials/T_Concrete.mat", "asset_type": "Material"}]
    issues = detect_unity_wrong_prefix_for_type(r)
    assert issues[0]["fix_suggestion"] == "M_Concrete"


# ────────────────────────────────────────────────────────────
# NMU002 — path outside Assets/
# ────────────────────────────────────────────────────────────


def test_nmu002_fires_when_path_outside_assets():
    r = [{"asset_path": "Content/Textures/T_Hero.png", "asset_type": "Texture2D"}]
    assert "NMU002" in _ids(detect_unity_path_outside_assets(r))


def test_nmu002_passes_when_path_starts_with_assets():
    r = [{"asset_path": "Assets/Textures/T_Hero.png", "asset_type": "Texture2D"}]
    assert detect_unity_path_outside_assets(r) == []


def test_nmu002_passes_for_assets_root():
    r = [{"asset_path": "Assets", "asset_type": "DefaultAsset"}]
    assert detect_unity_path_outside_assets(r) == []


def test_nmu002_skips_empty_path():
    r = [{"asset_path": "", "asset_type": "Texture2D"}]
    assert detect_unity_path_outside_assets(r) == []


# ────────────────────────────────────────────────────────────
# NMU003 — backslash in path
# ────────────────────────────────────────────────────────────


def test_nmu003_fires_when_backslash_present():
    r = [{"asset_path": "Assets\\Textures\\T_Hero.png", "asset_type": "Texture2D"}]
    assert "NMU003" in _ids(detect_unity_backslash_in_path(r))


def test_nmu003_passes_when_no_backslash():
    r = [{"asset_path": "Assets/Textures/T_Hero.png", "asset_type": "Texture2D"}]
    assert detect_unity_backslash_in_path(r) == []


def test_nmu003_fix_suggestion_converts_slashes():
    r = [{"asset_path": "Assets\\Textures\\T_Hero.png", "asset_type": "Texture2D"}]
    issues = detect_unity_backslash_in_path(r)
    assert issues[0]["fix_suggestion"] == "Assets/Textures/T_Hero.png"


# ────────────────────────────────────────────────────────────
# NMU004 — C# script in wrong folder
# ────────────────────────────────────────────────────────────


def test_nmu004_fires_when_cs_outside_valid_folder():
    r = [{"asset_path": "Assets/Textures/MyScript.cs", "asset_type": "MonoScript"}]
    assert "NMU004" in _ids(detect_unity_script_misplaced(r))


def test_nmu004_passes_when_cs_in_scripts():
    r = [{"asset_path": "Assets/Scripts/MyScript.cs", "asset_type": "MonoScript"}]
    assert detect_unity_script_misplaced(r) == []


def test_nmu004_passes_when_cs_in_editor():
    r = [{"asset_path": "Assets/Editor/MyEditorScript.cs", "asset_type": "MonoScript"}]
    assert detect_unity_script_misplaced(r) == []


def test_nmu004_passes_when_cs_in_plugins():
    r = [
        {"asset_path": "Assets/Plugins/Vendor/LibHelper.cs", "asset_type": "MonoScript"}
    ]
    assert detect_unity_script_misplaced(r) == []


def test_nmu004_skips_non_cs_files():
    r = [{"asset_path": "Assets/Textures/T_Hero.png", "asset_type": "Texture2D"}]
    assert detect_unity_script_misplaced(r) == []


# ────────────────────────────────────────────────────────────
# NMU005 — asset inside Resources/
# ────────────────────────────────────────────────────────────


def test_nmu005_fires_when_inside_resources():
    r = [{"asset_path": "Assets/Resources/T_Hero.png", "asset_type": "Texture2D"}]
    assert "NMU005" in _ids(detect_unity_resources_folder(r))


def test_nmu005_fires_when_nested_under_resources():
    r = [
        {"asset_path": "Assets/Game/Resources/UI/T_Icon.png", "asset_type": "Texture2D"}
    ]
    assert "NMU005" in _ids(detect_unity_resources_folder(r))


def test_nmu005_passes_when_not_in_resources():
    r = [{"asset_path": "Assets/Textures/T_Hero.png", "asset_type": "Texture2D"}]
    assert detect_unity_resources_folder(r) == []


def test_nmu005_does_not_fire_on_resources_in_filename():
    # "Resources" in filename only, not as a folder segment
    r = [{"asset_path": "Assets/Data/GameResources.asset", "asset_type": "TextAsset"}]
    assert detect_unity_resources_folder(r) == []


# ────────────────────────────────────────────────────────────
# NMU006 — asset inside StreamingAssets/
# ────────────────────────────────────────────────────────────


def test_nmu006_fires_when_inside_streaming_assets():
    r = [
        {"asset_path": "Assets/StreamingAssets/video.mp4", "asset_type": "DefaultAsset"}
    ]
    assert "NMU006" in _ids(detect_unity_streaming_assets(r))


def test_nmu006_passes_when_not_in_streaming_assets():
    r = [{"asset_path": "Assets/Videos/video.mp4", "asset_type": "DefaultAsset"}]
    assert detect_unity_streaming_assets(r) == []


# ────────────────────────────────────────────────────────────
# NMU007 — runtime asset under Editor/
# ────────────────────────────────────────────────────────────


def test_nmu007_fires_when_prefab_under_editor():
    r = [{"asset_path": "Assets/Editor/P_Button.prefab", "asset_type": "GameObject"}]
    assert "NMU007" in _ids(detect_unity_editor_folder_misuse(r))


def test_nmu007_passes_for_cs_file_under_editor():
    r = [{"asset_path": "Assets/Editor/MyInspector.cs", "asset_type": "MonoScript"}]
    assert detect_unity_editor_folder_misuse(r) == []


def test_nmu007_passes_for_editor_specific_type():
    r = [
        {
            "asset_path": "Assets/Editor/EditorBuildSettings.asset",
            "asset_type": "EditorBuildSettings",
        }
    ]
    assert detect_unity_editor_folder_misuse(r) == []


def test_nmu007_passes_when_not_under_editor():
    r = [{"asset_path": "Assets/Prefabs/P_Button.prefab", "asset_type": "GameObject"}]
    assert detect_unity_editor_folder_misuse(r) == []


# ────────────────────────────────────────────────────────────
# NMU008 — scene not in Scenes/
# ────────────────────────────────────────────────────────────


def test_nmu008_fires_when_scene_outside_scenes_folder():
    r = [{"asset_path": "Assets/Levels/MainMenu.unity", "asset_type": "SceneAsset"}]
    assert "NMU008" in _ids(detect_unity_scene_misplaced(r))


def test_nmu008_passes_when_scene_in_scenes_folder():
    r = [{"asset_path": "Assets/Scenes/MainMenu.unity", "asset_type": "SceneAsset"}]
    assert detect_unity_scene_misplaced(r) == []


def test_nmu008_skips_non_scene_assets():
    r = [{"asset_path": "Assets/Levels/T_Hero.png", "asset_type": "Texture2D"}]
    assert detect_unity_scene_misplaced(r) == []


# ────────────────────────────────────────────────────────────
# NMU010 — ScriptableObject missing suffix
# ────────────────────────────────────────────────────────────


def test_nmu010_fires_when_so_has_no_suffix():
    r = [
        {
            "asset_path": "Assets/Data/SO_EnemyStats.asset",
            "asset_type": "ScriptableObject",
        }
    ]
    assert "NMU010" in _ids(detect_unity_scriptableobject_suffix(r))


def test_nmu010_passes_when_so_has_data_suffix():
    r = [
        {
            "asset_path": "Assets/Data/SO_EnemyStats_Data.asset",
            "asset_type": "ScriptableObject",
        }
    ]
    assert detect_unity_scriptableobject_suffix(r) == []


def test_nmu010_passes_when_so_has_config_suffix():
    r = [
        {
            "asset_path": "Assets/Config/SO_GraphicsSettings_Config.asset",
            "asset_type": "ScriptableObject",
        }
    ]
    assert detect_unity_scriptableobject_suffix(r) == []


def test_nmu010_skips_non_so_types():
    r = [{"asset_path": "Assets/Data/SomeFile.asset", "asset_type": "TextAsset"}]
    assert detect_unity_scriptableobject_suffix(r) == []


def test_nmu010_fix_suggestion_appends_data():
    r = [
        {
            "asset_path": "Assets/Data/SO_EnemyStats.asset",
            "asset_type": "ScriptableObject",
        }
    ]
    issues = detect_unity_scriptableobject_suffix(r)
    assert issues[0]["fix_suggestion"] == "SO_EnemyStats_Data"


# ────────────────────────────────────────────────────────────
# NMU011 — Texture2D missing PBR suffix
# ────────────────────────────────────────────────────────────


def test_nmu011_fires_when_texture_has_no_pbr_suffix():
    r = [{"asset_path": "Assets/Textures/T_Rock.png", "asset_type": "Texture2D"}]
    assert "NMU011" in _ids(detect_unity_texture_pbr_suffix(r))


def test_nmu011_passes_when_texture_has_albedo_suffix():
    r = [{"asset_path": "Assets/Textures/T_Rock_Albedo.png", "asset_type": "Texture2D"}]
    assert detect_unity_texture_pbr_suffix(r) == []


def test_nmu011_passes_when_texture_has_normal_suffix():
    r = [{"asset_path": "Assets/Textures/T_Rock_Normal.png", "asset_type": "Texture2D"}]
    assert detect_unity_texture_pbr_suffix(r) == []


def test_nmu011_passes_when_texture_has_maskmap_suffix():
    r = [
        {"asset_path": "Assets/Textures/T_Rock_MaskMap.png", "asset_type": "Texture2D"}
    ]
    assert detect_unity_texture_pbr_suffix(r) == []


def test_nmu011_skips_non_texture_types():
    r = [{"asset_path": "Assets/Materials/M_Rock.mat", "asset_type": "Material"}]
    assert detect_unity_texture_pbr_suffix(r) == []


# ────────────────────────────────────────────────────────────
# NMU012 — uppercase extension
# ────────────────────────────────────────────────────────────


def test_nmu012_fires_when_extension_uppercase():
    r = [{"asset_path": "Assets/Textures/T_Hero.PNG", "asset_type": "Texture2D"}]
    assert "NMU012" in _ids(detect_unity_uppercase_extension(r))


def test_nmu012_passes_when_extension_lowercase():
    r = [{"asset_path": "Assets/Textures/T_Hero.png", "asset_type": "Texture2D"}]
    assert detect_unity_uppercase_extension(r) == []


def test_nmu012_fires_for_mixed_case_extension():
    r = [{"asset_path": "Assets/Textures/T_Hero.Png", "asset_type": "Texture2D"}]
    assert "NMU012" in _ids(detect_unity_uppercase_extension(r))


def test_nmu012_fix_suggestion_lowercases_extension():
    r = [{"asset_path": "Assets/Textures/T_Hero.PNG", "asset_type": "Texture2D"}]
    issues = detect_unity_uppercase_extension(r)
    assert issues[0]["fix_suggestion"].endswith(".png")


# ────────────────────────────────────────────────────────────
# NMU013 — parent-directory traversal in path
# ────────────────────────────────────────────────────────────


def test_nmu013_fires_when_path_has_dotdot():
    r = [{"asset_path": "Assets/../Textures/T_Hero.png", "asset_type": "Texture2D"}]
    assert "NMU013" in _ids(detect_unity_parent_dir_in_path(r))


def test_nmu013_passes_when_no_dotdot():
    r = [{"asset_path": "Assets/Textures/T_Hero.png", "asset_type": "Texture2D"}]
    assert detect_unity_parent_dir_in_path(r) == []


def test_nmu013_does_not_fire_on_filename_with_dots():
    # "v2.0.1" in file name is not ".." as a path segment
    r = [{"asset_path": "Assets/Data/config.v2.0.asset", "asset_type": "TextAsset"}]
    assert detect_unity_parent_dir_in_path(r) == []


# ────────────────────────────────────────────────────────────
# NMU014 — double slashes in path
# ────────────────────────────────────────────────────────────


def test_nmu014_fires_when_path_has_double_slash():
    r = [{"asset_path": "Assets//Textures/T_Hero.png", "asset_type": "Texture2D"}]
    assert "NMU014" in _ids(detect_unity_double_slash(r))


def test_nmu014_passes_when_no_double_slash():
    r = [{"asset_path": "Assets/Textures/T_Hero.png", "asset_type": "Texture2D"}]
    assert detect_unity_double_slash(r) == []


def test_nmu014_fix_suggestion_collapses_slashes():
    r = [{"asset_path": "Assets//Textures//T_Hero.png", "asset_type": "Texture2D"}]
    issues = detect_unity_double_slash(r)
    assert "//" not in issues[0]["fix_suggestion"]
    assert issues[0]["fix_suggestion"] == "Assets/Textures/T_Hero.png"
