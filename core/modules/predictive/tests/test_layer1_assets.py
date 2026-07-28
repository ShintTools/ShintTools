# core/modules/predictive/tests/test_layer1_assets.py

from lod_auditor.schema import Finding, Saving
from predictive.layers.layer1_assets import _attach_findings, analyze_assets, normalize_engine


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
        # impact is the asset's TOTAL cost, recovery is only the
        # recoverable portion — total is always >= what a fix buys back.
        assert item.impact["vram_mb"].expected >= (
            item.remediation.recovery["vram_mb"].expected
        )

    def test_clean_asset_yields_one_base_cost_item(self):
        # Everything has a cost, flagged or not — a clean asset still gets
        # exactly one item: name + cost, no diagnosis attached.
        r = analyze_assets([_texture()], engine="UE5", profile="default")
        assert len(r.items) == 1
        item = r.items[0]
        assert item.title == "/Game/T_Test"
        assert item.remediation is None
        assert item.rule_id == ""
        assert "vram_mb" in item.impact

    def test_every_priced_asset_yields_exactly_one_item(self):
        r = analyze_assets(
            [_texture(path="/Game/A"), _texture(path="/Game/B", w=4096, h=4096)],
            engine="UE5",
            profile="default",
        )
        assert len(r.items) == 2
        assert {i.title for i in r.items} == {"/Game/A", "/Game/B"}

    def test_multiple_findings_on_one_asset_merge_into_one_item(self):
        # LT003 (oversized, vram saving) + LT008 (RDO off, build saving) on
        # the same texture must not fork into two items — the simulator's
        # unit of selection is the asset, recovery sums across dimensions.
        r = analyze_assets(
            [_texture(w=4096, h=4096, rdo_enabled=False)],
            engine="UE5",
            profile="default",
        )
        matching = [i for i in r.items if i.title == "/Game/T_Test"]
        assert len(matching) == 1
        item = matching[0]
        assert item.remediation is not None
        assert item.remediation.recovery["vram_mb"].expected > 0
        assert item.remediation.recovery["build_mb"].expected > 0

    def test_title_is_never_a_rule_sentence(self):
        r = analyze_assets(
            [_texture(w=4096, h=4096)], engine="UE5", profile="default"
        )
        assert all(" — " not in i.title for i in r.items)
        assert all(i.title == i.source.get("path") for i in r.items)

    def test_item_ids_are_stable_format(self):
        r = analyze_assets(
            [_texture(w=4096, h=4096)], engine="UE5", profile="default"
        )
        assert all(i.item_id.startswith("ci-") for i in r.items)


class TestFallbackItem:
    """A finding-with-saving on an asset asset_vram() doesn't price (e.g. a
    Material — no base item exists for it) must still synthesize an item,
    so material/build-only saving findings don't silently vanish."""

    def test_finding_on_unpriced_asset_synthesizes_item(self):
        finding = Finding(
            asset_path="/Game/M_Test",
            rule_id="LM099",
            category="Material",
            severity="warning",
            message="synthetic",
            current={},
            recommended={},
            estimated_saving=Saving(build_size_mb=1.5),
            auto_fixable=False,
        )
        fallback = _attach_findings({}, [finding], next_index=0)
        assert len(fallback) == 1
        item = fallback[0]
        assert item.title == "/Game/M_Test"
        assert item.remediation.recovery["build_mb"].expected == 1.5

    def test_finding_with_no_recovery_produces_no_fallback(self):
        finding = Finding(
            asset_path="/Game/M_Test",
            rule_id="LM001",
            category="Material",
            severity="warning",
            message="synthetic",
            current={},
            recommended={},
            estimated_saving=Saving(shader_instructions=40),
            auto_fixable=False,
        )
        assert _attach_findings({}, [finding], next_index=0) == []


class TestEngineNormalization:
    def test_spellings(self):
        assert normalize_engine("UE5") == "unreal"
        assert normalize_engine("Unity") == "unity"
        assert normalize_engine("unreal") == "unreal"
        assert normalize_engine("") == "unreal"
