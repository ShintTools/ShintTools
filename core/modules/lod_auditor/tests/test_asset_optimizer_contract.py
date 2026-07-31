# core/modules/lod_auditor/tests/test_asset_optimizer_contract.py
#
# Regression coverage for the six Asset-Optimizer defects reported from the
# live clients (2026-07-31). Each class maps to one reported item.
#
# The through-line: the Core must publish numbers a studio can trust and
# recommendations a client can actually apply — never a figure derived from
# a resolution the GPU doesn't hold, never a saving larger than the thing
# being saved, never a key the client has no field for.

from __future__ import annotations

from lod_auditor.lod_orchestrator import audit_assets
from lod_auditor.lod_report import top_offenders
from lod_auditor.recommended_filter import filter_recommended
from lod_auditor.rules.lod_textures import check_lt003, check_lt004
from lod_auditor.vram_model import (
    effective_texture_size,
    is_analyzable_texture_format,
    is_indexed_format,
    texture_asset_vram_mb,
)


def _tex(**overrides) -> dict:
    base = {
        "asset_path": "Assets/T_Test.png",
        "asset_type": "Texture2D",
        "usage": "BaseColor",
        "width": 4096,
        "height": 4096,
        "compression": "RGBA32",
        "mips_enabled": True,
        "mip_count": 12,
        "streaming": True,
        "max_texture_size": 0,  # 0 = uncapped
        "referenced_by_materials": 1,
    }
    return {**base, **overrides}


# ── 1. Potential memory savings ───────────────────────────────────────────────


class TestSavingsArePhysicallyCoherent:
    def test_savings_never_exceed_the_assets_real_memory(self):
        """The reported symptom: panel shows a negative 'potential memory'
        because summed savings came to more than the texture holds."""
        asset = _tex(streaming=False)
        report = audit_assets([asset], engine="unity")
        real = texture_asset_vram_mb(asset)
        claimed = sum(f.estimated_saving.vram_mb for f in report.results)

        assert claimed <= real + 0.01
        assert real - claimed >= 0.0  # the panel's "potential" figure

    def test_no_saving_is_ever_negative(self):
        for engine in ("unity", "unreal"):
            report = audit_assets(
                [_tex(width=8192, height=512, streaming=False, srgb=True)],
                engine=engine,
            )
            for finding in report.results:
                assert finding.estimated_saving.vram_mb >= 0.0
                assert finding.estimated_saving.build_size_mb >= 0.0
                assert finding.estimated_saving.shader_instructions >= 0

    def test_combined_optimisations_reconcile_to_their_joint_result(self):
        """Resize AND compress don't sum: a 4096 RGBA8 (85.33 MB) becomes
        2048 BC7 (5.33 MB), so the honest total is 80 MB — not 128 MB (raw
        sum) and not 85.33 MB (which would imply the texture ends up free)."""
        asset = _tex(compression="RGBA32", width=4096, height=4096)
        report = audit_assets([asset], engine="unity")
        claimed = sum(f.estimated_saving.vram_mb for f in report.results)
        residual = texture_asset_vram_mb(asset) - claimed

        assert claimed == 80.0
        assert round(residual, 2) == 5.33  # what the texture still costs after

    def test_top_offenders_aggregate_stays_within_the_asset(self):
        asset = _tex(streaming=False)
        report = audit_assets([asset], engine="unity")
        row = top_offenders(report.results)[0]
        assert row["estimated_vram_saved_mb"] <= texture_asset_vram_mb(asset) + 0.01

    def test_deleting_a_dead_texture_still_reports_its_full_cost(self):
        """The joint optimisation model must not cap a removal — deleting
        frees everything, which resize/recompress arithmetic can't express."""
        dead = _tex(asset_path="Assets/T_Dead.png", referenced_by_materials=0)
        report = audit_assets([dead], engine="unity")
        lx001 = [f for f in report.results if f.rule_id == "LX001"]
        assert lx001, "LX001 should flag an unreferenced texture"
        assert lx001[0].estimated_saving.vram_mb == texture_asset_vram_mb(dead)


# ── 2. Max texture size ───────────────────────────────────────────────────────


class TestReportedFiguresAgreeWithEachOther:
    """The panel puts the message, the savings column and the client's own
    measured size on the same row. Any two of them disagreeing is the defect,
    regardless of which one is 'more correct'."""

    # What a Unity collector actually sends: the importer reports "Automatic"
    # for any platform without an explicit format override, and size_kb is
    # Profiler.GetRuntimeMemorySizeLong — the engine's own accounting.
    def _measured(self, **overrides) -> dict:
        return _tex(compression="Automatic", size_kb=2.67 * 1024,
                    max_texture_size=2048, **overrides)

    def test_message_quotes_the_same_figure_as_the_savings_column(self):
        report = audit_assets(
            [_tex(width=4096, height=4096, compression="RGBA32", streaming=False)],
            engine="unity",
        )
        for finding in report.results:
            if "MB VRAM" not in finding.message:
                continue
            assert "{vram_saving}" not in finding.message, "token left unrendered"
            assert f"{finding.estimated_saving.vram_mb:g} MB VRAM" in finding.message

    def test_client_measurement_is_reproduced_not_overridden(self):
        """A measured size above one RGBA8 texel used to be discarded as
        implausible, so the Core printed its model's figure next to the
        engine's — 14.22 MB against the panel's 24.88 MB on the same row."""
        asset = _tex(width=5184, height=3456, compression="Automatic",
                     max_texture_size=2048, size_kb=24.88 * 1024)
        assert round(texture_asset_vram_mb(asset), 2) == 24.88

    def test_a_resize_still_saves_when_the_size_was_measured(self):
        """The measured bytes-per-pixel is anchored at the current size.
        Re-deriving it after the proposed downsize spread the same bytes over
        fewer pixels and priced every Unity resize as free."""
        report = audit_assets([self._measured(width=4000, height=2664)],
                              engine="unity")
        resize = [f for f in report.results if f.rule_id == "LT006"]
        assert resize and resize[0].estimated_saving.vram_mb > 0

    def test_a_saving_survives_a_recommendation_the_client_cannot_apply(self):
        """LT006's fix is a DCC round-trip, so its recommendation is filtered
        out at the boundary. The memory it saves is still real — reading the
        filtered dict made the joint model conclude nothing changes."""
        report = audit_assets([self._measured(width=4000, height=2664)],
                              engine="unity")
        lt006 = [f for f in report.results if f.rule_id == "LT006"][0]
        assert lt006.recommended == {}
        assert lt006.auto_fixable is False
        assert lt006.estimated_saving.vram_mb > 0


class TestEffectiveTextureSize:
    def test_import_cap_defines_the_resident_size(self):
        assert effective_texture_size(4096, 4096, 2048) == (2048, 2048)
        assert effective_texture_size(4096, 2048, 1024) == (1024, 512)  # aspect kept
        assert effective_texture_size(1024, 1024, 2048) == (1024, 1024)  # under cap
        assert effective_texture_size(4096, 4096, 0) == (4096, 4096)  # uncapped

    def test_already_capped_texture_is_not_flagged_as_oversized(self):
        """The exact report: a 4096 source with max_texture_size=2048 was read
        as ~4096 and told to reduce to 2048 — which it already was."""
        assert check_lt003(_tex(width=4096, height=4096, max_texture_size=2048)) is None

    def test_genuinely_oversized_texture_still_fires(self):
        finding = check_lt003(_tex(width=4096, height=4096, max_texture_size=0))
        assert finding is not None
        assert finding.recommended["max_texture_size"] == 2048

    def test_memory_is_priced_from_the_capped_size(self):
        capped = _tex(width=4096, height=4096, max_texture_size=2048,
                      compression="DXT1")
        native = _tex(width=2048, height=2048, max_texture_size=0,
                      compression="DXT1")
        assert texture_asset_vram_mb(capped) == texture_asset_vram_mb(native)


# ── 3. recommended serialization ──────────────────────────────────────────────


class TestRecommendedSerialization:
    UNITY_TEXTURE = {"compression", "max_texture_size", "srgb", "streaming",
                     "mips_enabled"}

    def test_only_client_applicable_keys_survive(self):
        for engine, allowed in (("unity", self.UNITY_TEXTURE),):
            report = audit_assets(
                [_tex(streaming=False, srgb=True, usage="Normal")], engine=engine
            )
            for finding in report.results:
                assert set(finding.recommended) <= allowed, (
                    f"{finding.rule_id} leaked {set(finding.recommended) - allowed}"
                )

    def test_analysis_values_are_stripped(self):
        """vram_mb / width / height / confidence exist to explain the finding,
        never to be applied — they must not reach a typed client DTO."""
        report = audit_assets([_tex(streaming=False)], engine="unity")
        for finding in report.results:
            for banned in ("vram_mb", "width", "height", "confidence",
                           "resident_vram_mb", "estimated", "hint"):
                assert banned not in finding.recommended

    def test_advisory_strings_are_not_applicable_values(self):
        # "<= 2048" would parse to 0 in both clients and resize to nothing.
        assert filter_recommended(
            "Texture", "unity", {"max_texture_size": "<= 2048"}
        ) == {}
        assert filter_recommended("Mesh", "unity", {"lod_count": ">= 2"}) == {}
        assert filter_recommended(
            "Material", "unity", {"hint": "reduce or bake the flagged nodes"}
        ) == {}

    def test_unapplicable_finding_is_not_marked_auto_fixable(self):
        """A cleared recommendation means the client's Fix button would be a
        no-op, so the flag must follow the payload."""
        report = audit_assets(
            [{"asset_path": "Assets/M.mat", "asset_type": "Material",
              "instruction_count": 100000, "sampler_count": 3}],
            engine="unity",
        )
        for finding in report.results:
            if not finding.recommended:
                assert finding.auto_fixable is False

    def test_engine_vocabulary_is_translated_not_dropped(self):
        # UE5 says never_stream, Unity says streaming — same intent, inverted.
        assert filter_recommended("Texture", "unity", {"never_stream": True}) == {
            "streaming": False
        }
        assert filter_recommended("Texture", "unreal", {"streaming": True}) == {
            "never_stream": False
        }

    def test_unreal_keeps_the_keys_its_fixer_supports(self):
        """Filtering both engines down to Unity's DTO would silently disable
        working UE5 auto-fixes (lod_group, mip_gen, structural mesh keys)."""
        assert filter_recommended(
            "Texture", "unreal", {"lod_group": "NormalMap"}
        ) == {"lod_group": "NormalMap"}
        assert filter_recommended(
            "Mesh", "unreal", {"nanite_enabled": True}
        ) == {"nanite_enabled": True}
        # ...but Unity, which has no such field, gets nothing.
        assert filter_recommended("Texture", "unity", {"lod_group": "NormalMap"}) == {}


# ── 4. Indexed textures ───────────────────────────────────────────────────────


class TestIndexedTexturesAreIgnored:
    def test_indexed_formats_are_recognised(self):
        for fmt in ("Indexed8", "PAL8", "TSF_P8", "Palette", "RGBA_Indexed"):
            assert is_indexed_format(fmt) is True
        for fmt in ("BC7", "DXT1", "ASTC_6x6", "RGBA32"):
            assert is_indexed_format(fmt) is False

    def test_indexed_texture_produces_nothing_at_all(self):
        report = audit_assets(
            [_tex(compression="Indexed8", streaming=False, mips_enabled=False)],
            engine="unity",
        )
        assert report.results == []
        assert report.summary.issues_found == 0
        assert report.summary.estimated_vram_saved_mb == 0.0

    def test_indexed_texture_contributes_no_memory_baseline(self):
        assert texture_asset_vram_mb(_tex(compression="Indexed8")) == 0.0

    def test_unmapped_format_without_a_measurement_is_skipped(self):
        """Unity's "Automatic" with no size_kb can only be priced by guessing
        RGBA8 — an 8x over-estimate that invented savings and a bogus
        'this is uncompressed' verdict."""
        assert is_analyzable_texture_format("Automatic", None) is False
        assert audit_assets(
            [_tex(compression="Automatic")], engine="unity"
        ).results == []

    def test_unmapped_format_with_a_measurement_is_analyzed(self):
        # A real client measurement makes the format priceable after all.
        assert is_analyzable_texture_format("Automatic", 2048.0) is True

    def test_indexed_texture_is_excluded_from_cross_asset_rules(self):
        report = audit_assets(
            [_tex(compression="Indexed8", referenced_by_materials=0)],
            engine="unity",
        )
        assert [f.rule_id for f in report.results] == []


# ── 5/6. Cross-engine consistency ─────────────────────────────────────────────


class TestEngineConsistency:
    def test_same_asset_yields_the_same_memory_numbers_on_both_engines(self):
        asset = _tex(asset_path="/Game/T_X", streaming=False, srgb=True)
        ue5 = audit_assets([dict(asset)], engine="unreal")
        unity = audit_assets([dict(asset)], engine="unity")
        assert (
            ue5.summary.estimated_vram_saved_mb
            == unity.summary.estimated_vram_saved_mb
        )

    def test_srgb_rule_abstains_when_the_client_omits_the_field(self):
        """Unity's collector sends no `srgb`; defaulting it to True fired
        LT004 on every Normal/Mask/HDR/Data texture in the project."""
        without = _tex(usage="Normal")
        assert "srgb" not in without
        assert check_lt004(without) is None
        # Explicit values still evaluate normally.
        assert check_lt004(_tex(usage="Normal", srgb=True)) is not None
        assert check_lt004(_tex(usage="Normal", srgb=False)) is None
