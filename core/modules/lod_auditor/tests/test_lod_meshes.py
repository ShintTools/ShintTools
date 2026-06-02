# core/modules/lod_auditor/tests/test_lod_meshes.py

from lod_auditor.rules.lod_meshes import check_ld001, check_ld002, check_ld003

# ── Base fixture ──────────────────────────────────────────────────────────────

_GOOD_LODS: list[dict] = [
    {"index": 0, "triangles": 5_000, "vertices": 3_000, "screen_size": 1.0},
    {"index": 1, "triangles": 2_000, "vertices": 1_200, "screen_size": 0.5},
    {"index": 2, "triangles": 800, "vertices": 480, "screen_size": 0.25},
    {"index": 3, "triangles": 200, "vertices": 120, "screen_size": 0.1},
]

_BASE: dict = {
    "asset_path": "/Game/SM_Test",
    "asset_type": "StaticMesh",
    "lod_count": 4,
    "lods": _GOOD_LODS,
    "bounds_radius": 100.0,
    "used_in_levels": 3,
}


def _mesh(**overrides) -> dict:
    base = dict(_BASE)
    base.update(overrides)
    return base


# ── LD001 ─────────────────────────────────────────────────────────────────────


class TestLD001:
    def test_fires_when_only_lod0(self):
        asset = _mesh(lod_count=1, lods=[_GOOD_LODS[0]])
        result = check_ld001(asset)
        assert result is not None
        assert result.rule_id == "LD001"

    def test_fires_when_lod_count_zero(self):
        asset = _mesh(lod_count=0, lods=[])
        result = check_ld001(asset)
        assert result is not None

    def test_no_finding_with_two_lods(self):
        asset = _mesh(lod_count=2, lods=_GOOD_LODS[:2])
        assert check_ld001(asset) is None

    def test_no_finding_with_four_lods(self):
        assert check_ld001(_BASE) is None

    def test_auto_fixable_is_true(self):
        asset = _mesh(lod_count=1, lods=[_GOOD_LODS[0]])
        result = check_ld001(asset)
        assert result.auto_fixable is True

    def test_severity_is_warning(self):
        asset = _mesh(lod_count=1, lods=[_GOOD_LODS[0]])
        result = check_ld001(asset)
        assert result.severity == "warning"


# ── LD002 ─────────────────────────────────────────────────────────────────────


class TestLD002:
    def test_no_finding_for_good_chain(self):
        assert check_ld002(_BASE) is None

    def test_fires_when_triangle_count_not_decreasing(self):
        bad_lods = [
            {"index": 0, "triangles": 5_000, "vertices": 3_000, "screen_size": 1.0},
            {"index": 1, "triangles": 5_000, "vertices": 3_000, "screen_size": 0.5},
        ]
        result = check_ld002(_mesh(lods=bad_lods))
        assert result is not None
        assert result.rule_id == "LD002"

    def test_fires_when_triangles_increase(self):
        bad_lods = [
            {"index": 0, "triangles": 2_000, "vertices": 1_200, "screen_size": 1.0},
            {"index": 1, "triangles": 5_000, "vertices": 3_000, "screen_size": 0.5},
        ]
        result = check_ld002(_mesh(lods=bad_lods))
        assert result is not None

    def test_fires_when_screen_size_not_decreasing(self):
        bad_lods = [
            {"index": 0, "triangles": 5_000, "vertices": 3_000, "screen_size": 0.5},
            {"index": 1, "triangles": 2_000, "vertices": 1_200, "screen_size": 1.0},
        ]
        result = check_ld002(_mesh(lods=bad_lods))
        assert result is not None

    def test_no_finding_for_single_lod(self):
        asset = _mesh(lod_count=1, lods=[_GOOD_LODS[0]])
        assert check_ld002(asset) is None

    def test_no_finding_for_empty_lods(self):
        asset = _mesh(lod_count=0, lods=[])
        assert check_ld002(asset) is None

    def test_auto_fixable_is_true(self):
        bad_lods = [
            {"index": 0, "triangles": 5_000, "vertices": 3_000, "screen_size": 1.0},
            {"index": 1, "triangles": 5_000, "vertices": 3_000, "screen_size": 0.5},
        ]
        result = check_ld002(_mesh(lods=bad_lods))
        assert result.auto_fixable is True

    def test_current_contains_lod_snapshot(self):
        bad_lods = [
            {"index": 0, "triangles": 5_000, "vertices": 3_000, "screen_size": 1.0},
            {"index": 1, "triangles": 5_000, "vertices": 3_000, "screen_size": 0.5},
        ]
        result = check_ld002(_mesh(lods=bad_lods))
        assert isinstance(result.current["lods"], list)
        assert len(result.current["lods"]) == 2


# ── LD003 ─────────────────────────────────────────────────────────────────────


class TestLD003:
    def test_fires_for_tiny_mesh_over_budget(self):
        # bounds_radius=40 → budget=2000; 5000 > 2000 → fires
        asset = _mesh(
            bounds_radius=40.0,
            lods=[
                {"index": 0, "triangles": 5_000, "vertices": 3_000, "screen_size": 1.0}
            ],
        )
        result = check_ld003(asset)
        assert result is not None
        assert result.rule_id == "LD003"

    def test_no_finding_within_budget(self):
        asset = _mesh(
            bounds_radius=40.0,
            lods=[
                {"index": 0, "triangles": 1_500, "vertices": 900, "screen_size": 1.0}
            ],
        )
        assert check_ld003(asset) is None

    def test_no_finding_exactly_at_budget(self):
        asset = _mesh(
            bounds_radius=40.0,
            lods=[
                {"index": 0, "triangles": 2_000, "vertices": 1_200, "screen_size": 1.0}
            ],
        )
        assert check_ld003(asset) is None

    def test_large_mesh_has_larger_budget(self):
        # bounds_radius=600 → budget=80000; 50000 ≤ 80000 → no finding
        asset = _mesh(
            bounds_radius=600.0,
            lods=[
                {
                    "index": 0,
                    "triangles": 50_000,
                    "vertices": 30_000,
                    "screen_size": 1.0,
                }
            ],
        )
        assert check_ld003(asset) is None

    def test_large_mesh_over_budget_fires(self):
        asset = _mesh(
            bounds_radius=600.0,
            lods=[
                {
                    "index": 0,
                    "triangles": 100_000,
                    "vertices": 60_000,
                    "screen_size": 1.0,
                }
            ],
        )
        result = check_ld003(asset)
        assert result is not None

    def test_no_finding_for_empty_lods(self):
        assert check_ld003(_mesh(lods=[])) is None

    def test_auto_fixable_is_false(self):
        asset = _mesh(
            bounds_radius=40.0,
            lods=[
                {"index": 0, "triangles": 5_000, "vertices": 3_000, "screen_size": 1.0}
            ],
        )
        result = check_ld003(asset)
        assert result.auto_fixable is False

    def test_guidance_is_not_none(self):
        asset = _mesh(
            bounds_radius=40.0,
            lods=[
                {"index": 0, "triangles": 5_000, "vertices": 3_000, "screen_size": 1.0}
            ],
        )
        result = check_ld003(asset)
        assert result.guidance is not None

    def test_current_reports_lod0_triangles_and_radius(self):
        asset = _mesh(
            bounds_radius=40.0,
            lods=[
                {"index": 0, "triangles": 5_000, "vertices": 3_000, "screen_size": 1.0}
            ],
        )
        result = check_ld003(asset)
        assert result.current["lod0_triangles"] == 5_000
        assert result.current["bounds_radius"] == 40.0
