"""Run 5 smoke tests back-to-back (shared model load)."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "modules"))

from agent.explainer import explain_issue  # noqa: E402
from agent.llm_backend import is_loaded, load_model  # noqa: E402

ISSUES = [
    # TEST 6 — CM002: Function too long (maintainability, auto_fixable=False)
    {
        "rule_id": "CM002",
        "rule_name": "Function too long",
        "rule_explanation": (
            "Detects functions whose body exceeds 80 lines. Long functions "
            "are harder to read, test, and maintain. Split them into smaller "
            "focused helpers. There is no safe automatic way to split a "
            "function — it must be refactored manually."
        ),
        "severity": "warning",
        "category": "Maintainability",
        "file_path": "Source/Player/APlayerCharacter.cpp",
        "line": 120,
        "message": "APlayerCharacter::HandleInput is 143 lines long.",
        "fix_suggestion": "Split HandleInput into smaller focused functions.",
        "is_auto_fixable": False,
        "context_before": (
            "void APlayerCharacter::HandleInput(float DeltaTime)\n"
            "{\n"
            "    // 143 lines of movement, attack, dodge, interaction logic\n"
            "    UpdateMovement(DeltaTime);\n"
            "    HandleCombat(DeltaTime);"
        ),
    },
    # TEST 7 — CP006: GetAllActorsOfClass in Tick (performance, auto_fixable=False)
    {
        "rule_id": "CP006",
        "rule_name": "GetAllActorsOfClass in Tick",
        "rule_explanation": (
            "Detects calls to GetAllActorsOfClass inside Tick(). This "
            "function iterates every actor in the world every frame, which "
            "is O(n) and stalls the game thread when the scene is large. "
            "Cache the result once in BeginPlay and refresh only on "
            "actor spawn/destroy events."
        ),
        "severity": "warning",
        "category": "Performance",
        "file_path": "Source/Managers/ASpawnManager.cpp",
        "line": 61,
        "message": "GetAllActorsOfClass called inside Tick() — iterates every actor every frame.",
        "fix_suggestion": "Cache the actor list in BeginPlay; refresh on spawn/destroy events.",
        "is_auto_fixable": False,
        "context_before": (
            "void ASpawnManager::Tick(float DeltaTime)\n"
            "{\n"
            "    Super::Tick(DeltaTime);\n"
            "    TArray<AActor*> Enemies;\n"
            "    GetAllActorsOfClass(GetWorld(), AEnemy::StaticClass(), Enemies);"
        ),
    },
    # TEST 8 — CS004: Division without zero-check (security, auto_fixable=True)
    {
        "rule_id": "CS004",
        "rule_name": "Division without zero-check",
        "rule_explanation": (
            "Detects division operations where the divisor is not checked "
            "for zero before dividing. Integer division by zero crashes the "
            "engine immediately. Float division by zero produces NaN or Inf, "
            "which silently corrupts downstream calculations. Always guard "
            "with an explicit zero-check before dividing."
        ),
        "severity": "error",
        "category": "Security",
        "file_path": "Source/Stats/UDamageCalculator.cpp",
        "line": 44,
        "message": "Division by 'TotalArmor' without zero-check — crashes on integer, NaN on float.",
        "fix_suggestion": "Guard with 'if (TotalArmor != 0)' before dividing.",
        "is_auto_fixable": True,
        "context_before": (
            "float UDamageCalculator::ComputeFinalDamage(float RawDamage, int32 TotalArmor)\n"
            "{\n"
            "    float Reduction = ArmorFactor / TotalArmor;\n"
            "    return FMath::Max(0.f, RawDamage - Reduction);\n"
            "}"
        ),
    },
    # TEST 9 — BPP001: Blueprint tick with heavy logic (Blueprint performance, auto_fixable=False)
    {
        "rule_id": "BPP001",
        "rule_name": "Heavy logic in Blueprint Tick",
        "rule_explanation": (
            "Detects Blueprint Tick event graphs with more than 15 nodes. "
            "Complex Tick graphs run every frame and incur Blueprint VM "
            "overhead on top of the logic cost. Move heavy per-frame logic "
            "to C++ Tick or use Timers to run less frequently."
        ),
        "severity": "warning",
        "category": "Performance",
        "asset_path": "/Game/Enemies/BP_PatrolEnemy",
        "file_path": "/Game/Enemies/BP_PatrolEnemy",
        "graph": "Tick",
        "line": 0,
        "message": "BP_PatrolEnemy Tick graph has 38 nodes — Blueprint VM overhead every frame.",
        "fix_suggestion": "Move per-frame logic to C++ Tick or throttle with a Timer.",
        "is_auto_fixable": False,
    },
    # TEST 10 — NM003: Texture missing T_ prefix (naming, auto_fixable=True)
    {
        "rule_id": "NM003",
        "rule_name": "Texture missing T_ prefix",
        "rule_explanation": (
            "Detects Texture2D assets that do not start with the required "
            "'T_' prefix. UE5 naming conventions use prefixes to identify "
            "asset types at a glance in the Content Browser. A texture "
            "without 'T_' is easy to confuse with a Material or Blueprint. "
            "ShintTools' Auto-Fix can rename it through the AssetRegistry."
        ),
        "severity": "warning",
        "category": "Naming",
        "asset_path": "/Game/UI/Icons/HealthIcon",
        "file_path": "/Game/UI/Icons/HealthIcon",
        "line": 0,
        "message": "Texture2D 'HealthIcon' is missing the required 'T_' prefix.",
        "fix_suggestion": "Rename to 'T_HealthIcon'.",
        "is_auto_fixable": True,
    },
]


def run_all() -> None:
    if not is_loaded():
        print("Loading model...")
        t0 = time.time()
        load_model()
        print(f"Model loaded in {time.time()-t0:.1f}s\n")
        print("=" * 70)

    for issue in ISSUES:
        rid = issue["rule_id"]
        rname = issue["rule_name"]
        fixable = issue["is_auto_fixable"]
        print(f"\nTEST {rid} — {rname} | auto_fixable={fixable}")
        print("-" * 70)
        t0 = time.time()
        text = explain_issue(issue)
        elapsed = time.time() - t0
        print(f"[{elapsed:.1f}s | {len(text)} chars]")
        print(text)
        print("=" * 70)


if __name__ == "__main__":
    run_all()
