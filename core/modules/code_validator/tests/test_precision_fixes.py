"""Regression tests for the marketplace-review precision + Apply-safety fixes.

Driven by the first Fab review ("Out of 150 errors, 2 are actual errors.
Do not use 'Apply' !!!"). These lock in:

  * CP007 — no longer false-fires on the canonical
    `PrimaryActorTick.bCanEverTick = true` of an actor that genuinely ticks,
    and its Auto-Fix no longer silently flips the value (now mark_for_review).
  * CB010 — skips direct literal assignments (`X = 100.0f;`) and is demoted to
    `info` so style nits don't inflate the editor's error count.
  * CB008 — demoted to `info`.
  * CB012 fixer — never rewrites a control-flow `if (x) Foo()` as a cast.
  * delete_line — removes a whole multi-line statement, never just its first
    line (which would orphan the argument lines and not compile).
"""

import os
import sys

_CORE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, _CORE)
sys.path.insert(0, os.path.join(_CORE, "modules"))
sys.path.insert(
    0,
    os.path.join(_CORE, "modules", "code_validator", "unreal", "parsers", "fixers"),
)

from code_validator.unreal.cpp.cpp_best_practices import (  # noqa: E402
    detect_float_no_suffix,
    detect_magic_numbers,
)
from code_validator.unreal.cpp.cpp_performance import (  # noqa: E402
    detect_tick_enabled_in_constructor,
)

from cpp_fixer import CppFixer  # noqa: E402

_FIXER = CppFixer()


# ── CP007: tick-in-constructor false positive + unsafe Apply ───────────────

_CTOR_TICK = (
    "AMyActor::AMyActor()\n"
    "{\n"
    "    PrimaryActorTick.bCanEverTick = true;\n"
    "}\n"
)


class TestCP007Precision:
    def test_silent_when_actor_has_real_tick(self):
        code = _CTOR_TICK + (
            "void AMyActor::Tick(float DeltaTime)\n"
            "{\n"
            "    Super::Tick(DeltaTime);\n"
            "    Health -= DeltaTime;\n"
            "}\n"
        )
        assert detect_tick_enabled_in_constructor(code, "A.cpp") == []

    def test_fires_when_tick_enabled_but_unused(self):
        # No Tick override at all → enabling it is genuinely wasteful.
        issues = detect_tick_enabled_in_constructor(_CTOR_TICK, "A.cpp")
        assert len(issues) == 1
        assert issues[0]["rule_id"] == "CP007"

    def test_silent_when_tick_is_empty_super_only(self):
        code = _CTOR_TICK + (
            "void AMyActor::Tick(float DeltaTime)\n"
            "{\n"
            "    Super::Tick(DeltaTime);\n"
            "}\n"
        )
        # Empty/Super-only Tick = unused → CP007 still fires (the real waste).
        issues = detect_tick_enabled_in_constructor(code, "A.cpp")
        assert len(issues) == 1

    def test_cp007_is_not_auto_fixable(self):
        issues = detect_tick_enabled_in_constructor(_CTOR_TICK, "A.cpp")
        assert issues[0]["is_auto_fixable"] is False

    def test_fixer_marks_for_review_never_flips(self):
        fixed, _, _ = _FIXER.fix("CP007", _CTOR_TICK, line_number=3)
        assert "[SHINTTOOLS REVIEW]" in fixed
        assert "= true" in fixed  # original code preserved
        assert "bCanEverTick = false" not in fixed  # never silently disabled


# ── CB010: magic-number noise + severity ───────────────────────────────────


class TestCB010Precision:
    def test_skips_direct_literal_assignment(self):
        code = "void A::S() {\n    MaxHealth = 100.0f;\n    BaseRate = 45.0f;\n}"
        assert detect_magic_numbers(code, "A.cpp") == []

    def test_skips_uproperty_default(self):
        code = "UCLASS() class A {\n    float MaxHealth = 100.0f;\n};"
        assert detect_magic_numbers(code, "A.h") == []

    def test_flags_magic_in_expression(self):
        code = "void A::S() {\n    Damage = Base * 100 + 7;\n}"
        issues = detect_magic_numbers(code, "A.cpp")
        assert any(i["rule_id"] == "CB010" for i in issues)

    def test_flags_magic_in_call_argument(self):
        code = "void A::S() {\n    InitSize(42.0f, 96.0f);\n}"
        issues = detect_magic_numbers(code, "A.cpp")
        assert len(issues) == 1

    def test_severity_is_info(self):
        code = "void A::S() {\n    Damage = Base * 100;\n}"
        issues = detect_magic_numbers(code, "A.cpp")
        assert issues and all(i["severity"] == "info" for i in issues)


# ── CB008: float-suffix severity ───────────────────────────────────────────


def test_cb008_severity_is_info():
    code = "void A::S() {\n    float Rate = 1.5;\n}"
    issues = detect_float_no_suffix(code, "A.cpp")
    assert issues and all(i["severity"] == "info" for i in issues)


# ── CB012 fixer: must not corrupt control flow ─────────────────────────────


class TestCB012FixerSafety:
    def test_does_not_rewrite_if_condition(self):
        code = "void A::S()\n{\n    if (bFlag) DoThing();\n}"
        fixed, _, _ = _FIXER.fix("CB012", code, line_number=3)
        assert "static_cast<bFlag>" not in fixed
        assert "if (bFlag) DoThing();" in fixed

    def test_still_fixes_real_c_style_cast(self):
        code = "void A::S()\n{\n    int x = (int)y;\n}"
        fixed, _, _ = _FIXER.fix("CB012", code, line_number=3)
        assert "static_cast<int>(y)" in fixed


# ── delete_line: multi-line statement safety ───────────────────────────────


class TestDeleteLineSafety:
    def test_removes_whole_multiline_statement(self):
        code = (
            "void A::S()\n"
            "{\n"
            "    UE_LOG(LogTemp, Warning,\n"
            '        TEXT("health %f"),\n'
            "        CurrentHealth);\n"
            "    Keep();\n"
            "}"
        )
        fixed, _, _ = _FIXER.fix("CP004", code, line_number=3)
        # The entire UE_LOG is gone — no orphaned argument lines remain.
        assert "UE_LOG" not in fixed
        assert "CurrentHealth);" not in fixed
        assert 'TEXT("health %f")' not in fixed
        assert "Keep();" in fixed  # the next statement is untouched

    def test_single_line_deletes_only_that_line(self):
        code = (
            "void A::Update()\n"
            "{\n"
            "    // TODO: fix later\n"
            "    DoSomething();\n"
            "}"
        )
        fixed, _, _ = _FIXER.fix("CM003", code, line_number=3)
        assert "TODO" not in fixed
        assert "DoSomething();" in fixed  # following statement preserved
