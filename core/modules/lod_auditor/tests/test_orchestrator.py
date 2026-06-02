# core/modules/lod_auditor/tests/test_orchestrator.py

from lod_auditor.lod_orchestrator import audit_assets

# ── Canonical good assets (zero findings expected) ────────────────────────────

_GOOD_TEXTURE: dict = {
    "asset_path": "/Game/T_Good",
    "asset_type": "Texture2D",
    "usage": "BaseColor",
    "width": 2048,
    "height": 2048,
    "compression": "BC7",
    "srgb": True,
    "mips_enabled": True,
    "streaming": True,
    "lod_group": "World",
}

_GOOD_MATERIAL: dict = {
    "asset_path": "/Game/M_Good",
    "asset_type": "Material",
    "is_material_instance": True,
    "instruction_count": 150,
    "sampler_count": 3,
    "texture_samples": [
        {"texture": "/Game/T_A", "shared_sampler": False},
        {"texture": "/Game/T_B", "shared_sampler": False},
    ],
    "used_by_primitives": 1,
    "blend_mode": "Opaque",
}

_GOOD_MESH: dict = {
    "asset_path": "/Game/SM_Good",
    "asset_type": "StaticMesh",
    "lod_count": 4,
    "lods": [
        {"index": 0, "triangles": 5_000, "vertices": 3_000, "screen_size": 1.0},
        {"index": 1, "triangles": 2_000, "vertices": 1_200, "screen_size": 0.5},
        {"index": 2, "triangles": 800, "vertices": 480, "screen_size": 0.25},
        {"index": 3, "triangles": 200, "vertices": 120, "screen_size": 0.1},
    ],
    "bounds_radius": 100.0,
    "used_in_levels": 1,
}

# ── Intentionally bad assets (at least one finding each) ─────────────────────

_BAD_TEXTURE: dict = {
    **_GOOD_TEXTURE,
    "asset_path": "/Game/T_Bad",
    # LT001: RGBA8 is wrong for BaseColor (expects BC7)
    "compression": "RGBA8",
    # LT003: 4096×4096 exceeds World group budget of 2048
    "width": 4096,
    "height": 4096,
    # LT005: large texture with streaming off
    "streaming": False,
}

_BAD_MATERIAL: dict = {
    **_GOOD_MATERIAL,
    "asset_path": "/Game/M_Bad",
    "is_material_instance": False,
    # LM001: 512 > 400 (Opaque budget)
    "instruction_count": 512,
    # LM002: T_A duplicated
    "texture_samples": [
        {"texture": "/Game/T_A", "shared_sampler": False},
        {"texture": "/Game/T_A", "shared_sampler": False},
    ],
    # LM003: non-instance on 5 primitives
    "used_by_primitives": 5,
}

_BAD_MESH: dict = {
    **_GOOD_MESH,
    "asset_path": "/Game/SM_Bad",
    # LD001: only LOD0
    "lod_count": 1,
    "lods": [
        {"index": 0, "triangles": 5_000, "vertices": 3_000, "screen_size": 1.0},
    ],
}


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestAuditAssets:
    def test_empty_input_returns_empty_response(self):
        result = audit_assets([])
        assert result.summary.assets_audited == 0
        assert result.summary.issues_found == 0
        assert result.results == []

    def test_good_assets_produce_zero_findings(self):
        result = audit_assets([_GOOD_TEXTURE, _GOOD_MATERIAL, _GOOD_MESH])
        assert result.summary.issues_found == 0

    def test_bad_texture_produces_findings(self):
        result = audit_assets([_BAD_TEXTURE])
        assert result.summary.issues_found > 0

    def test_bad_material_produces_findings(self):
        result = audit_assets([_BAD_MATERIAL])
        assert result.summary.issues_found > 0

    def test_bad_mesh_produces_findings(self):
        result = audit_assets([_BAD_MESH])
        assert result.summary.issues_found > 0

    def test_assets_audited_count_matches_input_length(self):
        assets = [_GOOD_TEXTURE, _BAD_TEXTURE, _BAD_MESH]
        result = audit_assets(assets)
        assert result.summary.assets_audited == 3

    def test_vram_saved_accumulates_from_lt003(self):
        result = audit_assets([_BAD_TEXTURE])
        assert result.summary.estimated_vram_saved_mb > 0

    def test_instruction_saving_accumulates_from_lm001(self):
        result = audit_assets([_BAD_MATERIAL])
        assert result.summary.estimated_shader_instructions_saved > 0

    def test_auto_fixable_count_is_accurate(self):
        result = audit_assets([_BAD_MESH])
        auto_fixable_in_results = sum(1 for f in result.results if f.auto_fixable)
        assert result.summary.auto_fixable == auto_fixable_in_results

    def test_summary_issues_count_matches_results_list(self):
        result = audit_assets([_BAD_TEXTURE, _BAD_MATERIAL, _BAD_MESH])
        assert result.summary.issues_found == len(result.results)

    def test_unknown_asset_type_produces_no_findings(self):
        unknown = {"asset_path": "/Game/X", "asset_type": "WorldPartition"}
        result = audit_assets([unknown])
        assert result.summary.issues_found == 0

    def test_tier_filter_empty_set_hides_all_findings(self):
        result = audit_assets([_BAD_TEXTURE, _BAD_MESH], allowed_rules=frozenset())
        assert result.summary.issues_found == 0

    def test_tier_filter_none_shows_all_findings(self):
        result_none = audit_assets([_BAD_TEXTURE, _BAD_MESH], allowed_rules=None)
        result_empty = audit_assets(
            [_BAD_TEXTURE, _BAD_MESH], allowed_rules=frozenset()
        )
        assert result_none.summary.issues_found > result_empty.summary.issues_found

    def test_tier_filter_specific_rule_only_returns_that_rule(self):
        result = audit_assets([_BAD_TEXTURE], allowed_rules=frozenset({"LT003"}))
        assert all(f.rule_id == "LT003" for f in result.results)

    def test_mixed_good_and_bad_only_bad_generate_findings(self):
        result = audit_assets([_GOOD_TEXTURE, _BAD_MESH])
        rule_ids = {f.rule_id for f in result.results}
        # No texture findings (good texture) — only mesh findings
        assert not any(rid.startswith("LT") for rid in rule_ids)
        assert any(rid.startswith("LD") for rid in rule_ids)

    def test_findings_have_valid_category_values(self):
        result = audit_assets([_BAD_TEXTURE, _BAD_MATERIAL, _BAD_MESH])
        valid_categories = {"Texture", "Material", "Mesh"}
        for finding in result.results:
            assert finding.category in valid_categories

    def test_findings_have_valid_severity_values(self):
        result = audit_assets([_BAD_TEXTURE, _BAD_MATERIAL, _BAD_MESH])
        valid_severities = {"warning", "info"}
        for finding in result.results:
            assert finding.severity in valid_severities
