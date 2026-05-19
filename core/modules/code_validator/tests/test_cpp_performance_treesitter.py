"""Tests for Tree-sitter-based Tick body extraction in 9 CP* rules.

Verifies that calls nested 3+ levels deep inside Tick() are detected,
which the old 1-level regex missed.
"""

# flake8: noqa: E402

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "modules"))

from code_validator.unreal.cpp.cpp_performance import detect_ensure_in_tick  # CP015
from code_validator.unreal.cpp.cpp_performance import (
    detect_find_object_in_tick,  # CP001
)
from code_validator.unreal.cpp.cpp_performance import (
    detect_get_all_actors_in_tick,  # CP006
)
from code_validator.unreal.cpp.cpp_performance import (
    detect_get_component_in_tick,  # CP002
)
from code_validator.unreal.cpp.cpp_performance import detect_heavy_math_in_tick  # CP008
from code_validator.unreal.cpp.cpp_performance import detect_new_object_in_loop  # CP013
from code_validator.unreal.cpp.cpp_performance import (
    detect_spawn_actor_in_tick,  # CP018
)
from code_validator.unreal.cpp.cpp_performance import detect_string_ops_in_tick  # CP009
from code_validator.unreal.cpp.cpp_performance import (  # noqa: E402; CP012
    detect_tarray_copy_in_loop,
)

SRC = "MyActor.cpp"


def _deep_tick(inner: str) -> str:
    """Tick body with ``inner`` nested 3 levels deep (if > for > if).

    The legacy 1-level-brace regex stops at the first nested ``{}`` and
    never reaches this call; Tree-sitter walks the full AST.
    """
    return (
        "void AMyActor::Tick(float DeltaTime)\n"
        "{\n"
        "    Super::Tick(DeltaTime);\n"
        "    if (bShouldSearch)\n"
        "    {\n"
        "        for (int i = 0; i < 10; i++)\n"
        "        {\n"
        "            if (i > 0)\n"
        "            {\n"
        f"                {inner}\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


def _deep_loop(inner: str) -> str:
    """Function with ``inner`` nested deep inside a for-loop body."""
    return (
        "void AMyActor::Run()\n"
        "{\n"
        "    if (bGo)\n"
        "    {\n"
        "        for (int i = 0; i < 10; i++)\n"
        "        {\n"
        "            if (i > 0)\n"
        "            {\n"
        f"                {inner}\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


def _clean_tick() -> str:
    return (
        "void AMyActor::Tick(float DeltaTime)\n"
        "{\n"
        "    Super::Tick(DeltaTime);\n"
        "    Position += Velocity * DeltaTime;\n"
        "    HealthBar->SetPercent(Health / MaxHealth);\n"
        "}\n"
    )


def _clean_loop() -> str:
    return (
        "void AMyActor::Run()\n"
        "{\n"
        "    for (int i = 0; i < 10; i++)\n"
        "    {\n"
        "        Total += i;\n"
        "    }\n"
        "}\n"
    )


# ── CP001: FindObjectOfType inside Tick ───────────────────────────────


def test_cp001_deeply_nested_positive():
    src = _deep_tick("UObject* o = FindObjectOfType<UObject>();")
    issues = detect_find_object_in_tick(src, SRC)
    assert len(issues) == 1
    assert issues[0]["rule_id"] == "CP001"
    assert issues[0]["line"] == 10


def test_cp001_clean_negative():
    assert detect_find_object_in_tick(_clean_tick(), SRC) == []


# ── CP002: GetComponent inside Tick ───────────────────────────────────


def test_cp002_deeply_nested_positive():
    src = _deep_tick("auto* c = GetComponent<UMeshComponent>();")
    issues = detect_get_component_in_tick(src, SRC)
    assert len(issues) == 1
    assert issues[0]["rule_id"] == "CP002"
    assert issues[0]["line"] == 10


def test_cp002_clean_negative():
    assert detect_get_component_in_tick(_clean_tick(), SRC) == []


# ── CP006: GetAllActorsOfClass inside Tick ────────────────────────────


def test_cp006_deeply_nested_positive():
    src = _deep_tick("GetAllActorsOfClass<AActor>(this, Out);")
    issues = detect_get_all_actors_in_tick(src, SRC)
    assert len(issues) == 1
    assert issues[0]["rule_id"] == "CP006"
    assert issues[0]["line"] == 10


def test_cp006_clean_negative():
    assert detect_get_all_actors_in_tick(_clean_tick(), SRC) == []


# ── CP008: Heavy math inside Tick ─────────────────────────────────────


def test_cp008_deeply_nested_positive():
    src = _deep_tick("float v = FMath::Sqrt(X * X + Y * Y);")
    issues = detect_heavy_math_in_tick(src, SRC)
    assert len(issues) == 1
    assert issues[0]["rule_id"] == "CP008"
    assert issues[0]["line"] == 10


def test_cp008_clean_negative():
    assert detect_heavy_math_in_tick(_clean_tick(), SRC) == []


# ── CP009: FString operations inside Tick ─────────────────────────────


def test_cp009_deeply_nested_positive():
    src = _deep_tick('FString s = FString::Printf(TEXT("%d"), i);')
    issues = detect_string_ops_in_tick(src, SRC)
    assert len(issues) == 1
    assert issues[0]["rule_id"] == "CP009"
    assert issues[0]["line"] == 10


def test_cp009_clean_negative():
    assert detect_string_ops_in_tick(_clean_tick(), SRC) == []


# ── CP012: TArray copied inside loop ──────────────────────────────────


def test_cp012_deeply_nested_positive():
    src = _deep_loop("TArray<int32> Copy = SourceArray;")
    issues = detect_tarray_copy_in_loop(src, SRC)
    assert len(issues) == 1
    assert issues[0]["rule_id"] == "CP012"
    assert issues[0]["line"] == 9


def test_cp012_clean_negative():
    assert detect_tarray_copy_in_loop(_clean_loop(), SRC) == []


# ── CP013: NewObject called inside loop ───────────────────────────────


def test_cp013_deeply_nested_positive():
    src = _deep_loop("UObject* o = NewObject<UMyObject>();")
    issues = detect_new_object_in_loop(src, SRC)
    assert len(issues) == 1
    assert issues[0]["rule_id"] == "CP013"
    assert issues[0]["line"] == 9


def test_cp013_clean_negative():
    assert detect_new_object_in_loop(_clean_loop(), SRC) == []


# ── CP015: ensure() inside Tick ───────────────────────────────────────


def test_cp015_deeply_nested_positive():
    src = _deep_tick("ensure(bShouldSearch);")
    issues = detect_ensure_in_tick(src, SRC)
    assert len(issues) == 1
    assert issues[0]["rule_id"] == "CP015"
    assert issues[0]["line"] == 10


def test_cp015_clean_negative():
    assert detect_ensure_in_tick(_clean_tick(), SRC) == []


# ── CP018: SpawnActor inside Tick ─────────────────────────────────────


def test_cp018_deeply_nested_positive():
    src = _deep_tick("SpawnActor<AProjectile>(ProjectileClass);")
    issues = detect_spawn_actor_in_tick(src, SRC)
    assert len(issues) == 1
    assert issues[0]["rule_id"] == "CP018"
    assert issues[0]["line"] == 10


def test_cp018_clean_negative():
    assert detect_spawn_actor_in_tick(_clean_tick(), SRC) == []


# ── Regression: legacy single-level case still works ──────────────────


def test_legacy_single_level_still_detected():
    """A call directly in the Tick body (the case the old regex handled)
    must still be flagged after the migration."""
    src = (
        "void AMyActor::Tick(float DeltaTime)\n"
        "{\n"
        "    Super::Tick(DeltaTime);\n"
        "    UObject* o = FindObjectOfType<UObject>();\n"
        "}\n"
    )
    issues = detect_find_object_in_tick(src, SRC)
    assert len(issues) == 1
    assert issues[0]["rule_id"] == "CP001"
    assert issues[0]["line"] == 4


def test_multiple_classes_in_one_file():
    """Tree-sitter must find Tick bodies across multiple classes."""
    src = (
        "void AFirst::Tick(float D)\n"
        "{\n"
        "    Super::Tick(D);\n"
        "}\n"
        "\n"
        "void ASecond::Tick(float D)\n"
        "{\n"
        "    if (true) { for (int i=0;i<2;i++) { if(i){ "
        "SpawnActor<AActor>(); } } }\n"
        "}\n"
    )
    issues = detect_spawn_actor_in_tick(src, SRC)
    assert len(issues) == 1
    assert issues[0]["class"] == "ASecond"
