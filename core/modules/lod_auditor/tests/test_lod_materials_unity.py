# core/modules/lod_auditor/tests/test_lod_materials_unity.py
#
# LM015-LM018 — the Unity-native material levers.
#
# Context: LM001-LM014 are UE5-shaped (material instances, usage flags,
# layers, RVT). A Unity material scan could reach exactly one of them and
# nothing it produced was applicable, so the Materials tab had no fixes to
# offer at all. These four price properties UnityEngine.Material actually
# exposes, and they must stay silent on every other engine.

from __future__ import annotations

from lod_auditor.lod_orchestrator import audit_assets
from lod_auditor.rules.lod_materials import (
    check_lm003,
    check_lm015,
    check_lm016,
    check_lm017,
    check_lm018,
    check_lm019,
    check_lm020,
)


def _mat(**overrides) -> dict:
    base = {
        "asset_path": "Assets/M_Test.mat",
        "asset_type": "Material",
        "blend_mode": "Opaque",
        "two_sided": False,
    }
    return {**base, **overrides}


class TestLM015GpuInstancing:
    def _shared(self, **over) -> dict:
        return _mat(**{"gpu_instancing": False, "used_by_primitives": 64,
                       "render_pipeline": "builtin", **over})

    def test_fires_on_builtin_when_widely_shared(self):
        finding = check_lm015(self._shared(), engine="unity")
        assert finding is not None
        assert finding.recommended == {"enable_instancing": True}
        assert finding.auto_fixable is True

    def test_silent_when_the_srp_batcher_owns_the_draw(self):
        """URP/HDRP ignore the instancing flag for a batcher-compatible
        material, so recommending it would be a fix that changes nothing."""
        assert check_lm015(
            self._shared(render_pipeline="urp", srp_batcher_compatible=True),
            engine="unity",
        ) is None

    def test_fires_on_urp_when_the_batcher_cannot_take_it(self):
        assert check_lm015(
            self._shared(render_pipeline="urp", srp_batcher_compatible=False),
            engine="unity",
        ) is not None

    def test_abstains_when_the_pipeline_is_unknown(self):
        """Neither field present means we cannot tell which path the draw
        takes — no advice beats advice that may do nothing."""
        asset = self._shared()
        asset.pop("render_pipeline")
        assert check_lm015(asset, engine="unity") is None

    def test_silent_below_the_sharing_threshold(self):
        assert check_lm015(self._shared(used_by_primitives=2), engine="unity") is None

    def test_silent_when_already_enabled(self):
        assert check_lm015(self._shared(gpu_instancing=True), engine="unity") is None

    def test_abstains_when_the_field_was_not_sent(self):
        asset = self._shared()
        asset.pop("gpu_instancing")
        assert check_lm015(asset, engine="unity") is None


class TestLM016SrpBatcher:
    def test_fires_only_on_a_scriptable_pipeline(self):
        assert check_lm016(
            _mat(srp_batcher_compatible=False, render_pipeline="urp"),
            engine="unity",
        ) is not None
        assert check_lm016(
            _mat(srp_batcher_compatible=False, render_pipeline="builtin"),
            engine="unity",
        ) is None

    def test_is_advisory_because_no_material_property_can_fix_it(self):
        finding = check_lm016(
            _mat(srp_batcher_compatible=False, render_pipeline="hdrp"),
            engine="unity",
        )
        assert finding.auto_fixable is False
        assert finding.recommended == {}


class TestLM017RenderQueue:
    def test_transparent_forced_into_the_opaque_band(self):
        finding = check_lm017(
            _mat(blend_mode="Transparent", render_queue=2000), engine="unity"
        )
        assert finding is not None
        assert finding.recommended == {"render_queue": 3000}
        assert finding.auto_fixable is True

    def test_queue_inside_its_own_band_is_fine(self):
        assert check_lm017(
            _mat(blend_mode="Transparent", render_queue=3100), engine="unity"
        ) is None
        assert check_lm017(
            _mat(blend_mode="Opaque", render_queue=2000), engine="unity"
        ) is None

    def test_no_override_is_not_a_mismatch(self):
        # -1 is Unity's "use the shader's queue".
        assert check_lm017(
            _mat(blend_mode="Opaque", render_queue=-1), engine="unity"
        ) is None
        assert check_lm017(_mat(blend_mode="Opaque"), engine="unity") is None


class TestLM018DoubleSidedGi:
    def test_fires_on_a_single_sided_material(self):
        finding = check_lm018(
            _mat(double_sided_gi=True, two_sided=False), engine="unity"
        )
        assert finding.recommended == {"double_sided_gi": False}
        assert finding.auto_fixable is True

    def test_silent_when_the_material_really_is_two_sided(self):
        assert check_lm018(
            _mat(double_sided_gi=True, two_sided=True), engine="unity"
        ) is None


class TestLM019ShaderPipelineFolderMismatch:
    def test_fires_when_urp_folder_carries_a_builtin_shader(self):
        finding = check_lm019(
            _mat(
                asset_path="Assets/Materials/URP/M_Rock.mat",
                shading_model="Standard",
            ),
            engine="unity",
        )
        assert finding is not None
        assert finding.current["folder_pipeline"] == "urp"
        # No material property can retarget the shader — advisory only.
        assert finding.auto_fixable is False

    def test_fires_when_hdrp_folder_carries_a_urp_shader(self):
        finding = check_lm019(
            _mat(
                asset_path="Assets/Materials/HDRP/M_Glass.mat",
                shading_model="Universal Render Pipeline/Lit",
            ),
            engine="unity",
        )
        assert finding is not None
        assert finding.current["folder_pipeline"] == "hdrp"

    def test_silent_when_the_folder_and_shader_agree(self):
        assert check_lm019(
            _mat(
                asset_path="Assets/Materials/URP/M_Rock.mat",
                shading_model="Universal Render Pipeline/Lit",
            ),
            engine="unity",
        ) is None

    def test_silent_without_an_unambiguous_folder_marker(self):
        # No pipeline folder convention to contradict — no false positive.
        assert check_lm019(
            _mat(asset_path="Assets/Materials/M_Rock.mat", shading_model="Standard"),
            engine="unity",
        ) is None

    def test_abstains_on_unreal(self):
        assert check_lm019(
            _mat(
                asset_path="Assets/Materials/URP/M_Rock.mat",
                shading_model="Standard",
            ),
            engine="unreal",
        ) is None


class TestLM020DoubleSidedGiOnNonGiShader:
    def test_fires_on_an_unlit_shader(self):
        finding = check_lm020(
            _mat(two_sided=True, shading_model="Unlit/Color"), engine="unity"
        )
        assert finding is not None
        assert finding.recommended == {"double_sided_gi": False}
        assert finding.auto_fixable is True

    def test_fires_on_a_ui_shader(self):
        assert check_lm020(
            _mat(two_sided=True, shading_model="UI/Default"), engine="unity"
        ) is not None

    def test_silent_on_a_lit_shader(self):
        # A Lit shader genuinely benefits from double-sided GI — LM018's
        # territory, not LM020's.
        assert check_lm020(
            _mat(two_sided=True, shading_model="Universal Render Pipeline/Lit"),
            engine="unity",
        ) is None

    def test_silent_when_the_flag_is_off(self):
        assert check_lm020(
            _mat(two_sided=False, shading_model="Unlit/Color"), engine="unity"
        ) is None

    def test_abstains_on_unreal(self):
        assert check_lm020(
            _mat(two_sided=True, shading_model="Unlit/Color"), engine="unreal"
        ) is None


class TestEngineSeparation:
    UNITY_RULES = (
        check_lm015,
        check_lm016,
        check_lm017,
        check_lm018,
        check_lm019,
        check_lm020,
    )

    def test_unity_rules_abstain_on_unreal(self):
        asset = _mat(
            asset_path="Assets/Materials/URP/M_Test.mat",
            gpu_instancing=False, used_by_primitives=64, render_pipeline="builtin",
            srp_batcher_compatible=False, render_queue=2000,
            blend_mode="Transparent", double_sided_gi=True,
            shading_model="Standard",
        )
        for rule in self.UNITY_RULES:
            assert rule(asset, engine="unreal") is None, rule.__name__

    def test_unreal_only_concepts_abstain_on_unity(self):
        """LM003 recommends converting to a Material Instance — Unreal
        machinery with no Unity counterpart. It stayed quiet there only
        because the collector sent no used_by_primitives; now that the
        collector spec asks for that field, the concept must be gated."""
        shared = _mat(is_material_instance=False, used_by_primitives=40)
        assert check_lm003(shared, engine="unreal") is not None
        assert check_lm003(shared, engine="unity") is None

    def test_a_unity_material_scan_now_has_something_to_fix(self):
        report = audit_assets(
            [
                _mat(asset_path="Assets/M_Rock.mat", gpu_instancing=False,
                     used_by_primitives=64, render_pipeline="builtin"),
                _mat(asset_path="Assets/M_Glass.mat", blend_mode="Transparent",
                     render_queue=2000),
                _mat(asset_path="Assets/M_Wall.mat", double_sided_gi=True),
            ],
            engine="unity",
        )
        fixable = [f for f in report.results if f.auto_fixable]
        assert len(fixable) == 3
        assert all(f.recommended for f in fixable)
