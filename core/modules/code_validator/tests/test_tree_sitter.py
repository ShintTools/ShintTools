"""Tests for Tree-sitter fix patterns — all 53 auto-fix rules."""

import sys

sys.path.insert(0, "C:/Users/Usuario/ShintTools/core")
sys.path.insert(
    0,
    "C:/Users/Usuario/ShintTools/core" "/modules/code_validator/unreal/parsers/fixers",
)

from cpp_fixer import CppFixer  # noqa: E402

fixer = CppFixer()
passed = 0
failed = 0


def _run_case(
    name,
    rule_id,
    code,
    line_number,
    expected_in_output,
    expected_not_in_output=None,
):
    """Run a single test and print result."""
    global passed, failed
    fixed, additions, changes = fixer.fix(rule_id, code, line_number=line_number)
    ok = True

    for expected in (
        expected_in_output
        if isinstance(expected_in_output, list)
        else [expected_in_output]
    ):
        if expected not in fixed:
            print(f"FAIL {name}: " f"Expected '{expected}' in output")
            print(f"  Got: {fixed[:300]}")
            ok = False

    if expected_not_in_output:
        for not_expected in (
            expected_not_in_output
            if isinstance(expected_not_in_output, list)
            else [expected_not_in_output]
        ):
            if not_expected in fixed:
                print(f"FAIL {name}: " f"Did NOT expect '{not_expected}'")
                ok = False

    if ok:
        print(f"  PASS {name}")
        passed += 1
    else:
        failed += 1


# ================================================================
print("\n=== CORRECTED PATTERNS (CP007, CP010) ===")
# ================================================================

_run_case(
    "CP007: bCanEverTick = true -> false",
    "CP007",
    "AMyActor::AMyActor() {\n" "    PrimaryActorTick.bCanEverTick = true;\n}",
    2,
    "= false",
    "= true",
)

_run_case(
    "CP010: FORCEINLINE -> inline",
    "CP010",
    "FORCEINLINE float GetSpeed() const {\n" "    return Speed;\n}",
    1,
    "inline float GetSpeed",
    "FORCEINLINE",
)

# ================================================================
print("\n=== NULL CHECK WITH IsValid() ===")
# ================================================================

_run_case(
    "CS001: GetWorld() -> if (UWorld* World = GetWorld())",
    "CS001",
    "void AMyActor::Setup() {\n" "    GetWorld()->SpawnActor();\n}",
    2,
    "if (UWorld* World = GetWorld())",
)

_run_case(
    "CS003: Cast<> -> extract + IsValid(CastedAEnemy)",
    "CS003",
    "void AMyActor::OnHit() {\n" "    Cast<AEnemy>(Other)->TakeDamage(10);\n}",
    2,
    "IsValid(CastedAEnemy)",
)

_run_case(
    "CS007: OtherActor -> IsValid(OtherActor)",
    "CS007",
    "void AMyActor::OnOverlap(AActor* OtherActor)"
    " {\n    OtherActor->TakeDamage(10.0f);\n}",
    2,
    "IsValid(OtherActor)",
)

# ================================================================
print("\n=== EASY PATTERNS (Priority 2) ===")
# ================================================================

_run_case(
    "CB008: add_suffix (1.0 -> 1.0f)",
    "CB008",
    "void AMyActor::Setup() {\n" "    float Value = 1.0;\n}",
    2,
    "1.0f",
)

_run_case(
    "CB019: add_virtual",
    "CB019",
    "class AMyActor : public AActor {\n" "    ~AMyActor();\n};",
    2,
    "virtual ~AMyActor",
)

_run_case(
    "CB023: add_override",
    "CB023",
    "class AMyActor : public AActor {\n" "    void BeginPlay();\n};",
    2,
    "override;",
)

_run_case(
    "CB030: wrap_text_macro",
    "CB030",
    "void AMyActor::Setup() {\n" '    FString Name = "Hello World";\n}',
    2,
    'TEXT("Hello World")',
)

_run_case(
    "CM008: replace_destructor_default",
    "CM008",
    "class AMyActor : public AActor {\n" "    ~AMyActor() {}\n};",
    2,
    "= default;",
    "{}",
)

# ================================================================
print("\n=== MEDIUM PATTERNS (Priority 3) ===")
# ================================================================

_run_case(
    "CB012: wrap_static_cast",
    "CB012",
    "void AMyActor::Calculate() {\n" "    int Result = (float)Value + 1;\n}",
    2,
    "static_cast<float>(Value)",
    "(float)Value",
)

_run_case(
    "CS004: add_zero_check",
    "CS004",
    "void AMyActor::Calculate() {\n" "    float Result = Total / Count;\n}",
    2,
    ["Count != 0", "Total / Count"],
)

_run_case(
    "CS005: add_bounds_check",
    "CS005",
    "void AMyActor::Process() {\n" "    auto Item = MyArray[Index];\n}",
    2,
    ["IsValidIndex(Index)", "MyArray[Index]"],
)

# ========================================================
print("\n=== NEW REAL AUTO-FIX PATTERNS " "(formerly mark_for_review) ===")
# ========================================================

_run_case(
    "CB001: comment_line (infinite loop)",
    "CB001",
    "void AMyActor::Run() {\n" "    while (true) { DoWork(); }\n}",
    2,
    "// [SHINTTOOLS]",
)

_run_case(
    "CB002: comment_line (sync load)",
    "CB002",
    "void AMyActor::Load() {\n" "    LoadObject<UTexture2D>(nullptr, Path);\n}",
    2,
    "// [SHINTTOOLS]",
)

_run_case(
    "CB003: replace_raw_new -> NewObject",
    "CB003",
    "void AMyActor::Setup() {\n" "    UMyObject* Obj = new UMyObject();\n}",
    2,
    "NewObject<UMyObject>(this)",
    "new UMyObject",
)

_run_case(
    "CB004: comment_line (raw delete)",
    "CB004",
    "void AMyActor::Cleanup() {\n" "    delete MyObject;\n}",
    2,
    "// [SHINTTOOLS]",
)

_run_case(
    "CB007: comment_line (system header)",
    "CB007",
    '#include <iostream>\n#include "MyActor.h"',
    1,
    "// [SHINTTOOLS]",
)

_run_case(
    "CB009: remove_nullptr_init",
    "CB009",
    "    UPROPERTY() UMyComp* Comp = nullptr;",
    1,
    "UMyComp* Comp;",
    "nullptr",
)

_run_case(
    "CB016: comment_line (string concat in loop)",
    "CB016",
    "void AMyActor::Build() {\n" "    Result += FString::Printf(" 'TEXT("%d"), i);\n}',
    2,
    "// [SHINTTOOLS]",
)

_run_case(
    "CB021: replace_lambda_capture [&] -> [this]",
    "CB021",
    "void AMyActor::Setup() {\n" "    auto Lambda = [&]() { DoWork(); };\n}",
    2,
    "[this]",
    "[&]",
)

_run_case(
    "CB024: insert_line (Super::BeginPlay)",
    "CB024",
    "void AMyActor::BeginPlay() {\n" "    InitStuff();\n}",
    1,
    "Super::BeginPlay();",
)

_run_case(
    "CB025: add_ufunction_category",
    "CB025",
    "    UFUNCTION(BlueprintCallable)\n" "    void DoStuff();",
    1,
    'Category="Default"',
)

_run_case(
    "CB031: add_const_qualifier",
    "CB031",
    "    float GetHealth();",
    1,
    "const;",
)

# Regression: CB031 must NOT add 'const' to a static member function.
# C++ forbids 'const' on static members (no 'this' pointer).
_run_case(
    "CB031: skip static function (same-line static)",
    "CB031",
    "    static int32 GetDefault();",
    1,
    "static int32 GetDefault();",
    " const;",
)

# Regression: split-style 'static' on the line above the signature.
_run_case(
    "CB031: skip static function (split static)",
    "CB031",
    "    static\n    int32 GetDefault();",
    2,
    "int32 GetDefault();",
    " const;",
)

_run_case(
    "CB032: remove_const_ref",
    "CB032",
    "    const FVector& Location;",
    1,
    "FVector Location;",
    "const",
)

_run_case(
    "CS012: comment_line (hardcoded secret)",
    "CS012",
    "void AMyActor::Connect() {\n" '    FString ApiKey = "sk-12345abcde";\n}',
    2,
    "// [SHINTTOOLS]",
)

# ========================================================
print("\n=== MARK FOR REVIEW (true no-fix rules) ===")
# ========================================================

_run_case(
    "CB010: mark_for_review (magic number)",
    "CB010",
    "void AMyActor::Setup() {\n" "    Health = 100;\n}",
    2,
    "[SHINTTOOLS REVIEW]",
)

_run_case(
    "CB015: mark_for_review (auto without type)",
    "CB015",
    "void AMyActor::Setup() {\n" "    auto Result = GetValue();\n}",
    2,
    "[SHINTTOOLS REVIEW]",
)

_run_case(
    "CM004: mark_for_review (file too long)",
    "CM004",
    "// This file is 600 lines long\n" "void A() {}\n",
    1,
    "[SHINTTOOLS REVIEW]",
)

# ========================================================
print("\n=== REGRESSION TESTS (existing patterns) ===")
# ========================================================

_run_case(
    "CB005: std::vector -> TArray",
    "CB005",
    "void AMyActor::Setup() {\n" "    std::vector<int> Numbers;\n}",
    2,
    "TArray",
    "std::vector",
)

_run_case(
    "CS011: http -> https",
    "CS011",
    "void AMyActor::Connect() {\n" '    FString Url = "http://api.example.com";\n}',
    2,
    "https://",
    "http://api",
)

_run_case(
    "CM003: delete TODO comment",
    "CM003",
    "void AMyActor::Update() {\n"
    "    // TODO: Fix this later\n"
    "    DoSomething();\n}",
    2,
    expected_in_output="DoSomething",
    expected_not_in_output="TODO",
)

# ========================================================
# Summary
# ========================================================

print(f"\n{'='*50}")
print(f"Results: {passed} passed, {failed} failed, " f"{passed + failed} total")
print(f"{'='*50}")

if failed > 0:
    sys.exit(1)
