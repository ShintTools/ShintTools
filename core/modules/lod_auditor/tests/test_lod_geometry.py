# Tests for the mesh geometry rules (LG001–LG015).

import pytest

from lod_auditor.rules import lod_geometry as g

_ALL = [
    g.check_lg001,
    g.check_lg002,
    g.check_lg003,
    g.check_lg004,
    g.check_lg005,
    g.check_lg006,
    g.check_lg007,
    g.check_lg008,
    g.check_lg009,
    g.check_lg010,
    g.check_lg011,
    g.check_lg012,
    g.check_lg013,
    g.check_lg014,
    g.check_lg015,
    g.check_lg016,
]


@pytest.mark.parametrize("fn", _ALL, ids=[f.__name__ for f in _ALL])
def test_abstains_on_empty_asset(fn):
    """A v1-shaped asset with none of the v2 fields never false-positives."""
    assert fn({"asset_path": "/Game/X", "asset_type": "StaticMesh"}) is None


def _mesh(**kw):
    base = {"asset_path": "/Game/M", "asset_type": "StaticMesh"}
    base.update(kw)
    return base


def test_lg001_fires_over_cap_and_escalates():
    f = g.check_lg001(_mesh(triangle_count=600_000))
    assert f and f.rule_id == "LG001" and f.severity == "error"
    assert g.check_lg001(_mesh(triangle_count=200_000)).severity == "warning"


def test_lg001_abstains_for_nanite():
    assert g.check_lg001(_mesh(triangle_count=600_000, nanite_enabled=True)) is None


def test_lg002_fires_on_split_heavy():
    f = g.check_lg002(_mesh(triangle_count=10_000, vertex_count=30_000))
    assert f and f.rule_id == "LG002"


def test_lg003_fires_on_dense_scan():
    f = g.check_lg003(_mesh(vertex_count=5_000_000, bounds_radius=40.0))
    assert f and f.rule_id == "LG003" and f.severity == "info"


def test_lg004_error_on_nanite():
    f = g.check_lg004(
        _mesh(degenerate_triangle_count=5, triangle_count=1000, nanite_enabled=True)
    )
    assert f and f.severity == "error"
    assert (
        g.check_lg004(
            _mesh(degenerate_triangle_count=5, triangle_count=100000)
        ).severity
        == "warning"
    )


def test_lg005_warns_over_ratio():
    f = g.check_lg005(_mesh(duplicate_vertex_count=1000, vertex_count=10_000))
    assert f and f.severity == "warning"
    assert (
        g.check_lg005(_mesh(duplicate_vertex_count=100, vertex_count=100_000)).severity
        == "info"
    )


def test_lg006_needs_low_hard_edges():
    hi = {"hard_edge_ratio": 0.5}
    assert (
        g.check_lg006(
            _mesh(overlapping_vertex_count=5000, vertex_count=10_000, normal_stats=hi)
        )
        is None
    )
    lo = {"hard_edge_ratio": 0.05}
    assert (
        g.check_lg006(
            _mesh(overlapping_vertex_count=5000, vertex_count=10_000, normal_stats=lo)
        )
        is not None
    )


def test_lg007_error_for_static_lighting():
    f = g.check_lg007(_mesh(non_manifold_edge_count=3, uses_static_lighting=True))
    assert f and f.severity == "error"
    assert g.check_lg007(_mesh(non_manifold_edge_count=3)).severity == "warning"


def test_lg008_only_for_closed_hull_consumers():
    assert g.check_lg008(_mesh(open_edge_count=10)) is None
    assert (
        g.check_lg008(_mesh(open_edge_count=10, uses_static_lighting=True)) is not None
    )


def test_lg009_fires_on_buried_geometry():
    f = g.check_lg009(_mesh(internal_face_ratio=0.4, triangle_count=50_000))
    assert f and f.rule_id == "LG009"


def test_lg010_only_kit_pieces():
    assert g.check_lg010(_mesh(internal_face_ratio=0.3)) is None
    assert g.check_lg010(_mesh(internal_face_ratio=0.3, is_kit_piece=True)) is not None


def test_lg011_needs_known_used_channels():
    # unknown used channels -> abstain (avoid false positive)
    assert g.check_lg011(_mesh(uv_channel_count=4)) is None
    f = g.check_lg011(_mesh(uv_channel_count=4, lightmap_uv_index=1, vertex_count=1000))
    assert f and f.recommended["uv_channel_count"] == 2


def test_lg012_fires_on_fragmentation():
    assert g.check_lg012(_mesh(section_count=12)) is not None
    assert g.check_lg012(_mesh(material_slot_count=10)) is not None


def test_lg013_fires_on_bad_pivot():
    assert g.check_lg013(_mesh(pivot_offset_ratio=2.0)) is not None


def test_lg014_fires_on_scale():
    assert g.check_lg014(_mesh(import_uniform_scale=100.0)) is not None
    assert g.check_lg014(_mesh(import_scale_nonuniform=True)) is not None
    assert g.check_lg014(_mesh(import_uniform_scale=1.0)) is None


def test_lg015_needs_placement():
    assert (
        g.check_lg015(_mesh(has_negative_scale_instances=True, used_in_levels=0))
        is None
    )
    assert (
        g.check_lg015(_mesh(has_negative_scale_instances=True, used_in_levels=2))
        is not None
    )


def test_lg016_fires_on_unity_without_used_in_levels():
    """LG016 is LG015's Unity complement: no used_in_levels count exists on a
    Unity payload, so the flag alone (which only a scene scan can produce)
    is enough."""
    f = g.check_lg016(_mesh(has_negative_scale_instances=True), engine="unity")
    assert f and f.rule_id == "LG016" and f.severity == "info"
    assert f.auto_fixable is False


def test_lg016_abstains_off_unity():
    assert g.check_lg016(_mesh(has_negative_scale_instances=True)) is None
    assert (
        g.check_lg016(_mesh(has_negative_scale_instances=True), engine="unreal")
        is None
    )


def test_lg016_abstains_without_the_flag():
    assert g.check_lg016(_mesh(), engine="unity") is None
