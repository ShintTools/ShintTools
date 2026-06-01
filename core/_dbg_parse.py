import sys

sys.path.insert(0, "modules")

from code_validator.unreal.parsers.cpp_parser import CppParser

p = CppParser()

code = """\
void AMyActor::Tick(float DeltaTime)
{
    Super::Tick(DeltaTime);
    FVector Pos = GetActorLocation();
    FVector NewPos = Pos + FVector(0, 0, 1) * DeltaTime;
    SetActorLocation(NewPos);
    UpdateOverlaps();
    CheckCollision();
}
"""

try:
    root = p.parse(code)
    print("parse OK:", root)
except Exception as e:
    print(f"parse FAILED: {type(e).__name__}: {e}")

# Check if the raw tree-sitter parser has errors
raw = p.parser
print("raw parser type:", type(raw))
try:
    tree = raw.parse(code.encode())
    print("raw tree:", tree)
    print("root_node:", tree.root_node)
    print("has_error:", tree.root_node.has_error)
except Exception as e:
    print(f"raw parse FAILED: {type(e).__name__}: {e}")
