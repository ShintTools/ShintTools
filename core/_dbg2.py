import sys

sys.path.insert(0, "modules")
from code_validator.unreal.parsers.cpp_parser import CppParser

p = CppParser()
code = (
    "void AMyActor::Tick(float DeltaTime)\n"
    "{\n"
    "    Super::Tick(DeltaTime);\n"
    "    FVector Pos = GetActorLocation();\n"
    "    FVector NewPos = Pos + FVector(0, 0, 1) * DeltaTime;\n"
    "    SetActorLocation(NewPos);\n"
    "}\n"
)
try:
    root = p.parse(code)
    print("parse OK:", root)
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")

# Try the actual _EXTRACT_CODE from test_cm006_cp003.py
code2 = (
    "void AMyActor::Tick(float DeltaTime)\n"
    "{\n"
    "    Super::Tick(DeltaTime);\n"
    "    FVector Pos = GetActorLocation();\n"
    "    FVector NewPos = Pos + FVector(0, 0, 1) * DeltaTime;\n"
    "    SetActorLocation(NewPos);\n"
    "    UpdateOverlaps();\n"
    "    CheckCollision();\n"
    "}\n"
)
try:
    root = p.parse(code2)
    print("parse2 OK:", root)
except Exception as e:
    print(f"FAIL2: {type(e).__name__}: {e}")

# Also test the fixer
try:
    from cpp_fixer import CppFixer

    fixer = CppFixer()
    fixed, additions, changes = fixer.fix("CP003", code2, line_number=1)
    print("fixer OK:", fixed[:100])
except Exception as e:
    print(f"fixer FAIL: {type(e).__name__}: {e}")
