# core/modules/lod_auditor/tests/test_lod_shaders_unity.py
#
# LS013-LS015 — shader-name classification for Unity.
#
# Context: LS001-LS012 read asset["shader_stats"], which no Unity collector
# ever populates (there is no ShaderUtil/Frame Debugger scanner shipped), so
# those twelve rules are permanently silent on a Unity payload. The only real
# shader signal Unity sends is `shading_model` on the material asset — these
# three classify it by name. LX007 is the batch-level companion: a single
# material can't tell you a pipeline migration was left half-done, only the
# whole audited set can.

from __future__ import annotations

from lod_auditor.config import load_profile
from lod_auditor.lod_orchestrator import audit_assets
from lod_auditor.rules.lod_cross import check_lx007_mixed_pipeline
from lod_auditor.rules.lod_shaders import check_ls013, check_ls014, check_ls015

_MOBILE = load_profile("mobile")


def _mat(**overrides) -> dict:
    base = {
        "asset_path": "Assets/M_Test.mat",
        "asset_type": "Material",
        "blend_mode": "Opaque",
    }
    return {**base, **overrides}


class TestLS013LegacyShader:
    def test_fires_on_a_legacy_shader(self):
        finding = check_ls013(
            _mat(shading_model="Legacy Shaders/Bumped Diffuse"), engine="unity"
        )
        assert finding is not None
        assert finding.rule_id == "LS013"
        assert finding.auto_fixable is False

    def test_silent_on_a_modern_shader(self):
        assert check_ls013(
            _mat(shading_model="Universal Render Pipeline/Lit"), engine="unity"
        ) is None

    def test_abstains_on_unreal(self):
        assert check_ls013(
            _mat(shading_model="Legacy Shaders/Bumped Diffuse"), engine="unreal"
        ) is None


class TestLS014DesktopShaderOnMobileProfile:
    def test_fires_on_standard_under_mobile_profile(self):
        finding = check_ls014(
            _mat(shading_model="Standard"), engine="unity", thresholds=_MOBILE
        )
        assert finding is not None and finding.rule_id == "LS014"

    def test_silent_on_the_default_profile(self):
        assert check_ls014(_mat(shading_model="Standard"), engine="unity") is None

    def test_silent_when_already_a_mobile_shader(self):
        assert check_ls014(
            _mat(shading_model="Mobile/Diffuse"), engine="unity", thresholds=_MOBILE
        ) is None

    def test_abstains_on_unreal(self):
        assert check_ls014(
            _mat(shading_model="Standard"), engine="unreal", thresholds=_MOBILE
        ) is None


class TestLS015MobileShaderOnDesktopProfile:
    def test_fires_on_mobile_shader_under_the_default_profile(self):
        finding = check_ls015(_mat(shading_model="Mobile/Diffuse"), engine="unity")
        assert finding is not None
        assert finding.rule_id == "LS015"
        assert finding.severity == "info"

    def test_silent_under_the_mobile_profile(self):
        assert check_ls015(
            _mat(shading_model="Mobile/Diffuse"), engine="unity", thresholds=_MOBILE
        ) is None

    def test_silent_on_a_non_mobile_shader(self):
        assert check_ls015(_mat(shading_model="Standard"), engine="unity") is None

    def test_abstains_on_unreal(self):
        assert check_ls015(
            _mat(shading_model="Mobile/Diffuse"), engine="unreal"
        ) is None


class TestShaderRulesReachTheAuditEndToEnd:
    def test_a_legacy_shader_surfaces_through_audit_assets(self):
        report = audit_assets(
            [_mat(asset_path="Assets/M_Old.mat",
                  shading_model="Legacy Shaders/Bumped Diffuse")],
            engine="unity",
        )
        assert any(f.rule_id == "LS013" for f in report.results)


class TestLX007MixedPipeline:
    def _batch(self):
        return [
            _mat(asset_path="Assets/M_A.mat",
                 shading_model="Universal Render Pipeline/Lit"),
            _mat(asset_path="Assets/M_B.mat",
                 shading_model="Universal Render Pipeline/Lit"),
            _mat(asset_path="Assets/M_C.mat",
                 shading_model="Universal Render Pipeline/Lit"),
            _mat(asset_path="Assets/M_Legacy.mat", shading_model="Standard"),
        ]

    def test_flags_the_minority_pipeline(self):
        findings = check_lx007_mixed_pipeline(self._batch(), engine="unity")
        assert len(findings) == 1
        assert findings[0].asset_path == "Assets/M_Legacy.mat"
        assert findings[0].rule_id == "LX007"
        assert findings[0].current["dominant_family"] == "urp"
        assert findings[0].current["shader_family"] == "builtin"

    def test_silent_when_the_batch_is_a_single_family(self):
        batch = [
            _mat(asset_path="Assets/M_A.mat",
                 shading_model="Universal Render Pipeline/Lit"),
            _mat(asset_path="Assets/M_B.mat",
                 shading_model="Universal Render Pipeline/Unlit"),
        ]
        assert check_lx007_mixed_pipeline(batch, engine="unity") == []

    def test_abstains_on_unreal(self):
        assert check_lx007_mixed_pipeline(self._batch(), engine="unreal") == []

    def test_reaches_the_audit_end_to_end(self):
        report = audit_assets(self._batch(), engine="unity")
        lx007 = [f for f in report.results if f.rule_id == "LX007"]
        assert len(lx007) == 1
