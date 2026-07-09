# Tests for the LOD-chain completion rules (LD004–LD013).

import pytest

from lod_auditor.rules import lod_meshes as m

_ALL = [
    m.check_ld004,
    m.check_ld005,
    m.check_ld006,
    m.check_ld007,
    m.check_ld008,
    m.check_ld009,
    m.check_ld010,
    m.check_ld011,
    m.check_ld012,
    m.check_ld013,
]


@pytest.mark.parametrize("fn", _ALL, ids=[f.__name__ for f in _ALL])
def test_abstains_on_bare_mesh(fn):
    assert (
        fn({"asset_path": "/Game/M", "asset_type": "StaticMesh", "lod_count": 1})
        is None
    )


def _mesh(**kw):
    base = {"asset_path": "/Game/M", "asset_type": "StaticMesh"}
    base.update(kw)
    return base


def _lods(*specs):
    return [
        {"index": i, "triangles": t, "screen_size": ss, **extra}
        for i, (t, ss, extra) in enumerate(specs)
    ]


def test_ld004_too_few_for_size():
    lods = _lods((10000, 1.0, {}), (5000, 0.5, {}))
    f = m.check_ld004(_mesh(lod_count=2, lods=lods, bounds_radius=400.0))
    assert f and f.rule_id == "LD004"
    # nanite -> abstain
    assert (
        m.check_ld004(
            _mesh(lod_count=2, lods=lods, bounds_radius=400.0, nanite_enabled=True)
        )
        is None
    )


def test_ld005_excessive_lods():
    lods = _lods(*[(1000, 1.0 / (i + 1), {}) for i in range(8)])
    f = m.check_ld005(_mesh(lod_count=8, lods=lods))
    assert f and f.rule_id == "LD005"


def test_ld006_reduction_ratios():
    # shallow: LOD1 keeps 90% of LOD0
    lods = _lods((10000, 1.0, {}), (9000, 0.5, {}))
    assert m.check_ld006(_mesh(lods=lods)) is not None
    # healthy halving
    good = _lods((10000, 1.0, {}), (5000, 0.5, {}))
    assert m.check_ld006(_mesh(lods=good)) is None


def test_ld007_bad_screen_size():
    lods = _lods((10000, 1.0, {}), (5000, 0.95, {}))
    assert m.check_ld007(_mesh(lods=lods)) is not None


def test_ld008_material_grows():
    lods = [
        {
            "index": 0,
            "triangles": 10000,
            "screen_size": 1.0,
            "material_slots_used": [0],
            "section_count": 1,
        },
        {
            "index": 1,
            "triangles": 5000,
            "screen_size": 0.5,
            "material_slots_used": [0, 1],
            "section_count": 2,
        },
    ]
    assert m.check_ld008(_mesh(lods=lods)) is not None


def test_ld009_uv_dropped():
    lods = [
        {"index": 0, "triangles": 10000, "screen_size": 1.0, "uv_channel_count": 3},
        {"index": 1, "triangles": 5000, "screen_size": 0.5, "uv_channel_count": 1},
    ]
    f = m.check_ld009(_mesh(lods=lods, max_used_uv_channel=2))
    assert f and f.severity == "error"
    # no known required channel -> abstain
    assert m.check_ld009(_mesh(lods=lods)) is None


def test_ld010_shadow_lod():
    lods = _lods((30000, 1.0, {}), (10000, 0.5, {}))
    f = m.check_ld010(_mesh(lod_count=2, lods=lods, shadow_lod_index=-1))
    assert f and f.rule_id == "LD010"
    assert m.check_ld010(_mesh(lod_count=2, lods=lods, shadow_lod_index=1)) is None


def test_ld011_collision_legs():
    err = m.check_ld011(
        _mesh(collision={"complex_as_simple": True, "complex_triangles": 60000})
    )
    assert err and err.severity == "error"
    missing = m.check_ld011(
        _mesh(collision={"has_simple_collision": False}, used_in_levels=1)
    )
    assert missing and missing.severity == "warning"


def test_ld012_nanite_candidate_engine_gate():
    a = _mesh(
        lods=_lods((100000, 1.0, {})),
        triangle_count=100000,
        used_material_blend_modes=["Opaque"],
    )
    assert m.check_ld012(a, "unreal") is not None
    assert m.check_ld012(a, "unity") is None
    # translucent slot -> not a clean candidate
    a2 = dict(a, used_material_blend_modes=["Opaque", "Translucent"])
    assert m.check_ld012(a2, "unreal") is None


def test_ld013_nanite_compat_engine_gate():
    bad_mat = _mesh(
        nanite_enabled=True, used_material_blend_modes=["Opaque", "Translucent"]
    )
    err = m.check_ld013(bad_mat, "unreal")
    assert err and err.severity == "error"
    assert m.check_ld013(bad_mat, "unity") is None
    heavy = _mesh(
        nanite_enabled=True,
        used_material_blend_modes=["Opaque"],
        nanite_fallback_triangle_percent=50.0,
    )
    warn = m.check_ld013(heavy, "unreal")
    assert warn and warn.severity == "warning"
