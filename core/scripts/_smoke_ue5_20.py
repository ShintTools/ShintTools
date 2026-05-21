# core/scripts/_smoke_ue5_20.py
#
# 20-case smoke test for UE5: C++ (10), Blueprints (6), Naming (4).
# Run from core/:  python -m scripts._smoke_ue5_20

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.agent.explainer import explain_issue  # noqa: E402
from modules.agent.llm_backend import load_model  # noqa: E402

CASES: List[Dict[str, Any]] = [
    # ── C++ Security (CS) ──────────────────────────────────────────────────
    {
        "label": "[CS001] GetWorld null-check",
        "issue": {
            "rule_id": "CS001",
            "rule_name": "GetWorld without null-check",
            "rule_explanation": (
                "GetWorld() can return nullptr in editor utilities, "
                "commandlets, or during shutdown. Always guard with "
                "'if (UWorld* W = GetWorld())' before dereferencing."
            ),
            "file_path": "Source/MyGame/Actors/SpawnManager.cpp",
            "line": 34,
            "severity": "error",
            "category": "security",
            "message": "GetWorld() result dereferenced without null-check",
            "is_auto_fixable": False,
            "context_before": (
                "void ASpawnManager::BeginPlay()\n"
                "{\n"
                "    UWorld* World = GetWorld();\n"
                "    World->SpawnActor<AEnemy>("
                "EnemyClass, SpawnLoc, FRotator::ZeroRotator);\n"
                "}\n"
            ),
        },
    },
    {
        "label": "[CS003] Cast<T> null-check",
        "issue": {
            "rule_id": "CS003",
            "rule_name": "Cast result used without null-check",
            "rule_explanation": (
                "Cast<T> returns nullptr if the object is not of the "
                "expected type. Always check the result before "
                "dereferencing."
            ),
            "file_path": "Source/MyGame/Components/HealthComponent.cpp",
            "line": 52,
            "severity": "error",
            "category": "security",
            "message": "Cast<T> result used on next line without null-check",
            "is_auto_fixable": False,
            "context_before": (
                "void UHealthComponent::OnDamageTaken(AActor* Instigator)\n"
                "{\n"
                "    APlayerCharacter* Player = Cast<APlayerCharacter>(Instigator);\n"
                "    Player->AddKillCount(1);\n"
                "}\n"
            ),
        },
    },
    {
        "label": "[CS006] GetOwner null-check",
        "issue": {
            "rule_id": "CS006",
            "rule_name": "GetOwner used without null-check",
            "rule_explanation": (
                "GetOwner() returns nullptr for Actors that have no "
                "owner, during shutdown, or in editor utilities. Always "
                "guard with 'if (AActor* Owner = GetOwner())' before use."
            ),
            "file_path": "Source/MyGame/Components/WeaponComponent.cpp",
            "line": 77,
            "severity": "error",
            "category": "security",
            "message": "GetOwner() result dereferenced without null-check",
            "is_auto_fixable": False,
            "context_before": (
                "void UWeaponComponent::Fire()\n"
                "{\n"
                "    AActor* Owner = GetOwner();\n"
                "    Owner->TakeDamage(10.f, FDamageEvent(), nullptr, this);\n"
                "}\n"
            ),
        },
    },
    # ── C++ Performance (CP) ───────────────────────────────────────────────
    {
        "label": "[CP001] FindObjectOfType in Tick",
        "issue": {
            "rule_id": "CP001",
            "rule_name": "FindObject in Tick",
            "rule_explanation": (
                "FindObjectOfType inside Tick or Update searches all "
                "scene objects every frame, destroying performance. "
                "Cache the reference in BeginPlay instead."
            ),
            "file_path": "Source/MyGame/Actors/UIManager.cpp",
            "line": 88,
            "severity": "error",
            "category": "performance",
            "message": "FindObjectOfType called inside Tick",
            "is_auto_fixable": False,
            "context_before": (
                "void AUIManager::Tick(float DeltaTime)\n"
                "{\n"
                "    Super::Tick(DeltaTime);\n"
                "    AGameMode* GM = FindObjectOfType<AGameMode>();\n"
                "    if (GM) UpdateHUD(GM->GetScore());\n"
                "}\n"
            ),
        },
    },
    {
        "label": "[CP002] GetComponent in Tick",
        "issue": {
            "rule_id": "CP002",
            "rule_name": "GetComponent in Tick",
            "rule_explanation": (
                "GetComponent or GetComponentByClass inside Tick or "
                "Update retrieves the component every frame. Cache the "
                "reference in BeginPlay, not every frame."
            ),
            "file_path": "Source/MyGame/Actors/EnemyCharacter.cpp",
            "line": 61,
            "severity": "warning",
            "category": "performance",
            "message": "GetComponent called inside Tick",
            "is_auto_fixable": False,
            "context_before": (
                "void AEnemyCharacter::Tick(float DeltaTime)\n"
                "{\n"
                "    Super::Tick(DeltaTime);\n"
                "    UHealthComponent* HP = GetComponentByClass<UHealthComponent>();\n"
                "    if (HP && HP->IsDead()) Destroy();\n"
                "}\n"
            ),
        },
    },
    {
        "label": "[CP006] GetAllActorsOfClass in Tick",
        "issue": {
            "rule_id": "CP006",
            "rule_name": "GetAllActorsOfClass in Tick",
            "rule_explanation": (
                "GetAllActorsOfClass or GetAllActorsWithInterface inside "
                "Tick iterates every actor in the scene every frame — "
                "one of the most expensive operations in UE5. Cache "
                "results in BeginPlay or use an event-driven approach."
            ),
            "file_path": "Source/MyGame/Managers/EnemyTracker.cpp",
            "line": 43,
            "severity": "error",
            "category": "performance",
            "message": "GetAllActorsOfClass called inside Tick",
            "is_auto_fixable": False,
            "context_before": (
                "void AEnemyTracker::Tick(float DeltaTime)\n"
                "{\n"
                "    TArray<AActor*> Enemies;\n"
                "    UGameplayStatics::GetAllActorsOfClass(\n"
                "        GetWorld(), AEnemy::StaticClass(), Enemies);\n"
                "    UpdateRadar(Enemies);\n"
                "}\n"
            ),
        },
    },
    {
        "label": "[CP018] SpawnActor in Tick",
        "issue": {
            "rule_id": "CP018",
            "rule_name": "SpawnActor in Tick",
            "rule_explanation": (
                "SpawnActor calls inside Tick or Update create new "
                "actors every frame, exhausting memory and overwhelming "
                "the garbage collector. Move spawning to BeginPlay, "
                "events, or timers."
            ),
            "file_path": "Source/MyGame/Actors/ParticleEmitter.cpp",
            "line": 29,
            "severity": "error",
            "category": "performance",
            "message": "SpawnActor called inside Tick",
            "is_auto_fixable": False,
            "context_before": (
                "void AParticleEmitter::Tick(float DeltaTime)\n"
                "{\n"
                "    Super::Tick(DeltaTime);\n"
                "    GetWorld()->SpawnActor<AParticle>(\n"
                "        ParticleClass, GetActorLocation(), FRotator::ZeroRotator);\n"
                "}\n"
            ),
        },
    },
    # ── C++ Best Practices (CB) ────────────────────────────────────────────
    {
        "label": "[CB003] Raw new operator",
        "issue": {
            "rule_id": "CB003",
            "rule_name": "Raw new operator",
            "rule_explanation": (
                "In UE5, objects should be created with NewObject<T>() "
                "or CreateDefaultSubobject<T>(). Raw new bypasses the "
                "garbage collector and causes memory leaks."
            ),
            "file_path": "Source/MyGame/Systems/InventorySystem.cpp",
            "line": 18,
            "severity": "error",
            "category": "best_practices",
            "message": "Raw 'new' used — UE5 GC will not manage this object",
            "is_auto_fixable": False,
            "context_before": (
                "void UInventorySystem::Initialize()\n"
                "{\n"
                "    ItemDatabase = new UItemDatabase();\n"
                "    ItemDatabase->LoadFromDisk();\n"
                "}\n"
            ),
        },
    },
    {
        "label": "[CB010] Magic numbers",
        "issue": {
            "rule_id": "CB010",
            "rule_name": "Magic numbers in expression",
            "rule_explanation": (
                "Numeric literals used directly in expressions without "
                "a named constant reduce readability and make the code "
                "hard to maintain. Extract them to named constexpr "
                "constants. Skips 0, 1, -1 and array declarations."
            ),
            "file_path": "Source/MyGame/Actors/PlayerCharacter.cpp",
            "line": 105,
            "severity": "warning",
            "category": "best_practices",
            "message": "Magic number 350.0f used directly in expression",
            "is_auto_fixable": False,
            "context_before": (
                "void APlayerCharacter::ApplySpeedBoost()\n"
                "{\n"
                "    GetCharacterMovement()->MaxWalkSpeed = 350.0f * 1.5f;\n"
                "    SpeedBoostActive = true;\n"
                "}\n"
            ),
        },
    },
    # ── C++ Maintainability (CM) ───────────────────────────────────────────
    {
        "label": "[CM002] Function too long",
        "issue": {
            "rule_id": "CM002",
            "rule_name": "Function body too long",
            "rule_explanation": (
                "Functions whose body exceeds 80 lines are hard to "
                "read, test, and maintain. Split them into smaller "
                "functions with clear responsibilities."
            ),
            "file_path": "Source/MyGame/Actors/QuestManager.cpp",
            "line": 200,
            "severity": "warning",
            "category": "maintainability",
            "message": "Function 'ProcessQuestCompletion' has 112 lines",
            "is_auto_fixable": False,
            "context_before": (
                "void AQuestManager::ProcessQuestCompletion(\n"
                "    UQuest* Quest, APlayerCharacter* Player)\n"
                "{\n"
                "    // 112-line function body ...\n"
                "}\n"
            ),
        },
    },
    # ── Blueprint Performance (BPP) ────────────────────────────────────────
    {
        "label": "[BPP001] Tick enabled in Blueprint (auto-fix)",
        "issue": {
            "rule_id": "BPP001",
            "rule_name": "Tick enabled in Blueprint",
            "rule_explanation": (
                "Tick runs every frame — disable it if the Blueprint "
                "does not need per-frame updates. Use timers or events "
                "instead whenever possible."
            ),
            "file_path": "/Game/Blueprints/BP_TreasureChest",
            "severity": "warning",
            "category": "performance",
            "asset_path": "/Game/Blueprints/BP_TreasureChest",
            "graph": "Class Defaults",
            "message": "BP_TreasureChest has bCanEverTick=true with no Tick logic",
            "is_auto_fixable": True,
        },
    },
    {
        "label": "[BPP003] Heavy EventTick graph",
        "issue": {
            "rule_id": "BPP003",
            "rule_name": "Heavy EventTick graph",
            "rule_explanation": (
                "Too many nodes in the EventTick graph — heavy Tick "
                "logic runs every frame. Move infrequent logic to "
                "timers or events to reduce per-frame cost."
            ),
            "file_path": "/Game/Blueprints/BP_EnemyAI",
            "severity": "warning",
            "category": "performance",
            "asset_path": "/Game/Blueprints/BP_EnemyAI",
            "graph": "EventTick",
            "message": "EventTick graph has 68 nodes — exceeds the 40-node limit",
            "is_auto_fixable": False,
        },
    },
    {
        "label": "[BPP005] GetAllActorsOfClass in EventTick",
        "issue": {
            "rule_id": "BPP005",
            "rule_name": "GetAllActorsOfClass in EventTick",
            "rule_explanation": (
                "GetAllActorsOfClass called inside EventTick iterates "
                "every actor in the world each frame, causing massive "
                "CPU overhead in scenes with many actors. Cache the "
                "result in BeginPlay or use a timer-based refresh."
            ),
            "file_path": "/Game/Blueprints/BP_MiniMap",
            "severity": "error",
            "category": "performance",
            "asset_path": "/Game/Blueprints/BP_MiniMap",
            "graph": "EventTick",
            "message": "GetAllActorsOfClass node found inside EventTick",
            "is_auto_fixable": False,
        },
    },
    # ── Blueprint Best Practices (BPB) ─────────────────────────────────────
    {
        "label": "[BPB004] Missing BeginPlay Super call",
        "issue": {
            "rule_id": "BPB004",
            "rule_name": "Missing BeginPlay Super call",
            "rule_explanation": (
                "Blueprint overrides BeginPlay but does not call the "
                "parent implementation (Super::BeginPlay). Missing the "
                "Super call can break initialization chains in the "
                "class hierarchy."
            ),
            "file_path": "/Game/Blueprints/BP_PlayerCharacter",
            "severity": "warning",
            "category": "best_practices",
            "asset_path": "/Game/Blueprints/BP_PlayerCharacter",
            "graph": "BeginPlay",
            "message": "BeginPlay overrides parent but does not call Super",
            "is_auto_fixable": False,
        },
    },
    {
        "label": "[BPB006] Public function missing tooltip",
        "issue": {
            "rule_id": "BPB006",
            "rule_name": "Blueprint function missing tooltip",
            "rule_explanation": (
                "Public Blueprint functions are part of the class API "
                "and should have a tooltip so other developers "
                "understand their purpose. Add a description in the "
                "function's Details panel."
            ),
            "file_path": "/Game/Blueprints/BP_InventoryManager",
            "severity": "info",
            "category": "best_practices",
            "asset_path": "/Game/Blueprints/BP_InventoryManager",
            "graph": "AddItem",
            "message": "Public function 'AddItem' has no tooltip",
            "is_auto_fixable": False,
        },
    },
    # ── Blueprint Security (BPS) ───────────────────────────────────────────
    {
        "label": "[BPS001] Missing authority check",
        "issue": {
            "rule_id": "BPS001",
            "rule_name": "Missing authority check before action",
            "rule_explanation": (
                "Blueprint modifies a replicated variable without a "
                "HasAuthority or SwitchHasAuthority guard. In "
                "multiplayer, only the server should modify replicated "
                "state. Clients writing directly can cause desync, "
                "cheating, or server rejection."
            ),
            "file_path": "/Game/Blueprints/BP_GameState",
            "severity": "error",
            "category": "security",
            "asset_path": "/Game/Blueprints/BP_GameState",
            "graph": "EventGraph",
            "message": "Replicated variable written without HasAuthority guard",
            "is_auto_fixable": False,
        },
    },
    # ── UE5 Naming (NM) ────────────────────────────────────────────────────
    {
        "label": "[NM001] Asset missing type prefix (auto-fix)",
        "issue": {
            "rule_id": "NM001",
            "rule_name": "Asset missing type prefix",
            "rule_explanation": (
                "UE5 conventions require every asset to start with a "
                "short prefix identifying its class: SM_ for Static "
                "Meshes, T_ for Textures, M_ for Materials, BP_ for "
                "Blueprints. Without a prefix, assets are hard to find "
                "in the Content Browser and risk name collisions."
            ),
            "severity": "warning",
            "category": "naming",
            "asset_path": "/Game/Environment/RockFormation",
            "message": (
                "StaticMesh 'RockFormation' missing SM_ prefix"
                " — rename to 'SM_RockFormation'"
            ),
            "is_auto_fixable": True,
        },
    },
    {
        "label": "[NM002] Asset name contains spaces",
        "issue": {
            "rule_id": "NM002",
            "rule_name": "Asset name contains spaces",
            "rule_explanation": (
                "Spaces in asset names break code references and cause "
                "issues in source control and build pipelines. Replace "
                "spaces with underscores."
            ),
            "severity": "warning",
            "category": "naming",
            "asset_path": "/Game/Characters/Hero Sword",
            "message": "Asset 'Hero Sword' contains spaces — rename to 'Hero_Sword'",
            "is_auto_fixable": False,
        },
    },
    {
        "label": "[NM007] Asset name not PascalCase",
        "issue": {
            "rule_id": "NM007",
            "rule_name": "Asset name not PascalCase",
            "rule_explanation": (
                "Asset names after the prefix must be PascalCase. "
                "Valid: SM_HeroSword, T_RockWall_D, BP_PlayerCharacter. "
                "Invalid: SM_hero_sword, T_rock_wall, BP_playerCharacter. "
                "Consistent casing makes assets easier to search and "
                "reference from code."
            ),
            "severity": "warning",
            "category": "naming",
            "asset_path": "/Game/Environment/SM_rock_cliff",
            "message": "Asset 'SM_rock_cliff' not PascalCase — rename to 'SM_RockCliff'",  # noqa: E501
            "is_auto_fixable": False,
        },
    },
    {
        "label": "[NM009] Asset in wrong folder",
        "issue": {
            "rule_id": "NM009",
            "rule_name": "Asset in wrong folder",
            "rule_explanation": (
                "Asset type does not match its folder. A StaticMesh in "
                "/Textures/ or a Blueprint in /Materials/ confuses team "
                "members browsing the Content Browser and breaks "
                "tooling that resolves assets by folder convention. "
                "Move the asset to its expected folder."
            ),
            "severity": "warning",
            "category": "naming",
            "asset_path": "/Game/Textures/SM_BarrelLid",
            "message": (
                "StaticMesh 'SM_BarrelLid' is in /Textures/"
                " — expected /Meshes/ or /StaticMeshes/"
            ),
            "is_auto_fixable": False,
        },
    },
]

# ── Runner ──────────────────────────────────────────────────────────────────


def run() -> None:
    print("Loading model...")
    t_load_start = time.perf_counter()
    load_model()
    t_load_end = time.perf_counter()
    print(f"Model ready. (load: {t_load_end - t_load_start:.1f}s)\n")

    passed = 0
    failed = 0
    failed_labels = []
    times: list[float] = []

    for i, case in enumerate(CASES, 1):
        label = case["label"]
        issue: Dict[str, Any] = case["issue"]
        auto = issue["is_auto_fixable"]

        print(f"{'=' * 70}")
        print(f"[{i:02d}/20] {label}")
        print(f"  auto_fixable={auto}")
        print(f"{'-' * 70}")

        try:
            t0 = time.perf_counter()
            explanation = explain_issue(issue)
            elapsed = time.perf_counter() - t0
            times.append(elapsed)
            if not explanation:
                print(f"  [FAIL] Empty explanation ({elapsed:.1f}s)")
                failed += 1
                failed_labels.append(label)
                continue

            print(explanation)
            print(f"  time: {elapsed:.1f}s")

            closing = (
                "ShintTools' Auto-Fix can apply it for you."
                if auto
                else "You must fix this manually."
            )
            closing_ok = closing in explanation

            print()
            if closing_ok:
                print("  [OK] closing line correct")
                passed += 1
            else:
                print(f"  [WARN] closing line wrong — expected: '{closing}'")
                failed += 1
                failed_labels.append(label)

        except Exception as e:
            elapsed = time.perf_counter() - t0
            times.append(elapsed)
            print(f"  [ERROR] {type(e).__name__}: {e} ({elapsed:.1f}s)")
            failed += 1
            failed_labels.append(label)

        print()

    print("=" * 70)
    print(f"RESULTS: {passed}/20 passed")
    if failed_labels:
        print(f"\nFailed ({failed}):")
        for lbl in failed_labels:
            print(f"  - {lbl}")
    if times:
        total = sum(times)
        avg = total / len(times)
        first3 = sum(times[:3]) / 3
        last3 = sum(times[-3:]) / 3
        print(f"\nTIMING ({len(times)} inferences):")
        print(f"  Total inference:  {total:.1f}s")
        print(f"  Average per case: {avg:.1f}s")
        print(f"  First 3 avg:      {first3:.1f}s")
        print(f"  Last  3 avg:      {last3:.1f}s")
        print("  Per-case: " + ", ".join(f"{t:.1f}" for t in times))


if __name__ == "__main__":
    run()
