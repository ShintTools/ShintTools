"""Prueba del nuevo CppFixer con patrones."""

import sys

sys.path.insert(
    0,
    "C:/Users/Usuario/ShintTools/core/modules/code_validator/parsers",
)

from cpp_fixer import CppFixer  # noqa: E402

fixer = CppFixer()

# ========== TEST CP001 ==========
print("=== TEST CP001: FindObjectOfType en Tick ===")
code_cp001 = """
void AMyActor::Tick(float DeltaTime) {
    Super::Tick(DeltaTime);
    AActor* Target = FindObjectOfType<AActor>();
    Target->DoSomething();
}
"""
fixed, additions, changes = fixer.fix("CP001", code_cp001)
print(fixed)
print(f"Cambios: {changes}\n")

# ========== TEST CS001 ==========
print("=== TEST CS001: GetWorld sin null-check ===")
code_cs001 = """
void AMyActor::SpawnEnemy() {
    GetWorld()->SpawnActor<AEnemy>(EnemyClass);
}
"""
fixed, additions, changes = fixer.fix("CS001", code_cs001, line_number=3)
print(fixed)
print(f"Cambios: {changes}\n")

# ========== TEST CM001 ==========
print("=== TEST CM001: Borrar debug message ===")
code_cm001 = """
void AMyActor::BeginPlay() {
    Super::BeginPlay();
    GEngine->AddOnScreenDebugMessage(-1, 5.f, FColor::Red, TEXT("Debug"));
    Health = 100;
}
"""
fixed, additions, changes = fixer.fix("CM001", code_cm001, line_number=4)
print(fixed)
print(f"Cambios: {changes}\n")

# ========== TEST CP005 ==========
print("=== TEST CP005: Sleep -> Timer ===")
code_cp005 = """
void AMyActor::DoSomething() {
    FPlatformProcess::Sleep(2.0f);
    ContinueWork();
}
"""
fixed, additions, changes = fixer.fix("CP005", code_cp005, line_number=3)
print(fixed)
print(f"Additions: {additions}")
print(f"Cambios: {changes}\n")
