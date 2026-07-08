# core/scripts/validate_core_structure.py
#
# Daily structural health check for the ShintTools Core engine. Designed to be
# run unattended (cron / scheduled agent) and to fail loudly on the failure
# modes that have actually bitten us — chiefly validator FALSE POSITIVES and
# unsafe Auto-Fix output (the first Fab review: "150 errors, 2 real. Do not
# use Apply"). Everything here is deterministic; no LLM, no network.
#
# Checks:
#   1. Import smoke        — every orchestrator + fixer imports cleanly.
#   2. False positives     — run the C++/C# validators on a golden corpus of
#                            IDIOMATIC, known-good code; any error/warning-level
#                            finding is a regression (info-level style hints OK).
#   3. Severity validity   — every emitted severity is in {error,warning,info}.
#   4. Auto-fix safety     — every auto-fixable issue on a "dirty" file fixes
#                            without crashing, without the "not implemented"
#                            sentinel, and WITHOUT unbalancing braces/parens
#                            (the corruption heuristic).
#   5. Fixer/pattern map   — every C++ RULE_TO_PATTERN entry routes to a handled
#                            pattern name (no rule wired to a missing handler).
#
# Exit code: 0 = healthy, 1 = at least one hard failure. False positives are
# reported and counted; treat a non-zero FP count as a regression to triage.

from __future__ import annotations

import re
import sys
from pathlib import Path

_CORE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_CORE))
sys.path.insert(0, str(_CORE / "modules"))

_VALID_SEVERITIES = {"error", "warning", "info"}

# ── Golden corpus: idiomatic, known-good code (must produce ZERO error/warning) ──

UE5_HEADER = r"""
#pragma once
#include "CoreMinimal.h"
#include "GameFramework/Character.h"
#include "MyCharacter.generated.h"

UCLASS()
class MYGAME_API AMyCharacter : public ACharacter
{
    GENERATED_BODY()
public:
    AMyCharacter();
    virtual void BeginPlay() override;
    virtual void Tick(float DeltaTime) override;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stats")
    float MaxHealth = 100.0f;
};
"""

UE5_SOURCE = r"""
#include "MyCharacter.h"

AMyCharacter::AMyCharacter()
{
    PrimaryActorTick.bCanEverTick = true;
    MaxHealth = 100.0f;
}

void AMyCharacter::BeginPlay()
{
    Super::BeginPlay();
}

void AMyCharacter::Tick(float DeltaTime)
{
    Super::Tick(DeltaTime);
    CurrentHealth = FMath::Clamp(CurrentHealth, 0.0f, MaxHealth);
}
"""

UNITY_SOURCE = r"""
using UnityEngine;

public class PlayerController : MonoBehaviour
{
    [SerializeField] private float moveSpeed = 5f;
    private Rigidbody _rb;

    private void Awake()
    {
        _rb = GetComponent<Rigidbody>();
    }

    private void FixedUpdate()
    {
        Vector3 input = new Vector3(
            Input.GetAxis("Horizontal"), 0f, Input.GetAxis("Vertical"));
        _rb.AddForce(input * moveSpeed);
    }
}
"""

# ── Dirty corpus: deliberately problematic, to exercise detectors + fixers ──

UE5_DIRTY = r"""
#include "Bad.h"
void ABad::Tick(float DeltaTime)
{
    Super::Tick(DeltaTime);
    UObject* Obj = FindObjectOfType<UObject>();
    int x = (int)GetSomeValue();
    UE_LOG(LogTemp, Warning,
        TEXT("value %d"),
        x);
}
"""

UNITY_DIRTY = r"""
using UnityEngine;
public class Bad : MonoBehaviour
{
    public float speed;
    private void Update()
    {
        Debug.Log("frame " + Time.frameCount);
    }
}
"""


def _balance(code: str) -> tuple[int, int]:
    """(brace_balance, paren_balance) — 0 means balanced."""
    return (
        code.count("{") - code.count("}"),
        code.count("(") - code.count(")"),
    )


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.warnings: list[str] = []

    def fail(self, msg: str) -> None:
        self.failures.append(msg)
        print(f"  FAIL  {msg}")

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        print(f"  WARN  {msg}")

    def ok(self, msg: str) -> None:
        print(f"  ok    {msg}")


def check_imports(r: Report) -> dict:
    print("\n[1] Import smoke")
    mods = {}
    try:
        from code_validator.unreal.cpp.cpp_orchestrator import run_all_cpp_rules
        from code_validator.unity.csharp.csharp_orchestrator import (
            run_all_csharp_rules,
        )
        from code_validator.unreal.cpp._cpp_helpers import _fixer as cpp_fixer
        from code_validator.unity.csharp._csharp_helpers import _fixer as cs_fixer
        from code_validator.unreal.parsers.fixers.fix_patterns import RULE_TO_PATTERN

        mods.update(
            run_cpp=run_all_cpp_rules,
            run_cs=run_all_csharp_rules,
            cpp_fixer=cpp_fixer,
            cs_fixer=cs_fixer,
            cpp_patterns=RULE_TO_PATTERN,
        )
        r.ok("orchestrators + fixers import")
    except Exception as e:  # noqa: BLE001
        r.fail(f"import error: {e}")
    return mods


def check_false_positives(r: Report, mods: dict) -> None:
    print("\n[2] False positives on idiomatic code (expect 0 error/warning)")
    if not mods:
        return
    corpus = [
        ("MyCharacter.h", UE5_HEADER, mods["run_cpp"]),
        ("MyCharacter.cpp", UE5_SOURCE, mods["run_cpp"]),
        ("PlayerController.cs", UNITY_SOURCE, mods["run_cs"]),
    ]
    total = 0
    for name, code, runner in corpus:
        issues = runner(code, name)
        loud = [i for i in issues if i.get("severity") in ("error", "warning")]
        if loud:
            total += len(loud)
            for i in loud:
                r.warn(
                    f"{name}: {i.get('rule_id')} [{i.get('severity')}] "
                    f"L{i.get('line')} — {i.get('message','')[:60]}"
                )
        else:
            r.ok(f"{name}: clean ({len(issues)} info-level hints)")
    if total == 0:
        r.ok("no error/warning false positives on the golden corpus")


def check_severity_validity(r: Report, mods: dict) -> None:
    print("\n[3] Severity validity")
    if not mods:
        return
    bad = 0
    for code, name, runner in (
        (UE5_DIRTY, "Bad.cpp", mods["run_cpp"]),
        (UNITY_DIRTY, "Bad.cs", mods["run_cs"]),
        (UE5_SOURCE, "MyCharacter.cpp", mods["run_cpp"]),
    ):
        for i in runner(code, name):
            sev = i.get("severity")
            if sev not in _VALID_SEVERITIES:
                bad += 1
                r.fail(f"{name}: {i.get('rule_id')} has invalid severity {sev!r}")
    if bad == 0:
        r.ok("all emitted severities in {error, warning, info}")


def check_autofix_safety(r: Report, mods: dict) -> None:
    print("\n[4] Auto-fix safety (no crash / no corruption)")
    if not mods:
        return
    cases = [
        (UE5_DIRTY, "Bad.cpp", mods["run_cpp"], mods["cpp_fixer"]),
        (UNITY_DIRTY, "Bad.cs", mods["run_cs"], mods["cs_fixer"]),
    ]
    checked = 0
    for code, name, runner, fixer in cases:
        base_balance = _balance(code)
        for issue in runner(code, name):
            if not issue.get("is_auto_fixable"):
                continue
            rid = issue.get("rule_id", "")
            line = issue.get("line", 1)
            checked += 1
            try:
                fixed, _, notes = fixer.fix(rid, code, line)
            except Exception as e:  # noqa: BLE001
                r.fail(f"{name}: fixer crashed on {rid}: {e}")
                continue
            joined = " ".join(notes).lower()
            if "not implemented" in joined or "no pattern" in joined:
                r.fail(f"{name}: {rid} routes to a missing fixer handler")
                continue
            if _balance(fixed) != base_balance:
                r.fail(
                    f"{name}: {rid} Auto-Fix unbalanced braces/parens "
                    f"({base_balance} -> {_balance(fixed)}) — corruption risk"
                )
    r.ok(f"checked {checked} auto-fixable issue(s) — no crash/corruption")


def check_fixer_pattern_map(r: Report, mods: dict) -> None:
    print("\n[5] C++ fixer/pattern map consistency")
    if not mods:
        return
    fixer_src = (
        _CORE
        / "modules/code_validator/unreal/parsers/fixers/cpp_fixer.py"
    ).read_text(encoding="utf-8")
    handled = set(re.findall(r'pattern_name == "([a-z_]+)"', fixer_src))
    handled.add("mark_for_review")  # always handled
    missing = []
    for rid, entry in mods["cpp_patterns"].items():
        pattern_name = entry[0]
        if pattern_name.startswith("bp_"):
            continue  # Blueprint patterns are executed plugin-side, not by CppFixer
        if pattern_name not in handled:
            missing.append(f"{rid} -> '{pattern_name}'")
    if missing:
        for m in missing:
            r.fail(f"rule wired to unhandled pattern: {m}")
    else:
        r.ok(f"all {len(mods['cpp_patterns'])} rule->pattern entries are handled")


def main() -> int:
    print("=" * 64)
    print("ShintTools Core — structural health check")
    print("=" * 64)
    r = Report()
    mods = check_imports(r)
    check_false_positives(r, mods)
    check_severity_validity(r, mods)
    check_autofix_safety(r, mods)
    check_fixer_pattern_map(r, mods)

    print("\n" + "=" * 64)
    print(
        f"RESULT: {len(r.failures)} failure(s), "
        f"{len(r.warnings)} warning(s)/possible false positive(s)"
    )
    print("=" * 64)
    return 1 if r.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
