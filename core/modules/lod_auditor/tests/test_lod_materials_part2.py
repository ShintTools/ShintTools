# Tests for the material-completion rules (LM004–LM014).

import pytest

from lod_auditor.rules import lod_materials as m

_ALL = [
    m.check_lm004,
    m.check_lm005,
    m.check_lm006,
    m.check_lm007,
    m.check_lm008,
    m.check_lm009,
    m.check_lm010,
    m.check_lm011,
    m.check_lm012,
    m.check_lm013,
    m.check_lm014,
]


@pytest.mark.parametrize("fn", _ALL, ids=[f.__name__ for f in _ALL])
def test_abstains_on_bare_material(fn):
    assert fn({"asset_path": "/Game/Mat", "asset_type": "Material"}) is None


def _mat(**kw):
    base = {"asset_path": "/Game/Mat", "asset_type": "Material", "blend_mode": "Opaque"}
    base.update(kw)
    return base


def test_lm004_samplers_escalate():
    assert m.check_lm004(_mat(sampler_count=13)).severity == "warning"
    assert m.check_lm004(_mat(sampler_count=20)).severity == "error"


def test_lm005_graph_complexity():
    assert m.check_lm005(_mat(graph_node_count=500)) is not None
    assert m.check_lm005(_mat(graph_depth=60)) is not None


def test_lm006_function_depth():
    assert m.check_lm006(_mat(function_call_depth=8)) is not None


def test_lm007_layers():
    assert m.check_lm007(_mat(layer_count=6)) is not None
    # Translucent budget is _default (2)
    assert m.check_lm007(_mat(blend_mode="Translucent", layer_count=3)) is not None


def test_lm008_layered_blend():
    f = m.check_lm008(_mat(layer_count=3, base_pass_instructions=350))
    assert f and f.rule_id == "LM008"
    assert m.check_lm008(_mat(layer_count=1, base_pass_instructions=350)) is None


def test_lm009_rvt_underused():
    assert m.check_lm009(_mat(uses_rvt=True, used_by_primitives=2)) is not None
    assert m.check_lm009(_mat(uses_rvt=True, used_by_primitives=50)) is None


def test_lm010_dynamic_params():
    warn = m.check_lm010(_mat(dynamic_parameter_count=12, is_material_instance=False))
    assert warn.severity == "warning"
    info = m.check_lm010(_mat(dynamic_parameter_count=12, is_material_instance=True))
    assert info.severity == "info"


def test_lm011_permutations_escalate():
    assert m.check_lm011(_mat(static_switch_count=12)).severity == "warning"
    err = m.check_lm011(_mat(static_switch_count=12, static_permutation_estimate=500))
    assert err.severity == "error" and err.estimated_saving.build_size_mb > 0


def test_lm012_unused_flags():
    f = m.check_lm012(_mat(usage_flags_unused=["bUsedWithSkeletalMesh"]))
    assert f and f.auto_fixable is True


def test_lm013_expensive_nodes_severity():
    f = m.check_lm013(_mat(expensive_node_counts={"SceneColor": 2, "SceneDepth": 1}))
    assert f and f.severity == "warning"  # max(warning, info)


def test_lm014_vertex_shader():
    assert m.check_lm014(_mat(vertex_shader_instructions=300)) is not None
