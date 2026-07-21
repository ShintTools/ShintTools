# core/modules/lod_auditor/tests/test_lod_textures.py

import copy

from lod_auditor.rules.lod_textures import (
    THRESHOLDS,
    check_lt001,
    check_lt002,
    check_lt003,
    check_lt004,
    check_lt005,
    check_lt006,
    check_lt007,
    check_lt008,
)


def _thresholds(**overrides) -> dict:
    """A copy of the default thresholds with specific keys overridden."""
    t = copy.deepcopy(THRESHOLDS)
    t.update(overrides)
    return t


# ── Base fixture ──────────────────────────────────────────────────────────────

_BASE: dict = {
    "asset_path": "/Game/T_Test",
    "asset_type": "Texture2D",
    "usage": "BaseColor",
    "width": 2048,
    "height": 2048,
    "compression": "BC7",
    "srgb": True,
    "mips_enabled": True,
    "mip_count": 12,
    "streaming": True,
    "lod_group": "World",
    "max_texture_size": 2048,
    "referenced_by_materials": 1,
}


def _tex(**overrides) -> dict:
    return {**_BASE, **overrides}


# ── LT001 ─────────────────────────────────────────────────────────────────────


class TestLT001:
    def test_fires_when_normal_uses_bc7(self):
        result = check_lt001(_tex(usage="Normal", compression="BC7"))
        assert result is not None
        assert result.rule_id == "LT001"

    def test_no_finding_when_normal_uses_bc5(self):
        assert check_lt001(_tex(usage="Normal", compression="BC5")) is None

    def test_fires_when_hdr_uses_bc7_recommends_bc6h(self):
        result = check_lt001(_tex(usage="HDR", compression="BC7"))
        assert result is not None
        assert result.recommended["compression"] == "BC6H"

    def test_fires_when_mask_uses_bc7_recommends_bc4(self):
        result = check_lt001(_tex(usage="Mask", compression="BC7"))
        assert result is not None
        assert result.recommended["compression"] == "BC4"

    def test_no_finding_for_optimal_basecolor_bc7(self):
        assert check_lt001(_tex(usage="BaseColor", compression="BC7")) is None

    def test_no_finding_for_ui_rgba8(self):
        assert check_lt001(_tex(usage="UI", compression="RGBA8")) is None

    def test_ue5_tc_normalmap_treated_as_bc5(self):
        # TC_Normalmap normalises to BC5 → no finding for Normal usage
        assert check_lt001(_tex(usage="Normal", compression="TC_Normalmap")) is None

    def test_auto_fixable_is_true(self):
        result = check_lt001(_tex(usage="Normal", compression="BC7"))
        assert result.auto_fixable is True

    def test_unknown_usage_produces_no_finding(self):
        assert check_lt001(_tex(usage="Lightmap", compression="BC5")) is None


# ── LT002 ─────────────────────────────────────────────────────────────────────


class TestLT002:
    def test_fires_when_basecolor_missing_mips(self):
        result = check_lt002(_tex(usage="BaseColor", mips_enabled=False))
        assert result is not None
        assert result.rule_id == "LT002"

    def test_fires_when_normal_missing_mips(self):
        result = check_lt002(_tex(usage="Normal", mips_enabled=False))
        assert result is not None
        assert result.recommended["mips_enabled"] is True

    def test_fires_when_ui_has_mips(self):
        result = check_lt002(_tex(usage="UI", mips_enabled=True))
        assert result is not None
        assert result.recommended["mips_enabled"] is False

    def test_no_finding_for_basecolor_with_mips(self):
        assert check_lt002(_tex(usage="BaseColor", mips_enabled=True)) is None

    def test_no_finding_for_ui_without_mips(self):
        assert check_lt002(_tex(usage="UI", mips_enabled=False)) is None

    def test_auto_fixable_is_true(self):
        result = check_lt002(_tex(usage="UI", mips_enabled=True))
        assert result.auto_fixable is True


# ── LT003 ─────────────────────────────────────────────────────────────────────


class TestLT003:
    def test_fires_when_4k_in_world_group(self):
        result = check_lt003(_tex(width=4096, height=4096, lod_group="World"))
        assert result is not None
        assert result.rule_id == "LT003"

    def test_recommended_size_matches_group_budget(self):
        result = check_lt003(_tex(width=4096, height=4096, lod_group="World"))
        assert result.recommended["max_texture_size"] == 2048

    def test_no_finding_for_2k_in_world_group(self):
        assert check_lt003(_tex(width=2048, height=2048, lod_group="World")) is None

    def test_no_finding_for_4k_in_cinematic_group(self):
        # Cinematic budget is 4096 px
        assert check_lt003(_tex(width=4096, height=4096, lod_group="Cinematic")) is None

    def test_no_finding_for_1k_in_ui_group(self):
        assert check_lt003(_tex(width=1024, height=1024, lod_group="UI")) is None

    def test_fires_for_2k_in_ui_group(self):
        result = check_lt003(_tex(width=2048, height=2048, lod_group="UI"))
        assert result is not None
        assert result.recommended["max_texture_size"] == 1024

    def test_vram_saving_is_positive(self):
        result = check_lt003(_tex(width=4096, height=4096, lod_group="World"))
        assert result.estimated_saving.vram_mb > 0

    def test_auto_fixable_is_true(self):
        result = check_lt003(_tex(width=4096, height=4096, lod_group="World"))
        assert result.auto_fixable is True

    def test_unknown_lod_group_uses_default_budget(self):
        # Unknown group → default 2048
        result = check_lt003(_tex(width=4096, height=4096, lod_group="Custom"))
        assert result is not None
        assert result.recommended["max_texture_size"] == 2048

    def test_unity_wording_differs_but_budget_matches_unreal(self):
        # engine only changes the message copy — the numeric budget must be
        # identical for the same profile (no engine dimension in the YAML).
        tex = _tex(width=4096, height=4096, lod_group="World")
        result_ue5 = check_lt003(tex, engine="unreal")
        result_unity = check_lt003(tex, engine="unity")
        assert result_ue5 is not None and result_unity is not None
        assert "slot budget" in result_ue5.message
        assert "max-size budget" in result_unity.message
        assert result_ue5.recommended == result_unity.recommended

    def test_mobile_profile_lowers_unity_budget(self):
        # The mobile threshold profile — not the engine — is what a Unity
        # mobile project should select to get a stricter budget.
        tex = _tex(width=2048, height=2048, lod_group="World")
        default_result = check_lt003(tex, engine="unity")
        mobile_result = check_lt003(
            tex, engine="unity", thresholds=_thresholds(LT003_MAX_SIZE_BY_LOD_GROUP={
                **THRESHOLDS["LT003_MAX_SIZE_BY_LOD_GROUP"], "World": 1024,
            }),
        )
        assert default_result is None
        assert mobile_result is not None
        assert mobile_result.recommended["max_texture_size"] == 1024


# ── LT004 ─────────────────────────────────────────────────────────────────────


class TestLT004:
    def test_fires_when_normal_has_srgb(self):
        result = check_lt004(_tex(usage="Normal", srgb=True))
        assert result is not None
        assert result.rule_id == "LT004"
        assert result.recommended["srgb"] is False

    def test_fires_when_mask_has_srgb(self):
        result = check_lt004(_tex(usage="Mask", srgb=True))
        assert result is not None

    def test_fires_when_basecolor_missing_srgb(self):
        result = check_lt004(_tex(usage="BaseColor", srgb=False))
        assert result is not None
        assert result.recommended["srgb"] is True

    def test_no_finding_for_normal_without_srgb(self):
        assert check_lt004(_tex(usage="Normal", srgb=False)) is None

    def test_no_finding_for_basecolor_with_srgb(self):
        assert check_lt004(_tex(usage="BaseColor", srgb=True)) is None

    def test_no_finding_for_unknown_usage(self):
        assert check_lt004(_tex(usage="Lightmap", srgb=True)) is None

    def test_auto_fixable_is_true(self):
        result = check_lt004(_tex(usage="Normal", srgb=True))
        assert result.auto_fixable is True


# ── LT005 ─────────────────────────────────────────────────────────────────────


class TestLT005:
    def test_fires_for_2k_texture_no_streaming(self):
        result = check_lt005(_tex(width=2048, height=2048, streaming=False))
        assert result is not None
        assert result.rule_id == "LT005"

    def test_fires_for_4k_texture_no_streaming(self):
        result = check_lt005(_tex(width=4096, height=4096, streaming=False))
        assert result is not None

    def test_no_finding_when_streaming_enabled(self):
        assert check_lt005(_tex(width=4096, height=4096, streaming=True)) is None

    def test_no_finding_for_small_texture_no_streaming(self):
        # Below 2048 threshold → streaming policy doesn't apply
        assert check_lt005(_tex(width=1024, height=1024, streaming=False)) is None

    def test_severity_is_info(self):
        result = check_lt005(_tex(width=2048, height=2048, streaming=False))
        assert result.severity == "info"

    def test_current_contains_resident_vram(self):
        result = check_lt005(_tex(width=4096, height=4096, streaming=False))
        assert result.current["resident_vram_mb"] > 0

    def test_auto_fixable_is_true(self):
        result = check_lt005(_tex(width=2048, height=2048, streaming=False))
        assert result.auto_fixable is True


# ── LT006 ─────────────────────────────────────────────────────────────────────


class TestLT006:
    def test_fires_for_npot_world_texture(self):
        result = check_lt006(_tex(width=1500, height=1500, lod_group="World"))
        assert result is not None
        assert result.rule_id == "LT006"

    def test_recommends_floor_power_of_two(self):
        result = check_lt006(_tex(width=1500, height=900, lod_group="World"))
        assert result.recommended == {"width": 1024, "height": 512}

    def test_no_finding_for_power_of_two(self):
        assert check_lt006(_tex(width=2048, height=1024)) is None

    def test_no_finding_for_ui_group(self):
        # UI textures are exempt — NPOT is idiomatic there.
        assert check_lt006(_tex(width=1500, height=900, lod_group="UI")) is None

    def test_no_finding_below_min_edge(self):
        assert check_lt006(_tex(width=100, height=60, lod_group="World")) is None

    def test_one_npot_edge_is_enough(self):
        # POT width but NPOT height still pads on the GPU.
        result = check_lt006(_tex(width=1024, height=900, lod_group="World"))
        assert result is not None

    def test_unity_wording_differs_but_recommendation_matches_unreal(self):
        tex = _tex(width=1500, height=900, lod_group="World")
        result_ue5 = check_lt006(tex, engine="unreal")
        result_unity = check_lt006(tex, engine="unity")
        assert result_ue5 is not None and result_unity is not None
        assert "UE5 pads it" in result_ue5.message
        assert "disable block compression" in result_unity.message
        assert result_ue5.recommended == result_unity.recommended == {
            "width": 1024, "height": 512,
        }


# ── LT007 ─────────────────────────────────────────────────────────────────────


class TestLT007:
    def test_fires_for_uncompressed_large(self):
        result = check_lt007(_tex(width=512, height=512, compression="RGBA8"))
        assert result is not None
        assert result.rule_id == "LT007"
        assert result.recommended["compression"] == "BC7"

    def test_recognises_ue5_uncompressed_alias(self):
        # TC_VectorDisplacementmap normalises to RGBA8.
        result = check_lt007(
            _tex(width=512, height=512, compression="TC_VectorDisplacementmap")
        )
        assert result is not None

    def test_info_below_max_edge(self):
        # 512 is >= min (256) but < max (1024) → minor, info severity.
        result = check_lt007(_tex(width=512, height=512, compression="RGBA8"))
        assert result.severity == "info"

    def test_warning_at_or_above_max_edge(self):
        # Default max edge is 1024 → a 2K uncompressed texture is a warning.
        result = check_lt007(_tex(width=2048, height=2048, compression="RGBA8"))
        assert result.severity == "warning"

    def test_vram_saving_is_positive(self):
        result = check_lt007(_tex(width=1024, height=1024, compression="RGBA8"))
        assert result.estimated_saving.vram_mb > 0

    def test_no_finding_for_compressed(self):
        assert check_lt007(_tex(width=2048, height=2048, compression="BC7")) is None

    def test_no_finding_below_min_edge(self):
        assert check_lt007(_tex(width=128, height=128, compression="RGBA8")) is None


# ── LT008 ─────────────────────────────────────────────────────────────────────


class TestLT008:
    def test_fires_when_rdo_disabled_on_bc7(self):
        result = check_lt008(
            _tex(width=2048, height=2048, compression="BC7", rdo_enabled=False)
        )
        assert result is not None
        assert result.rule_id == "LT008"

    def test_saving_is_build_size_not_vram(self):
        result = check_lt008(
            _tex(width=2048, height=2048, compression="BC7", rdo_enabled=False)
        )
        assert result.estimated_saving.vram_mb == 0.0
        assert result.estimated_saving.build_size_mb > 0
        assert result.severity == "info"

    def test_silent_when_rdo_field_absent(self):
        # No rdo_enabled key → older client, stay quiet rather than guess.
        assert check_lt008(_tex(width=2048, height=2048, compression="BC7")) is None

    def test_silent_when_rdo_enabled(self):
        assert (
            check_lt008(
                _tex(width=2048, height=2048, compression="BC7", rdo_enabled=True)
            )
            is None
        )

    def test_no_finding_for_uncompressed_format(self):
        # RDO has nothing to shrink on RGBA8.
        assert (
            check_lt008(
                _tex(width=2048, height=2048, compression="RGBA8", rdo_enabled=False)
            )
            is None
        )

    def test_no_finding_below_min_edge(self):
        assert (
            check_lt008(
                _tex(width=128, height=128, compression="BC7", rdo_enabled=False)
            )
            is None
        )


# ── Per-request threshold overrides (thresholds= kwarg) ───────────────────────


class TestThresholdParam:
    def test_lt003_global_ceiling_flags_under_budget_texture(self):
        # 2048 World is within the per-group budget (2048) but a 1024 global
        # ceiling makes it over budget and pins the recommendation to 1024.
        tex = _tex(width=2048, height=2048, lod_group="World")
        assert check_lt003(tex) is None
        result = check_lt003(tex, thresholds=_thresholds(LT003_GLOBAL_MAX_SIZE=1024))
        assert result is not None
        assert result.recommended["max_texture_size"] == 1024

    def test_lt003_ceiling_never_raises_a_tighter_group_budget(self):
        # A ceiling above the group budget must not loosen it (min wins).
        tex = _tex(width=4096, height=4096, lod_group="World")  # budget 2048
        result = check_lt003(tex, thresholds=_thresholds(LT003_GLOBAL_MAX_SIZE=8192))
        assert result is not None
        assert result.recommended["max_texture_size"] == 2048

    def test_lt007_raised_min_edge_silences_small_uncompressed(self):
        tex = _tex(width=512, height=512, compression="RGBA8")
        assert check_lt007(tex) is not None  # default min 256 → fires
        assert (
            check_lt007(tex, thresholds=_thresholds(LT007_UNCOMPRESSED_MIN_EDGE=1024))
            is None
        )

    def test_lt007_lowered_max_edge_escalates_to_warning(self):
        # 512 is info by default (max 1024); drop max to 256 → warning.
        tex = _tex(width=512, height=512, compression="RGBA8")
        assert check_lt007(tex).severity == "info"
        escalated = check_lt007(
            tex, thresholds=_thresholds(LT007_UNCOMPRESSED_MAX_EDGE=256)
        )
        assert escalated is not None
        assert escalated.severity == "warning"

    def test_lt006_raised_min_edge_silences_small_npot(self):
        tex = _tex(width=300, height=300, lod_group="World")
        assert check_lt006(tex) is not None  # default min 128 → fires
        assert check_lt006(tex, thresholds=_thresholds(LT006_NPOT_MIN_EDGE=512)) is None

    def test_lt005_lowered_min_edge_flags_smaller_texture(self):
        # 1024 non-streaming is below the default 2048 streaming min → silent;
        # lower the min to 512 and it should fire.
        tex = _tex(width=1024, height=1024, streaming=False)
        assert check_lt005(tex) is None
        assert (
            check_lt005(tex, thresholds=_thresholds(LT005_STREAMING_MIN_EDGE=512))
            is not None
        )
