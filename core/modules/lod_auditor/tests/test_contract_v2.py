# Contract v2 verification: non-breaking regression, Unity engine gate, and the
# golden mesh/material corpora.

import json
from pathlib import Path

import pytest

from lod_auditor.lod_orchestrator import audit_assets

_HERE = Path(__file__).parent


def _ids(assets, **kw):
    return {f.rule_id for f in audit_assets(assets, **kw).results}


# ── Non-breaking regression ───────────────────────────────────────────────────


def test_v1_mesh_payload_unchanged():
    """A v1 mesh (no v2 fields) still produces only its v1 finding."""
    v1 = {
        "asset_path": "/Game/M",
        "asset_type": "StaticMesh",
        "lod_count": 1,
        "lods": [{"index": 0, "triangles": 5000, "screen_size": 1.0}],
        "bounds_radius": 100.0,
        "used_in_levels": 1,
    }
    assert _ids([v1], engine="unreal") == {"LD001"}


def test_v1_texture_payload_unchanged():
    """A v1 texture payload does not gain any Part-2 findings."""
    v1 = {
        "asset_path": "/Game/T",
        "asset_type": "Texture2D",
        "usage": "BaseColor",
        "width": 2048,
        "height": 2048,
        "compression": "BC7",
        "srgb": True,
        "mips_enabled": True,
        "streaming": True,
        "lod_group": "World",
        "referenced_by_materials": 1,
    }
    # Clean v1 texture -> no findings at all.
    assert _ids([v1], engine="unreal") == set()


def test_v1_material_payload_unchanged():
    v1 = {
        "asset_path": "/Game/Mat",
        "asset_type": "Material",
        "blend_mode": "Opaque",
        "instruction_count": 100,
        "sampler_count": 3,
        "used_by_primitives": 1,
        "is_material_instance": True,
    }
    assert _ids([v1], engine="unreal") == set()


# ── Unity engine gate (the one place a wrong answer, not an empty one, matters) ─


@pytest.mark.parametrize("nanite_rule", ["LD012", "LD013"])
def test_nanite_rules_abstain_for_unity(nanite_rule):
    candidate = {
        "asset_path": "/Game/M",
        "asset_type": "StaticMesh",
        "lod_count": 1,
        "triangle_count": 200000,
        "nanite_enabled": True,
        "used_material_blend_modes": ["Opaque", "Translucent"],
        "nanite_fallback_triangle_percent": 80.0,
        "bounds_radius": 300.0,
    }
    assert nanite_rule not in _ids([candidate], engine="unity")
    # And at least one of them fires for unreal (proves the fixture is live).
    assert {"LD012", "LD013"} & _ids([candidate], engine="unreal")


# ── Golden corpora ────────────────────────────────────────────────────────────


def _load(name):
    return json.loads((_HERE / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", _load("golden_meshes.json"), ids=lambda c: c["name"])
def test_golden_meshes(case):
    profile = case.get("profile", "default")
    fired = _ids([case["asset"]], engine="unreal", profile=profile)
    if case.get("expect_empty"):
        assert fired == set(), f"{case['name']} expected clean, got {sorted(fired)}"
    for rid in case.get("expect_contains", []):
        assert rid in fired, f"{case['name']} missing {rid}; got {sorted(fired)}"
    for rid in case.get("expect_absent", []):
        assert rid not in fired, f"{case['name']} unexpectedly fired {rid}"


@pytest.mark.parametrize(
    "case", _load("golden_materials.json"), ids=lambda c: c["name"]
)
def test_golden_materials(case):
    fired = _ids(
        [case["asset"]], engine="unreal", profile=case.get("profile", "default")
    )
    if case.get("expect_empty"):
        assert fired == set(), f"{case['name']} expected clean, got {sorted(fired)}"
    for rid in case.get("expect_contains", []):
        assert rid in fired, f"{case['name']} missing {rid}; got {sorted(fired)}"
    for rid in case.get("expect_absent", []):
        assert rid not in fired, f"{case['name']} unexpectedly fired {rid}"
