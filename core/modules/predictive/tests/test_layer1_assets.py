# core/modules/predictive/tests/test_layer1_assets.py

from predictive.layers.layer1_assets import analyze_assets, normalize_engine


def _texture(path="/Game/T_Test", w=2048, h=2048, fmt="BC7", **kw):
    base = {
        "asset_path": path,
        "asset_type": "Texture2D",
        "usage": "BaseColor",
        "width": w,
        "height": h,
        "compression": fmt,
        "srgb": True,
        "mips_enabled": True,
        "streaming": True,
        "lod_group": "World",
        "referenced_by_materials": 1,
    }
    base.update(kw)
    return base


def _mesh(path="/Game/SM_Test", verts=100_000):
    return {
        "asset_path": path,
        "asset_type": "StaticMesh",
        "vertex_count": verts,
        "triangle_count": verts * 2,
        "lod_count": 1,
    }


class TestAggregates:
    def test_texture_vram_is_exact_and_high_confidence(self):
        # 2048² BC7 with mips = 5.33 MB (deterministic block math).
        r = analyze_assets([_texture()], engine="UE5", profile="default")
        assert r.vram_total.confidence == "high"
        assert abs(r.vram_total.expected - 5.33) < 0.01
        assert r.vram_total.min == r.vram_total.expected == r.vram_total.max

    def test_mesh_vertex_buffer_priced(self):
        # 100k verts × 32 B = 3.05 MB
        r = analyze_assets([_mesh()], engine="UE5", profile="default")
        assert abs(r.vram_total.expected - 3.05) < 0.01

    def test_totals_sum_across_assets(self):
        r = analyze_assets(
            [_texture(), _mesh()], engine="UE5", profile="default"
        )
        assert abs(r.vram_total.expected - (5.33 + 3.05)) < 0.02
        assert r.assets_analyzed == 2

    def test_build_band_is_medium_and_wider_than_vram(self):
        r = analyze_assets([_texture()], engine="UE5", profile="default")
        assert r.build_total.confidence == "medium"
        assert r.build_total.min < r.build_total.expected < r.build_total.max
        # Package ratio never exceeds 1: cooked ≤ GPU payload.
        assert r.build_total.max <= r.vram_total.expected + 0.01

    def test_undersized_assets_are_skipped_not_guessed(self):
        r = analyze_assets(
            [{"asset_path": "/Game/X", "asset_type": "Texture2D"}],
            engine="UE5",
            profile="default",
        )
        assert r.vram_total.expected == 0.0


class TestAuditDrivenItems:
    def test_oversized_texture_yields_item_with_recovery(self):
        # 4096² in World group breaks the 2048 budget → LT003 with a saving.
        r = analyze_assets(
            [_texture(w=4096, h=4096)], engine="UE5", profile="default"
        )
        lt003 = [i for i in r.items if i.rule_id == "LT003"]
        assert lt003, "expected the LOD audit to surface LT003"
        item = lt003[0]
        assert item.layer == 1
        assert "vram_mb" in item.remediation.recovery
        assert item.remediation.recovery["vram_mb"].expected > 0
        assert item.remediation.auto_fixable is True
        # Impact mirrors recovery: today's excess == tomorrow's saving.
        assert item.impact["vram_mb"].expected == (
            item.remediation.recovery["vram_mb"].expected
        )

    def test_clean_assets_produce_no_items(self):
        r = analyze_assets([_texture()], engine="UE5", profile="default")
        assert r.items == []

    def test_item_ids_are_stable_format(self):
        r = analyze_assets(
            [_texture(w=4096, h=4096)], engine="UE5", profile="default"
        )
        assert all(i.item_id.startswith("ci-") for i in r.items)


class TestEngineNormalization:
    def test_spellings(self):
        assert normalize_engine("UE5") == "unreal"
        assert normalize_engine("Unity") == "unity"
        assert normalize_engine("unreal") == "unreal"
        assert normalize_engine("") == "unreal"
