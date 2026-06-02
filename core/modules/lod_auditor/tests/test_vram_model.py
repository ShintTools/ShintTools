# core/modules/lod_auditor/tests/test_vram_model.py

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
        # Unknown format uses RGBA8 bpp (4.0) as the safe default
        result_unknown = estimate_texture_vram_mb(512, 512, "ASTC_8x8")
        result_rgba8 = estimate_texture_vram_mb(512, 512, "RGBA8")
        assert result_unknown == result_rgba8
