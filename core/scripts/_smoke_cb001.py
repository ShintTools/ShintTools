import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "modules"))

from agent.explainer import explain_issue  # noqa: E402
from agent.llm_backend import is_loaded, load_model  # noqa: E402

issue = {
    "rule_id": "CB001",
    "rule_name": "Infinite loop without exit",
    "rule_explanation": (
        "Detects while(true) or for(;;) loops that contain no break, return, "
        "or goto statement. A loop with no exit condition will hang the game "
        "thread permanently. Every infinite loop must have at least one "
        "reachable exit path."
    ),
    "severity": "error",
    "category": "Best Practices",
    "file_path": "Source/Systems/AQuestManager.cpp",
    "line": 88,
    "message": "while(true) loop has no break, return or goto — will hang the game thread.",  # noqa: E501
    "fix_suggestion": "Add a break or return condition inside the loop body.",
    "is_auto_fixable": False,
    "context_before": (
        "void AQuestManager::ProcessEvents()\n"
        "{\n"
        "    while (true)\n"
        "    {\n"
        "        UQuestEvent* Ev = EventQueue.Dequeue();"
    ),
}

if not is_loaded():
    t0 = time.time()
    load_model()

print("Generating CB001...\n")
t0 = time.time()
text = explain_issue(issue)
elapsed = time.time() - t0
print(f"Generated in {elapsed:.1f}s | {len(text)} chars\n")
print("=" * 70)
print(text)
print("=" * 70)
