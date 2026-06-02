# core/modules/lod_auditor/tests/test_lod_textures.py

from lod_auditor.rules.lod_textures import (
    check_lt001,
    check_lt002,
    check_lt003,
    check_lt004,
    check_lt005,
)

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
