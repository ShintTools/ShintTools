# Tests for the UV / texel-density rules (LW001–LW010).

import pytest

from lod_auditor.rules import lod_uv as uv

_ALL = [
    uv.check_lw001,
    uv.check_lw002,
    uv.check_lw003,
    uv.check_lw004,
    uv.check_lw005,
    uv.check_lw006,
    uv.check_lw007,
    uv.check_lw008,
    uv.check_lw009,
    uv.check_lw010,
    uv.check_lw011,
]


@pytest.mark.parametrize("fn", _ALL, ids=[f.__name__ for f in _ALL])
def test_abstains_without_uv_channels(fn):
    assert fn({"asset_path": "/Game/M", "asset_type": "StaticMesh"}) is None


def _mesh(channels, **kw):
    base = {
        "asset_path": "/Game/M",
        "asset_type": "StaticMesh",
        "uv_channels": channels,
    }
    base.update(kw)
    return base


def test_lw001_overlap_channel0():
    f = uv.check_lw001(_mesh([{"channel": 0, "overlap_ratio": 0.5}]))
    assert f and f.rule_id == "LW001"
    assert uv.check_lw001(_mesh([{"channel": 0, "overlap_ratio": 0.1}])) is None


def test_lw002_lightmap_overlap_error():
    f = uv.check_lw002(
        _mesh(
            [{"channel": 1, "overlap_ratio": 0.05}],
            lightmap_uv_index=1,
            uses_static_lighting=True,
        )
    )
    assert f and f.severity == "error"
    # not static-lit -> abstain
    assert (
        uv.check_lw002(
            _mesh([{"channel": 1, "overlap_ratio": 0.05}], lightmap_uv_index=1)
        )
        is None
    )


def test_lw003_stretch():
    f = uv.check_lw003(_mesh([{"channel": 0, "max_stretch": 5.0, "avg_stretch": 2.0}]))
    assert f and f.rule_id == "LW003"


def test_lw004_only_detail_meshes():
    ch = [{"channel": 0, "avg_stretch": 1.5}]
    assert uv.check_lw004(_mesh(ch)) is None
    assert (
        uv.check_lw004(
            {
                "asset_path": "/Game/Wall_Detail",
                "asset_type": "StaticMesh",
                "uv_channels": ch,
            }
        )
        is not None
    )


def test_lw005_islands():
    f = uv.check_lw005(
        _mesh([{"channel": 0, "island_count": 900}], triangle_count=10_000)
    )
    assert f and f.rule_id == "LW005"


def test_lw006_lightmap_autofix():
    f = uv.check_lw006(
        _mesh(
            [{"channel": 1, "packing_efficiency": 0.3}],
            lightmap_uv_index=1,
            uses_static_lighting=True,
        )
    )
    assert f and f.auto_fixable is True
    # texture channel -> not auto-fixable
    f2 = uv.check_lw006(_mesh([{"channel": 0, "packing_efficiency": 0.3}]))
    assert f2 and f2.auto_fixable is False


def test_lw007_high_and_low():
    hi = uv.check_lw007(
        _mesh([{"channel": 0, "texel_density_avg": 30.0}], lod_group="World")
    )
    assert hi and hi.severity == "warning"
    lo = uv.check_lw007(
        _mesh([{"channel": 0, "texel_density_avg": 1.0}], lod_group="World")
    )
    assert lo and lo.severity == "info"


def test_lw008_variance():
    f = uv.check_lw008(
        _mesh([{"channel": 0, "texel_density_cv": 0.8}], triangle_count=5000)
    )
    assert f and f.rule_id == "LW008"


def test_lw009_lightmap_leg():
    f = uv.check_lw009(
        _mesh(
            [{"channel": 1, "outside_unit_ratio": 0.2}],
            lightmap_uv_index=1,
            uses_static_lighting=True,
        )
    )
    assert f and f.severity == "warning"
    # channel0 without clamp addressing -> abstain (tiling is legit)
    assert uv.check_lw009(_mesh([{"channel": 0, "outside_unit_ratio": 0.2}])) is None


def test_lw010_material_and_lightmap_legs():
    mat = uv.check_lw010(
        _mesh([{"channel": 0}], uv_channel_count=1, max_used_uv_channel=2)
    )
    assert mat and mat.severity == "error"
    lm = uv.check_lw010(
        _mesh(
            [{"channel": 0}],
            uv_channel_count=1,
            uses_static_lighting=True,
            lightmap_uv_index=-1,
        )
    )
    assert lm and lm.recommended.get("generate_lightmap_uvs") is True


def test_lw011_fires_on_unity_without_static_lighting_signal():
    """LW011 is LW009's Unity complement: uses_static_lighting never arrives
    on a Unity payload, so lightmap_uv_index pointing at a real channel is the
    signal instead — one notch lower confidence (info, not warning)."""
    f = uv.check_lw011(
        _mesh([{"channel": 1, "outside_unit_ratio": 0.2}], lightmap_uv_index=1),
        engine="unity",
    )
    assert f and f.rule_id == "LW011" and f.severity == "info"
    assert f.auto_fixable is False


def test_lw011_abstains_off_unity_or_without_a_lightmap_channel():
    ch = [{"channel": 1, "outside_unit_ratio": 0.2}]
    assert uv.check_lw011(_mesh(ch, lightmap_uv_index=1)) is None  # unreal default
    assert (
        uv.check_lw011(_mesh(ch, lightmap_uv_index=1), engine="unreal") is None
    )
    assert uv.check_lw011(_mesh(ch), engine="unity") is None  # no lightmap channel


def test_lw011_abstains_within_bounds():
    ch = [{"channel": 1, "outside_unit_ratio": 0.0}]
    assert (
        uv.check_lw011(_mesh(ch, lightmap_uv_index=1), engine="unity") is None
    )
