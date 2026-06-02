# core/modules/lod_auditor/tests/test_lod_materials.py

from lod_auditor.rules.lod_materials import check_lm001, check_lm002, check_lm003

# ── Base fixture ──────────────────────────────────────────────────────────────

_BASE: dict = {
    "asset_path": "/Game/M_Test",
    "asset_type": "Material",
    "is_material_instance": False,
    "parent_material": None,
    "instruction_count": 100,
    "sampler_count": 3,
    "texture_samples": [
        {"texture": "/Game/T_A", "shared_sampler": False},
        {"texture": "/Game/T_B", "shared_sampler": False},
    ],
    "used_by_primitives": 1,
    "blend_mode": "Opaque",
}


def _mat(**overrides) -> dict:
    return {**_BASE, **overrides}


# ── LM001 ─────────────────────────────────────────────────────────────────────


class TestLM001:
    def test_fires_when_over_opaque_budget(self):
        result = check_lm001(_mat(instruction_count=450, blend_mode="Opaque"))
        assert result is not None
        assert result.rule_id == "LM001"

    def test_no_finding_exactly_at_opaque_budget(self):
        assert check_lm001(_mat(instruction_count=400, blend_mode="Opaque")) is None

    def test_no_finding_below_opaque_budget(self):
        assert check_lm001(_mat(instruction_count=200, blend_mode="Opaque")) is None

    def test_fires_when_over_translucent_budget(self):
        # Translucent budget is 200
        result = check_lm001(_mat(instruction_count=250, blend_mode="Translucent"))
        assert result is not None

    def test_no_finding_at_translucent_budget(self):
        assert (
            check_lm001(_mat(instruction_count=200, blend_mode="Translucent")) is None
        )

    def test_fires_when_over_masked_budget(self):
        result = check_lm001(_mat(instruction_count=400, blend_mode="Masked"))
        assert result is not None

    def test_saving_reports_exact_excess_instructions(self):
        result = check_lm001(_mat(instruction_count=512, blend_mode="Opaque"))
        assert result.estimated_saving.shader_instructions == 112  # 512 - 400

    def test_auto_fixable_is_false(self):
        result = check_lm001(_mat(instruction_count=500, blend_mode="Opaque"))
        assert result.auto_fixable is False

    def test_guidance_is_not_none(self):
        result = check_lm001(_mat(instruction_count=500, blend_mode="Opaque"))
        assert result.guidance is not None

    def test_unknown_blend_mode_uses_default_budget(self):
        # Unknown blend mode → default 400
        result = check_lm001(_mat(instruction_count=450, blend_mode="Custom"))
        assert result is not None


# ── LM002 ─────────────────────────────────────────────────────────────────────


class TestLM002:
    def test_fires_on_duplicate_texture(self):
        samples = [
            {"texture": "/Game/T_A", "shared_sampler": False},
            {"texture": "/Game/T_A", "shared_sampler": False},
            {"texture": "/Game/T_B", "shared_sampler": False},
        ]
        result = check_lm002(_mat(texture_samples=samples))
        assert result is not None
        assert result.rule_id == "LM002"

    def test_no_finding_for_unique_textures(self):
        assert check_lm002(_mat()) is None

    def test_no_finding_for_empty_samples(self):
        assert check_lm002(_mat(texture_samples=[])) is None

    def test_duplicate_path_appears_in_current(self):
        samples = [
            {"texture": "/Game/T_X", "shared_sampler": False},
            {"texture": "/Game/T_X", "shared_sampler": False},
        ]
        result = check_lm002(_mat(texture_samples=samples))
        assert "/Game/T_X" in result.current["duplicate_textures"]

    def test_recommended_has_empty_duplicates(self):
        samples = [
            {"texture": "/Game/T_X", "shared_sampler": False},
            {"texture": "/Game/T_X", "shared_sampler": False},
        ]
        result = check_lm002(_mat(texture_samples=samples))
        assert result.recommended["duplicate_textures"] == []

    def test_auto_fixable_is_true(self):
        samples = [
            {"texture": "/Game/T_A", "shared_sampler": False},
            {"texture": "/Game/T_A", "shared_sampler": False},
        ]
        result = check_lm002(_mat(texture_samples=samples))
        assert result.auto_fixable is True

    def test_tripled_texture_is_detected(self):
        samples = [{"texture": "/Game/T_A", "shared_sampler": False}] * 3
        result = check_lm002(_mat(texture_samples=samples))
        assert result is not None


# ── LM003 ─────────────────────────────────────────────────────────────────────


class TestLM003:
    def test_fires_when_reused_above_threshold(self):
        result = check_lm003(_mat(is_material_instance=False, used_by_primitives=5))
        assert result is not None
        assert result.rule_id == "LM003"

    def test_fires_exactly_at_threshold(self):
        # threshold = 3 → 3 primitives fires
        result = check_lm003(_mat(is_material_instance=False, used_by_primitives=3))
        assert result is not None

    def test_no_finding_below_threshold(self):
        result = check_lm003(_mat(is_material_instance=False, used_by_primitives=2))
        assert result is None

    def test_no_finding_for_material_instance(self):
        # Instanced materials are exempt regardless of primitive count
        result = check_lm003(_mat(is_material_instance=True, used_by_primitives=10))
        assert result is None

    def test_auto_fixable_is_false(self):
        result = check_lm003(_mat(is_material_instance=False, used_by_primitives=5))
        assert result.auto_fixable is False

    def test_guidance_is_not_none(self):
        result = check_lm003(_mat(is_material_instance=False, used_by_primitives=5))
        assert result.guidance is not None

    def test_severity_is_info(self):
        result = check_lm003(_mat(is_material_instance=False, used_by_primitives=5))
        assert result.severity == "info"
