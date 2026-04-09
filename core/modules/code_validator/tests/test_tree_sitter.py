"""Prueba de nuevas reglas."""

import sys

sys.path.insert(0, "C:/Users/Usuario/ShintTools/core")
sys.path.insert(0, "C:/Users/Usuario/ShintTools/core/modules/code_validator/parsers")

from cpp_fixer import CppFixer  # noqa: E402

fixer = CppFixer()

# ========== TEST CB005: std::vector -> TArray ==========
print("=== TEST CB005: std::vector -> TArray ===")
code = """
void AMyActor::Setup() {
    std::vector<int> Numbers;
    Numbers.push_back(1);
}
"""
fixed, additions, changes = fixer.fix("CB005", code, line_number=3)
print(fixed)
print(f"Cambios: {changes}\n")

# ========== TEST CS007: OtherActor null check ==========
print("=== TEST CS007: OtherActor null check ===")
code = """
void AMyActor::OnOverlap(AActor* OtherActor) {
    OtherActor->TakeDamage(10.0f);
}
"""
fixed, additions, changes = fixer.fix("CS007", code, line_number=3)
print(fixed)
print(f"Cambios: {changes}\n")

# ========== TEST CM003: Delete TODO comment ==========
print("=== TEST CM003: Delete TODO comment ===")
code = """
void AMyActor::Update() {
    // TODO: Fix this later
    DoSomething();
}
"""
fixed, additions, changes = fixer.fix("CM003", code, line_number=3)
print(fixed)
print(f"Cambios: {changes}\n")
