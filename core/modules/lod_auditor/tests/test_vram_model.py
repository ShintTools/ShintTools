# core/modules/lod_auditor/tests/test_vram_model.py

import logging

from lod_auditor.vram_model import estimate_texture_vram_mb, normalize_compression


class TestNormalizeCompression:
    def test_ue5_tc_default_maps_to_bc7(self):
        assert normalize_compression("TC_Default") == "BC7"

    def test_ue5_tc_normalmap_maps_to_bc5(self):
        assert normalize_compression("TC_Normalmap") == "BC5"

    def test_ue5_tc_masks_maps_to_bc4(self):
        assert normalize_compression("TC_Masks") == "BC4"

    def test_ue5_tc_hdr_maps_to_bc6h(self):
        assert normalize_compression("TC_HDR") == "BC6H"

    def test_canonical_bc7_passes_through(self):
        assert normalize_compression("BC7") == "BC7"

    def test_canonical_rgba8_passes_through(self):
        assert normalize_compression("RGBA8") == "RGBA8"

    def test_unknown_format_passes_through_unchanged(self):
        # Unknown formats are returned as-is so the caller can decide.
        assert normalize_compression("ASTC_6x6") == "ASTC_6x6"


class TestEstimateTextureVramMb:
    def test_4096_bc7_with_mips_approx_21mb(self):
        # 4096² × 1.0 bpp × (4/3) / 1_048_576 ≈ 21.33 MB
        result = estimate_texture_vram_mb(4096, 4096, "BC7", with_mips=True)
        assert abs(result - 21.33) < 0.1

    def test_2048_bc7_with_mips_approx_5mb(self):
        result = estimate_texture_vram_mb(2048, 2048, "BC7", with_mips=True)
        assert abs(result - 5.33) < 0.1

    def test_4096_bc7_no_mips_equals_16mb(self):
        # 4096² × 1.0 bpp / 1_048_576 = exactly 16 MB
        result = estimate_texture_vram_mb(4096, 4096, "BC7", with_mips=False)
        assert result == 16.0

    def test_4096_bc1_half_cost_of_bc7(self):
        # BC1 = 0.5 bpp vs BC7 = 1.0 bpp → half the VRAM
        vram_bc1 = estimate_texture_vram_mb(4096, 4096, "BC1")
        vram_bc7 = estimate_texture_vram_mb(4096, 4096, "BC7")
        assert abs(vram_bc1 / vram_bc7 - 0.5) < 0.01

    def test_4k_to_2k_is_4x_reduction(self):
        # Halving each dimension → 1/4 the area → 1/4 the VRAM
        vram_4k = estimate_texture_vram_mb(4096, 4096, "BC7")
        vram_2k = estimate_texture_vram_mb(2048, 2048, "BC7")
        assert abs(vram_4k / vram_2k - 4.0) < 0.01

    def test_rgba8_more_expensive_than_bc7(self):
        # RGBA8 = 4 bpp vs BC7 = 1 bpp
        vram_rgba8 = estimate_texture_vram_mb(1024, 1024, "RGBA8")
        vram_bc7 = estimate_texture_vram_mb(1024, 1024, "BC7")
        assert vram_rgba8 > vram_bc7

    def test_ue5_tc_default_accepted_as_bc7(self):
        # TC_Default normalises to BC7 internally
        result_canonical = estimate_texture_vram_mb(1024, 1024, "BC7")
        result_ue5 = estimate_texture_vram_mb(1024, 1024, "TC_Default")
        assert result_canonical == result_ue5

    def test_mips_add_one_third_cost(self):
        vram_no_mips = estimate_texture_vram_mb(2048, 2048, "BC7", with_mips=False)
        vram_mips = estimate_texture_vram_mb(2048, 2048, "BC7", with_mips=True)
        ratio = vram_mips / vram_no_mips
        assert abs(ratio - 4 / 3) < 0.01

    def test_unknown_format_falls_back_to_rgba8_cost(self):
        # A genuinely unrecognised format uses RGBA8 bpp (4.0) as the safe
        # default. (Known Unity/mobile names like ASTC_8x8 are mapped explicitly
        # and must NOT fall back — see test_unity_formats_are_recognised.)
        result_unknown = estimate_texture_vram_mb(512, 512, "NOT_A_REAL_FORMAT")
        result_rgba8 = estimate_texture_vram_mb(512, 512, "RGBA8")
        assert result_unknown == result_rgba8

    def test_unity_formats_are_recognised(self):
        # Regression: Unity TextureFormat names must map to their block-
        # compressed bpp, not the RGBA8 fallback (that over-estimated VRAM ~8×
        # and produced negative "potential size" in the panel).
        rgba8 = estimate_texture_vram_mb(4000, 2664, "RGBA8")
        assert estimate_texture_vram_mb(4000, 2664, "DXT1") < rgba8
        # DXT1 == BC1 (0.5 bpp) → exactly 1/8 of RGBA8 (4.0 bpp).
        assert estimate_texture_vram_mb(1024, 1024, "DXT1") == estimate_texture_vram_mb(
            1024, 1024, "BC1"
        )
        assert estimate_texture_vram_mb(1024, 1024, "DXT5") == estimate_texture_vram_mb(
            1024, 1024, "BC3"
        )

    def test_unity_mobile_block_formats_are_recognised(self):
        # Same bug class as DXT1 above, for the mobile compression formats
        # Unity actually emits by default on Android/iOS (ASTC/ETC/PVRTC).
        # Any of these falling through to the RGBA8 fallback (4.0 bpp)
        # reproduces the "tamaño incorrecto de texturas" regression.
        rgba8 = estimate_texture_vram_mb(2048, 2048, "RGBA8")
        for fmt in (
            "ASTC_5x5", "ASTC_10x10", "ASTC_12x12",
            "ETC_RGB4", "ETC1_RGB", "ETC2_RGBA1",
            "EAC_R", "EAC_RG",
            "PVRTC_RGB2", "PVRTC_RGBA2",
        ):
            result = estimate_texture_vram_mb(2048, 2048, fmt)
            assert result < rgba8, f"{fmt} fell back to the RGBA8 estimate"

    def test_astc_10x10_regression_matches_reported_bug(self):
        # ASTC_10x10 is a common Unity mobile preset (1.28 bpp real). Before
        # the fix it silently fell back to RGBA8 (4.0 bpp) — a ~3.1x
        # over-estimate. Exact-value regression, not just "smaller than".
        result = estimate_texture_vram_mb(4096, 4096, "ASTC_10x10", with_mips=False)
        rgba8 = estimate_texture_vram_mb(4096, 4096, "RGBA8", with_mips=False)
        assert result == round(rgba8 * (0.16 / 4.0), 2)
        assert result < rgba8 / 3

    def test_astc_6x6_bpp_is_exact_not_rounded(self):
        # ASTC_6x6 used to round to the nearest canonical 0.5 bytes/px
        # (4.0 bpp-equivalent slot) instead of its real 3.56 bpp (~12% error).
        result = estimate_texture_vram_mb(2048, 2048, "ASTC_6x6", with_mips=False)
        expected = round(2048 * 2048 * 0.4444 / 1_048_576, 2)
        assert result == expected

    def test_texture_importer_format_names_are_recognised(self):
        # The Unity client reads GetPlatformTextureSettings().format, which is
        # the TextureImporterFormat enum — its member names differ from the
        # runtime TextureFormat enum (ASTC_RGBA_6x6 vs ASTC_6x6,
        # RGBA_PVRTC_4Bpp vs PVRTC_RGBA4, RGBA_ETC2 vs ETC2_RGBA8). All of
        # them used to fall back to RGBA8 and report ~8x the real size.
        pairs = [
            ("ASTC_RGBA_6x6", "ASTC_6x6"),
            ("ASTC_RGB_6x6", "ASTC_6x6"),
            ("ASTC_HDR_6x6", "ASTC_6x6"),
            ("ASTC_RGBA_12x12", "ASTC_12x12"),
            ("RGBA_PVRTC_4Bpp", "PVRTC_RGBA4"),
            ("RGB_PVRTC_2Bpp", "PVRTC_RGB2"),
            ("RGBA_ETC2", "ETC2_RGBA8"),
            ("RGB_ETC2", "ETC2_RGB"),
            ("ETC2_RGB4", "ETC2_RGB"),
            ("ETC2_RGB4_PUNCHTHROUGH_ALPHA", "ETC2_RGBA1"),
            ("ETC_RGB4Crunched", "ETC_RGB4"),
        ]
        for importer_name, runtime_name in pairs:
            assert estimate_texture_vram_mb(
                2048, 2048, importer_name
            ) == estimate_texture_vram_mb(2048, 2048, runtime_name), importer_name

    def test_unmapped_format_warns_instead_of_failing_silently(self, caplog):
        # The RGBA8 fallback stays, but it must leave a trace — a silent
        # fallback is what let the Unity mobile formats be wrong for so long.
        with caplog.at_level(logging.WARNING):
            estimate_texture_vram_mb(512, 512, "SOME_FUTURE_FORMAT")
        assert "SOME_FUTURE_FORMAT" in caplog.text

    def test_unknown_format_still_falls_back_to_rgba8_cost(self):
        # The intentional fallback for genuinely unrecognised formats must
        # stay intact — only real Unity/UE5 format names get exact mapping.
        result_unknown = estimate_texture_vram_mb(512, 512, "NOT_A_REAL_FORMAT")
        result_rgba8 = estimate_texture_vram_mb(512, 512, "RGBA8")
        assert result_unknown == result_rgba8
