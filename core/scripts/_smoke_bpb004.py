import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "modules"))

from agent.explainer import explain_issue  # noqa: E402
from agent.llm_backend import is_loaded, load_model  # noqa: E402

issue = {
    "rule_id": "BPB004",
    "rule_name": "Missing Super BeginPlay call in Blueprint",
    "rule_explanation": (
        "Detects Blueprint classes that override BeginPlay without calling "
        "the Parent BeginPlay node. Skipping the Super call breaks the "
        "initialisation chain: components, replication setup, and any parent "
        "class logic that relies on BeginPlay will not run. Always add a "
        "Parent: BeginPlay node at the start of the event."
    ),
    "severity": "warning",
    "category": "Best Practices",
    "asset_path": "/Game/Characters/BP_SoldierCharacter",
    "file_path": "/Game/Characters/BP_SoldierCharacter",
    "graph": "BeginPlay",
    "line": 0,
    "message": "BP_SoldierCharacter overrides BeginPlay without calling Super.",
    "fix_suggestion": "Add a Parent: BeginPlay node at the start of the BeginPlay graph.",  # noqa: E501
    "is_auto_fixable": False,
}

if not is_loaded():
    t0 = time.time()
    load_model()

print("Generating BPB004...\n")
t0 = time.time()
text = explain_issue(issue)
elapsed = time.time() - t0
print(f"Generated in {elapsed:.1f}s | {len(text)} chars\n")
print("=" * 70)
print(text)
print("=" * 70)
