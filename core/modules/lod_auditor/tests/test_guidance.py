# core/modules/lod_auditor/tests/test_guidance.py
#
# Engine-aware fix guidance: resolution order (engine -> _default -> None),
# placeholder formatting, and that the rules actually emit engine-specific
# wording end-to-end.

from __future__ import annotations

from lod_auditor import audit_assets
from lod_auditor.guidance import guidance_for


class TestGuidanceResolution:
    def test_engine_specific_wins(self):
        unreal = guidance_for("LM003", "unreal")
        unity = guidance_for("LM003", "unity")
        assert unreal is not None and unity is not None
        assert unreal != unity
        # Unreal wording vs Unity wording.
        assert "Material Instance" in unreal
        assert "Material Variant" in unity or "MaterialPropertyBlock" in unity

    def test_falls_back_to_default_for_unknown_engine(self):
        # An engine with no specific entry falls through to "_default".
        default = guidance_for("LD003", "godot", budget=2000)
        assert default is not None
        # The _default LD003 template is engine-neutral (no Simplygon).
        assert "Simplygon" not in default
        assert "2,000" in default  # placeholder formatted

    def test_unknown_rule_returns_none(self):
        assert guidance_for("ZZ999", "unreal") is None

    def test_placeholder_formatting(self):
        text = guidance_for("LD003", "unreal", budget=12345)
        assert text is not None
        assert "12,345" in text

    def test_missing_placeholder_does_not_raise(self):
        # Forgetting to pass `budget` must not blow up — returns raw template.
        text = guidance_for("LD003", "unreal")
        assert text is not None  # no KeyError


class TestEngineAwareAuditEndToEnd:
    """The orchestrator threads engine into the rules so guidance differs."""

    def _mesh_over_budget(self):
        return [
            {
                "asset_path": "/Game/Meshes/Rock",
                "asset_type": "StaticMesh",
                "lod_count": 1,
                "lods": [{"index": 0, "triangles": 90000, "screen_size": 1.0}],
                "bounds_radius": 40.0,
            }
        ]

    def test_unreal_guidance_has_unreal_wording(self):
        resp = audit_assets(self._mesh_over_budget(), engine="unreal")
        ld003 = [f for f in resp.results if f.rule_id == "LD003"]
        assert ld003, "LD003 should fire on a 90k-tri mesh"
        assert "Simplygon" in (ld003[0].guidance or "")

    def test_unity_guidance_has_unity_wording(self):
        resp = audit_assets(self._mesh_over_budget(), engine="unity")
        ld003 = [f for f in resp.results if f.rule_id == "LD003"]
        assert ld003
        guidance = ld003[0].guidance or ""
        assert "Simplygon" not in guidance
        assert "LOD Group" in guidance or "Mesh Simplification" in guidance


class TestFindingEnrichment:
    """Every finding is stamped with rule_name / rule_explanation / engine."""

    def test_findings_carry_name_explanation_engine(self):
        assets = [
            {
                "asset_path": "/Game/Meshes/Rock",
                "asset_type": "StaticMesh",
                "lod_count": 1,
                "lods": [{"index": 0, "triangles": 90000, "screen_size": 1.0}],
                "bounds_radius": 40.0,
            }
        ]
        resp = audit_assets(assets, engine="unity")
        assert resp.results
        for f in resp.results:
            assert f.rule_name, f"{f.rule_id} missing rule_name"
            assert f.rule_explanation, f"{f.rule_id} missing rule_explanation"
            assert f.engine == "unity"

    def test_rule_name_is_humanised_not_id(self):
        assets = [
            {
                "asset_path": "/Game/Meshes/Rock",
                "asset_type": "StaticMesh",
                "lod_count": 1,  # LD001: no LOD chain
            }
        ]
        resp = audit_assets(assets, engine="unreal")
        ld001 = [f for f in resp.results if f.rule_id == "LD001"]
        assert ld001
        assert ld001[0].rule_name == "Mesh has no LOD chain"
