import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "modules"))

from agent.explainer import explain_issue  # noqa: E402
from agent.llm_backend import is_loaded, load_model  # noqa: E402

issue = {
    "rule_id": "CP001",
    "rule_name": "FindObject in Tick",
    "rule_explanation": (
        "Detects calls to FindObject or FindObjectOfType inside Tick(). "
        "These functions traverse the entire GC root and all live UObjects "
        "every frame, making their cost linear with world size. Cache the "
        "result in BeginPlay or use a dedicated member variable instead."
    ),
    "severity": "warning",
    "category": "Performance",
    "file_path": "Source/AI/AEnemyController.cpp",
    "line": 47,
    "message": "FindObjectOfType called inside Tick() — O(n) over all live UObjects every frame.",  # noqa: E501
    "fix_suggestion": "Cache the result in BeginPlay() into a member variable.",
    "is_auto_fixable": False,
    "context_before": (
        "void AEnemyController::Tick(float DeltaTime)\n"
        "{\n"
        "    Super::Tick(DeltaTime);\n"
        "    UGameInstance* GI = FindObjectOfType<UGameInstance>();\n"
        "    if (GI) GI->HandleEnemyTick(this);"
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
