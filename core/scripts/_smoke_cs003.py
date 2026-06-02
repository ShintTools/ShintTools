import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "modules"))

from agent.explainer import explain_issue  # noqa: E402
from agent.llm_backend import is_loaded, load_model  # noqa: E402

issue = {
    "rule_id": "CS003",
    "rule_name": "Unchecked Cast result",
    "rule_explanation": (
        "Detects Cast<T>() results used directly without a null-check. "
        "Cast<T>() returns nullptr when the object is not of type T. "
        "Dereferencing the result without checking it first causes a crash "
        "at runtime. Always guard with 'if (T* Ptr = Cast<T>(Obj))' "
        "before using the pointer."
    ),
    "severity": "error",
    "category": "Security",
    "file_path": "Source/Weapons/AWeaponBase.cpp",
    "line": 33,
    "message": "Cast<AProjectile> result used without null-check — crashes if cast fails.",  # noqa: E501
    "fix_suggestion": "Wrap the cast in 'if (AProjectile* P = Cast<AProjectile>(Actor))'.",  # noqa: E501
    "is_auto_fixable": True,
    "context_before": (
        "void AWeaponBase::OnHit(AActor* Actor)\n"
        "{\n"
        "    AProjectile* Proj = Cast<AProjectile>(Actor);\n"
        "    Proj->ApplyDamage(Damage);\n"
        "    Proj->Destroy();"
    ),
}

if not is_loaded():
    print("[1/2] Loading model...")
    t0 = time.time()
    load_model()
    print(f"      Loaded in {time.time()-t0:.1f}s\n")

print("[2/2] Generating...\n")
t0 = time.time()
text = explain_issue(issue)
elapsed = time.time() - t0

print(f"Generated in {elapsed:.1f}s | {len(text)} chars\n")
print("=" * 70)
print(text)
print("=" * 70)
