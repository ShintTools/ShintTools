"""Prueba del patrón extract_function."""

# ruff: noqa: E402
import sys

sys.path.insert(
    0,
    "C:/Users/Usuario/ShintTools/core/modules/code_validator/parsers",
)

from cpp_fixer import CppFixer  # noqa: E402

fixer = CppFixer()

# ========== TEST CP003 ==========
print("=== TEST CP003: Extract Tick logic ===")
code = """
void AMyActor::Tick(float DeltaTime) {
    Super::Tick(DeltaTime);
    FVector Location = GetActorLocation();
    Location.Z += Speed * DeltaTime;
    SetActorLocation(Location);
    CheckCollisions();
    UpdateHealth();
}
"""
fixed, additions, changes = fixer.fix("CP003", code)
print("CODIGO CORREGIDO:")
print(fixed)
print(f"\nCAMBIOS: {changes}")
print(f"\nAGREGAR AL PROYECTO:{additions}")
