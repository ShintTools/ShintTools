import sys

sys.path.insert(0, "modules")
import tree_sitter_cpp as tscpp
from tree_sitter import Language, Parser

# Try 0.22 style first, then 0.21 style
try:
    cpp_language = Language(tscpp.language())
    print("0.22 style Language OK")
except TypeError as e:
    print(f"0.22 style failed: {e}")
    cpp_language = Language(tscpp.language(), "cpp")
    print("0.21 style Language OK")

try:
    p = Parser(cpp_language)
    print("0.22 style Parser OK")
except TypeError as e:
    print(f"0.22 style Parser failed: {e}")
    p = Parser()
    p.set_language(cpp_language)
    print("0.21 style Parser OK")

# Simple test
for code_str, label in [
    ("int x = 5;", "simple"),
    ("void Tick() {}", "simple function"),
    (
        "void AMyActor::Tick(float DeltaTime)\n{\n    Super::Tick(DeltaTime);\n}\n",
        "Tick method",
    ),
    (
        "void AMyActor::Tick(float DeltaTime)\n{\n    Super::Tick(DeltaTime);\n    FVector Pos = GetActorLocation();\n}\n",
        "Tick with FVector",
    ),
]:
    try:
        tree = p.parse(code_str.encode())
        print(f"  {label}: OK has_error={tree.root_node.has_error}")
    except Exception as e:
        print(f"  {label}: FAIL {type(e).__name__}: {e}")
