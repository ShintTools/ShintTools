# Tests for the texture-completion rules (LT009–LT016) and cross rules
# (LX004–LX006, LT015).

import pytest

from lod_auditor.rules import lod_cross as x
from lod_auditor.rules import lod_textures as t

_ALL = [t.check_lt009, t.check_lt010, t.check_lt013, t.check_lt014, t.check_lt016]


@pytest.mark.parametrize("fn", _ALL, ids=[f.__name__ for f in _ALL])
def test_abstains_on_bare_texture(fn):
    assert fn({"asset_path": "/Game/T", "asset_type": "Texture2D"}) is None


def _tex(**kw):
    base = {"asset_path": "/Game/T", "asset_type": "Texture2D", "usage": "BaseColor"}
    base.update(kw)
    return base


def test_lt009_missing_mips_escalates():
    world = t.check_lt009(
        _tex(mips_enabled=False, width=2048, height=2048, lod_group="World")
    )
    assert world.severity == "error"
    other = t.check_lt009(
        _tex(mips_enabled=False, width=2048, height=2048, lod_group="Character")
    )
    assert other.severity == "warning"
    # UI is exempt
    assert (
        t.check_lt009(_tex(usage="UI", mips_enabled=False, width=2048, height=2048))
        is None
    )


def test_lt010_wrong_group():
    f = t.check_lt010(_tex(usage="Normal", lod_group="World"))
    assert f and f.recommended["lod_group"] == "NormalMap"
    assert t.check_lt010(_tex(usage="Normal", lod_group="WorldNormalMap")) is None


def test_lt010_abstains_on_unity():
    # Texture LOD groups are a UE5 concept — the rule must never fire for
    # Unity, even for an asset that would trip it under Unreal.
    tex = _tex(usage="Normal", lod_group="World")
    assert t.check_lt010(tex, engine="unreal") is not None
    assert t.check_lt010(tex, engine="unity") is None


def test_lt013_pack_candidates():
    f = t.check_lt013(_tex(usage="Mask", pack_candidates=["/A", "/B", "/C"]))
    assert f and f.rule_id == "LT013"
    assert t.check_lt013(_tex(usage="Mask", pack_candidates=["/A"])) is None


def test_lt014_memory_ceiling():
    f = t.check_lt014(_tex(width=8192, height=8192, compression="RGBA8"))
    assert f and f.severity == "error" and f.estimated_saving.vram_mb > 0


def test_lt016_never_stream():
    assert t.check_lt016(_tex(usage="UI", streaming=True)) is not None
    assert t.check_lt016(_tex(usage="UI", streaming=False)) is None


def test_lx004_unused_instance():
    assets = [
        {
            "asset_path": "/Game/MI",
            "asset_type": "MaterialInstanceConstant",
            "used_by_primitives": 0,
            "child_instance_count": 0,
            "size_kb": 100,
        }
    ]
    out = x.check_lx004_unused_material_instance(assets)
    assert out and out[0].rule_id == "LX004"


def test_lx005_duplicate_textures():
    assets = [
        {
            "asset_path": "/Game/A",
            "asset_type": "Texture2D",
            "content_hash": "h",
            "size_kb": 500,
            "width": 2048,
            "height": 2048,
            "compression": "BC7",
        },
        {
            "asset_path": "/Game/B",
            "asset_type": "Texture2D",
            "content_hash": "h",
            "size_kb": 500,
            "width": 2048,
            "height": 2048,
            "compression": "BC7",
        },
    ]
    out = x.check_lx005_duplicate_textures(assets)
    assert len(out) == 1 and out[0].rule_id == "LX005"


def test_lx006_same_source_multisize():
    assets = [
        {
            "asset_path": "/Game/A",
            "asset_type": "Texture2D",
            "source_guid": "g",
            "max_texture_size": 2048,
        },
        {
            "asset_path": "/Game/B",
            "asset_type": "Texture2D",
            "source_guid": "g",
            "max_texture_size": 1024,
        },
    ]
    out = x.check_lx006_same_source_multisize(assets)
    assert len(out) == 1 and out[0].rule_id == "LX006"


def test_lt015_streaming_pool():
    big = [
        {
            "asset_path": f"/Game/T{i}",
            "asset_type": "Texture2D",
            "streaming": True,
            "width": 8192,
            "height": 8192,
            "compression": "RGBA8",
            "mips_enabled": True,
        }
        for i in range(20)
    ]
    out = x.check_lt015_streaming_pool(big)
    assert (
        len(out) == 1 and out[0].rule_id == "LT015" and out[0].asset_path == "<project>"
    )
    assert x.check_lt015_streaming_pool([]) == []
