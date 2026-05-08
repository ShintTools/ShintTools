# core/scripts/smoke_llm_explainer.py
#
# Standalone smoke test for the customer-facing explainer.
#
# What it does:
#   1. Loads the local GGUF model (DeepSeek Coder 1.3B Q4_K_M).
#   2. Builds a fake enriched issue (rule_name + rule_explanation +
#      snippet) for ONE of the three domains (cpp / blueprint / naming).
#   3. Calls explain_issue() — direct generate() with a minimal prompt,
#      no orchestrator, no tools, no JSON.
#   4. Prints exactly what the model wrote.
#
# Run from the repo root:
#   python core/scripts/smoke_llm_explainer.py            # cpp (default)
#   python core/scripts/smoke_llm_explainer.py blueprint
#   python core/scripts/smoke_llm_explainer.py naming
#   SHOW_PROMPT=1 python core/scripts/smoke_llm_explainer.py cpp
#
# Cost: ~10-30 s to load the model (first run only), then 5-30 s per
# explanation depending on length and CPU.

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Make `agent`, `code_validator`, `naming` importable as top-level
# packages, matching how the FastAPI app loads them.
_CORE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_CORE / "modules"))


# ── Sample fixtures (one per domain) ───────────────────────────────────────
#
# Each fixture is a single enriched issue dict — the same shape the
# orchestrators emit after enrich_issue() runs. We hand-build them so
# we don't need a real source file / Blueprint export / asset registry
# on disk.


_CPP_ISSUE = {
    "rule_id": "CS001",
    "rule_name": "GetWorld without null-check",
    "rule_explanation": (
        "Detects GetWorld()-> calls without a null-check. GetWorld() can "
        "return nullptr in editor utilities, commandlets, or during "
        "shutdown. Always guard with 'if (UWorld* W = GetWorld())' "
        "before dereferencing."
    ),
    "severity": "error",
    "category": "Security",
    "file_path": "Source/MyActor.cpp",
    "line": 12,
    "message": ("GetWorld() may return nullptr; dereferencing it crashes the engine."),
    "fix_suggestion": (
        "Capture GetWorld() into a local and bail early when it is null."
    ),
    "is_auto_fixable": True,
    # cpp_orchestrator.run_all_cpp_rules() injects this 5-line window
    # automatically; we hand-build it here so the smoke test mirrors
    # production input exactly.
    "context_before": (
        "void AMyActor::BeginPlay()\n"
        "{\n"
        "    Super::BeginPlay();\n"
        "    UWorld* World = GetWorld();\n"
        "    AActor* Spawned = World->SpawnActor<AActor>(SpawnClass);"
    ),
}


_BP_ISSUE = {
    "rule_id": "BPS003",
    "rule_name": "ExecuteConsoleCommand in shipping code",
    "rule_explanation": (
        "Flag Blueprints that contain ExecuteConsoleCommand nodes. "
        "Console commands can change game state, enable cheats, or "
        "expose debug functionality. In shipping builds this is a "
        "security risk and potential exploit vector. Remove or gate "
        "behind development-only checks."
    ),
    "severity": "error",
    "category": "Security",
    "asset_path": "/Game/Blueprints/BP_DebugMenu",
    "graph": "EventGraph",
    "file_path": "/Game/Blueprints/BP_DebugMenu",
    "line": 0,
    "message": (
        "ExecuteConsoleCommand found in 'BP_DebugMenu' graph 'EventGraph' "
        "(2 instance(s)) — console commands can change game state and "
        "enable cheats."
    ),
    "fix_suggestion": (
        "Remove ExecuteConsoleCommand or wrap it with a "
        "UE_BUILD_SHIPPING / WITH_EDITOR preprocessor check."
    ),
    "is_auto_fixable": False,
}


_NM_ISSUE = {
    "rule_id": "NM001",
    "rule_name": "Asset missing type prefix",
    "rule_explanation": ("Flag assets that lack a valid UE5 type prefix."),
    "severity": "warning",
    "category": "Textures",
    "asset_path": "/Game/Textures/HeroDiffuse",
    "file_path": "/Game/Textures/HeroDiffuse",
    "line": 0,
    "message": ("Texture2D 'HeroDiffuse' is missing the required 'T_' prefix."),
    "fix_suggestion": "Rename '/Game/Textures/HeroDiffuse' to 'T_HeroDiffuse'.",
    "is_auto_fixable": True,
}


_FIXTURES = {
    "cpp": _CPP_ISSUE,
    "blueprint": _BP_ISSUE,
    "naming": _NM_ISSUE,
}


# ── Runner ─────────────────────────────────────────────────────────────────


def main() -> int:
    domain_name = sys.argv[1] if len(sys.argv) > 1 else "cpp"
    if domain_name not in _FIXTURES:
        print(f"Unknown domain '{domain_name}'. Use one of: {sorted(_FIXTURES)}")
        return 2

    issue_dict = dict(_FIXTURES[domain_name])

    # Imports kept inside main() so import-time failures (missing GGUF
    # etc.) print a clean error instead of crashing the script header.
    from agent.explainer import build_explainer_prompt, explain_issue
    from agent.llm_backend import is_loaded, load_model
    from code_validator.rules._rule_metadata import enrich_issue

    # Re-run enrichment from the live rule metadata so the smoke test
    # uses whatever rule_name and rule_explanation the orchestrators
    # would inject in production. This avoids the fixture drifting
    # silently when docstrings are updated.
    enrich_issue(issue_dict)

    print(f"=== smoke_llm_explainer.py — domain: {domain_name} ===\n")

    if os.environ.get("SHOW_PROMPT") == "1":
        rendered_prompt = build_explainer_prompt(issue_dict)
        print(f"--- FULL PROMPT (chars={len(rendered_prompt)}) ---")
        print(rendered_prompt)
        print("--- END PROMPT ---\n")

    # 1. Load the GGUF model (idempotent).
    if not is_loaded():
        print("[1/2] Loading GGUF model into RAM (first run takes 10-30 s)...")
        t_load_start = time.time()
        load_model()
        print(f"      Model loaded in {time.time() - t_load_start:.1f} s.\n")
    else:
        print("[1/2] Model already loaded.\n")

    # 2. Generate the explanation directly.
    print("[2/2] Generating explanation...\n")
    t_gen_start = time.time()
    explanation_text = explain_issue(issue_dict)
    elapsed_seconds = time.time() - t_gen_start

    print(
        f"      Generated in {elapsed_seconds:.1f} s · "
        f"len={len(explanation_text)} chars\n"
    )

    print("=" * 70)
    print("CUSTOMER-FACING EXPLANATION:")
    print("=" * 70)
    print(explanation_text or "(empty)")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
