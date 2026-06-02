"""
Smoke test for Qwen2.5-Coder-1.5B-Instruct with adjusted system prompt.
Comparable to the DeepSeek smoke tests.
"""

import os
import sys
import time
from pathlib import Path

# Set the Qwen model BEFORE importing llm_backend
os.environ["SHINTTOOLS_MODEL_FILE"] = "Qwen2.5-Coder-1.5B-Instruct-Q4_K_M.gguf"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "modules"))

from agent.llm_backend import generate, is_loaded, load_model  # noqa: E402

# Adjusted system prompt for Qwen (more direct/concise than DeepSeek)
QWEN_SYSTEM = (
    "You are a senior code reviewer for Unreal Engine and Unity projects. "
    "Explain detected code issues in 2-4 sentences. Use second person. "
    "Mention the rule name in **bold**. Ground claims in the rule_explanation. "
    "Use `code` for tiny expressions. End with: if auto_fixable, say "
    "'ShintTools can auto-fix this'; else say 'fix manually'."
)

# Test issues (same as DeepSeek batch)
ISSUES = [
    {
        "name": "CS001",
        "rule_name": "GetWorld without null-check",
        "rule_explanation": (
            "Detects GetWorld()->calls without a null-check. GetWorld() can "
            "return nullptr in editor utilities, commandlets, or during "
            "shutdown. Always guard with 'if (UWorld* W = GetWorld())' "
            "before dereferencing."
        ),
        "context": "UWorld* World = GetWorld();\nAActor* Spawned = World->SpawnActor<AActor>(SpawnClass);",  # noqa: E501
        "is_auto_fixable": True,
    },
    {
        "name": "CP001",
        "rule_name": "FindObject in Tick",
        "rule_explanation": (
            "Detects calls to FindObject or FindObjectOfType inside Tick(). "
            "These functions traverse the entire GC root and all live UObjects "
            "every frame, making their cost linear with world size. Cache the "
            "result in BeginPlay or use a dedicated member variable instead."
        ),
        "context": "void AEnemyController::Tick(float DeltaTime) {\n    UGameInstance* GI = FindObjectOfType<UGameInstance>();",  # noqa: E501
        "is_auto_fixable": False,
    },
    {
        "name": "CS004",
        "rule_name": "Division without zero-check",
        "rule_explanation": (
            "Detects division operations where the divisor is not checked "
            "for zero before dividing. Integer division by zero crashes the "
            "engine immediately. Float division by zero produces NaN or Inf. "
            "Always guard with an explicit zero-check before dividing."
        ),
        "context": "float Reduction = ArmorFactor / TotalArmor;",
        "is_auto_fixable": True,
    },
]


def build_prompt_qwen(issue: dict) -> str:
    """Build a Qwen-formatted prompt (simpler than DeepSeek)."""
    return (
        f"{QWEN_SYSTEM}\n\n"
        f"Rule: {issue['rule_name']}\n"
        f"Explanation: {issue['rule_explanation']}\n"
        f"Code snippet:\n{issue['context']}\n"
        f"Auto-fixable: {issue['is_auto_fixable']}\n\n"
        f"Explain this issue:"
    )


def run_tests() -> None:
    if not is_loaded():
        print("[Loading Qwen model...]")
        t0 = time.time()
        load_model(n_ctx=1024)  # Reduced context for 1.5B
        print(f"Loaded in {time.time()-t0:.1f}s\n")
        print("=" * 70)

    print("\nQWEN2.5-CODER-1.5B SMOKE TESTS (3 issues)\n")
    print("=" * 70)

    for issue in ISSUES:
        rid = issue["name"]
        rname = issue["rule_name"]
        fixable = issue["is_auto_fixable"]

        prompt = build_prompt_qwen(issue)

        print(f"\nTEST {rid} — {rname} | auto_fixable={fixable}")
        print("-" * 70)

        t0 = time.time()
        text = generate(
            prompt,
            max_tokens=220,
            temperature=0.2,
            stop=["\n\n", "\n```"],
        )
        elapsed = time.time() - t0

        print(f"[{elapsed:.1f}s | {len(text)} chars]")
        print(text.strip())
        print("=" * 70)


if __name__ == "__main__":
    run_tests()
