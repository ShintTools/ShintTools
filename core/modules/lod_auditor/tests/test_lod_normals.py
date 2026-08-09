# Tests for the normal & tangent rules (LN001–LN006).

import pytest

from lod_auditor.rules import lod_normals as n

_ALL = [
    n.check_ln001,
    n.check_ln002,
    n.check_ln003,
    n.check_ln004,
    n.check_ln005,
    n.check_ln006,
    n.check_ln007,
]


@pytest.mark.parametrize("fn", _ALL, ids=[f.__name__ for f in _ALL])
def test_abstains_without_normal_stats(fn):
    assert fn({"asset_path": "/Game/M", "asset_type": "StaticMesh"}) is None


def _mesh(ns, **kw):
    base = {"asset_path": "/Game/M", "asset_type": "StaticMesh", "normal_stats": ns}
    base.update(kw)
    return base


def test_ln001_missing_normals():
    f = n.check_ln001(_mesh({"has_normals": False, "recompute_normals": False}))
    assert f and f.severity == "error"
    assert (
        n.check_ln001(_mesh({"has_normals": False, "recompute_normals": True})) is None
    )


def test_ln002_invalid_normals_escalates():
    f = n.check_ln002(_mesh({"zero_normal_count": 500}, vertex_count=10_000))
    assert f and f.severity == "error"
    assert (
        n.check_ln002(_mesh({"zero_normal_count": 1}, vertex_count=100_000)).severity
        == "warning"
    )


def test_ln003_tangent_legs():
    legacy = n.check_ln003(_mesh({"tangent_space": "legacy"}))
    assert legacy and legacy.rule_id == "LN003"
    no_tan = n.check_ln003(
        _mesh({"has_tangents": False}, has_normal_mapped_material=True)
    )
    assert no_tan is not None
    # no tangents but no normal-mapped material -> abstain
    assert n.check_ln003(_mesh({"has_tangents": False})) is None


def test_ln004_hard_edges():
    f = n.check_ln004(_mesh({"hard_edge_ratio": 0.7}, vertex_count=5000))
    assert f and f.rule_id == "LN004"


def test_ln005_single_group():
    f = n.check_ln005(
        _mesh({"smoothing_group_count": 1, "hard_edge_ratio": 0.0}, triangle_count=5000)
    )
    assert f and f.rule_id == "LN005"


def test_ln006_recompute_discards():
    f = n.check_ln006(
        _mesh({"recompute_normals": True, "has_normals": True, "zero_normal_count": 0})
    )
    assert f and f.recommended["recompute_normals"] is False


def test_ln007_high_mirrored_ratio_is_engine_neutral():
    """Unlike LG016/LW011, LN007 has no engine gate — mirrored_tangent_ratio
    is real on both UE5 and Unity payloads and no other rule reads it."""
    unreal = n.check_ln007(_mesh({"mirrored_tangent_ratio": 0.9}), engine="unreal")
    unity = n.check_ln007(_mesh({"mirrored_tangent_ratio": 0.9}), engine="unity")
    assert unreal and unreal.rule_id == "LN007" and unreal.severity == "info"
    assert unity and unity.rule_id == "LN007"


def test_ln007_abstains_below_threshold_or_without_tangents():
    # Routine partial mirroring (a symmetric character) stays quiet.
    assert n.check_ln007(_mesh({"mirrored_tangent_ratio": 0.4})) is None
    # No tangents at all is LN003's territory, not LN007's.
    assert (
        n.check_ln007(
            _mesh({"mirrored_tangent_ratio": 0.9, "has_tangents": False})
        )
        is None
    )
