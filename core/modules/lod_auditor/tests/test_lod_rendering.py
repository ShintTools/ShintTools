# Tests for the rendering-cost rules (LR001–LR008).

import pytest

from lod_auditor.config import load_profile
from lod_auditor.rules import lod_rendering as r

_MOBILE = load_profile("mobile")

_ALL = [
    r.check_lr001,
    r.check_lr002,
    r.check_lr003,
    r.check_lr004,
    r.check_lr005,
    r.check_lr006,
    r.check_lr007,
    r.check_lr008,
]


@pytest.mark.parametrize("fn", _ALL, ids=[f.__name__ for f in _ALL])
def test_abstains_on_bare_material(fn):
    assert fn({"asset_path": "/Game/Mat", "asset_type": "Material"}) is None


def _mat(**kw):
    base = {"asset_path": "/Game/Mat", "asset_type": "Material", "blend_mode": "Opaque"}
    base.update(kw)
    return base


def test_lr001_opaque_scene_read():
    assert r.check_lr001(_mat(uses_scene_color=True)) is not None
    assert r.check_lr001(_mat(blend_mode="Translucent", uses_scene_color=True)) is None


def test_lr002_mobile_only():
    m = _mat(blend_mode="Masked", used_by_primitives=200)
    assert r.check_lr002(m) is None  # default profile
    assert r.check_lr002(m, "unreal", thresholds=_MOBILE) is not None


def test_lr003_translucent_depth_escalates():
    warn = r.check_lr003(
        _mat(blend_mode="Translucent", uses_depth_read=True, instruction_count=50)
    )
    assert warn and warn.severity == "warning"
    err = r.check_lr003(
        _mat(blend_mode="Translucent", uses_depth_read=True, instruction_count=5000)
    )
    assert err and err.severity == "error"


def test_lr004_additive_stacking():
    assert (
        r.check_lr004(_mat(blend_mode="Additive", used_by_primitives=200)) is not None
    )


def test_lr005_decal_cost():
    assert r.check_lr005(_mat(is_decal=True, instruction_count=500)) is not None


def test_lr006_two_sided_fix_gate():
    unknown = r.check_lr006(_mat(two_sided=True, used_by_primitives=50))
    assert unknown and unknown.auto_fixable is False
    known = r.check_lr006(
        _mat(two_sided=True, used_by_primitives=50, has_thin_geo_consumers=False)
    )
    assert known and known.auto_fixable is True


def test_lr007_wpo_heavy():
    assert (
        r.check_lr007(_mat(uses_wpo=True, max_referencer_vertex_count=200_000))
        is not None
    )
    assert r.check_lr007(_mat(uses_wpo=True, has_nanite_referencer=True)) is not None


def test_lr008_pdo_cost():
    assert r.check_lr008(_mat(uses_pdo=True, used_by_primitives=50)) is not None
