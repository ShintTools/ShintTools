# Tests for the shader rules (LS001–LS012).

import pytest

from lod_auditor.config import load_profile
from lod_auditor.rules import lod_shaders as s

_MOBILE = load_profile("mobile")

_ALL = [
    s.check_ls001,
    s.check_ls002,
    s.check_ls003,
    s.check_ls004,
    s.check_ls005,
    s.check_ls006,
    s.check_ls007,
    s.check_ls008,
    s.check_ls009,
    s.check_ls010,
    s.check_ls011,
    s.check_ls012,
]


@pytest.mark.parametrize("fn", _ALL, ids=[f.__name__ for f in _ALL])
def test_abstains_without_shader_stats(fn):
    assert fn({"asset_path": "/Game/Mat", "asset_type": "Material"}) is None


def _mat(ss, **kw):
    base = {"asset_path": "/Game/Mat", "asset_type": "Material", "shader_stats": ss}
    base.update(kw)
    return base


def test_ls001_escalates():
    assert s.check_ls001(_mat({"instruction_count": 600})).severity == "warning"
    assert s.check_ls001(_mat({"instruction_count": 2000})).severity == "error"


def test_ls002_fetches():
    f = s.check_ls002(_mat({"texture_fetch_count": 30}))
    assert f and f.estimated_saving.shader_instructions == 4 * (30 - 16)


def test_ls003_branches():
    assert s.check_ls003(_mat({"branch_count": 40})) is not None


def test_ls004_dynamic_mobile_escalates():
    m = _mat({"dynamic_branch_count": 10})
    assert s.check_ls004(m).severity == "info"
    assert s.check_ls004(m, "unreal", thresholds=_MOBILE).severity == "warning"


def test_ls005_unbounded_loop():
    assert s.check_ls005(_mat({"loop_count": 1, "max_loop_iterations": 0})) is not None
    assert s.check_ls005(_mat({"loop_count": 1, "max_loop_iterations": 8})) is None


def test_ls006_register_pressure():
    assert s.check_ls006(_mat({"estimated_register_pressure": 100})) is not None


def test_ls007_variants_escalates():
    assert s.check_ls007(_mat({"variant_count": 300})).severity == "warning"
    assert s.check_ls007(_mat({"variant_count": 2000})).severity == "error"


def test_ls008_mobile_only():
    m = _mat({"half_precision_ratio": 0.1})
    assert s.check_ls008(m) is None
    assert s.check_ls008(m, "unreal", thresholds=_MOBILE) is not None


def test_ls009_dead_code():
    assert s.check_ls009(_mat({"dead_code_ratio": 0.3})) is not None


def test_ls010_dead_params_autofix():
    f = s.check_ls010(_mat({"dead_parameter_count": 10}))
    assert f and f.auto_fixable is True


def test_ls011_expensive_math():
    f = s.check_ls011(_mat({"expensive_op_counts": {"pow": 20, "sin": 12}}))
    assert f and f.estimated_saving.shader_instructions == (20 - 8) + (12 - 8)


def test_ls012_dependent_reads():
    assert s.check_ls012(_mat({"dependent_texture_reads": 5})) is not None
