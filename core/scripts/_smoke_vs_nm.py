# core/scripts/_smoke_vs_nm.py
#
# Smoke test: Qwen on Unity Visual Scripting (VS*) and Naming (NM/NMU) rules.
# Run from core/:  python -m scripts._smoke_vs_nm

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.agent.explainer import explain_issue  # noqa: E402
from modules.agent.llm_backend import load_model  # noqa: E402

# ── Test cases ──────────────────────────────────────────────────────────────

CASES: List[Dict[str, Any]] = [
    # ── Unity Visual Scripting ──────────────────────────────────────────────
    {
        "label": "VSP001 — Log node in Update graph",
        "issue": {
            "rule_id": "VSP001",
            "rule_name": "Log node inside an Update graph",
            "rule_explanation": (
                "Log / PrintToConsole inside a graph that runs every frame. "
                "Every Update tick calls Debug.Log which allocates a string "
                "and flushes to the console, causing measurable GC pressure "
                "and editor slowdown. Remove or gate the node behind a "
                "conditional before shipping."
            ),
            "severity": "warning",
            "category": "Performance",
            "asset_path": "Assets/Game/PlayerController.asset",
            "message": "Log node found inside an Update graph — runs every frame",
            "is_auto_fixable": False,
        },
    },
    {
        "label": "VSM001 — Graph too large",
        "issue": {
            "rule_id": "VSM001",
            "rule_name": "Visual Scripting graph too large",
            "rule_explanation": (
                "More than 50 nodes in a single graph is hard to read and "
                "slow to load in the Unity editor. Large graphs become "
                "unmaintainable quickly. Break the graph into smaller "
                "sub-graphs or move repeated logic into custom C# nodes."
            ),
            "severity": "warning",
            "category": "Maintainability",
            "asset_path": "Assets/Game/EnemyAI.asset",
            "message": "Graph has 73 nodes — exceeds the 50-node limit",
            "is_auto_fixable": False,
        },
    },
    {
        "label": "VSB001 — Orphan custom event",
        "issue": {
            "rule_id": "VSB001",
            "rule_name": "Orphan custom event",
            "rule_explanation": (
                "A CustomEvent node is declared in the graph but no "
                "TriggerCustomEvent node calls it (or vice versa). "
                "Orphan events are dead code — they never fire and "
                "mislead future readers about the graph's intent. "
                "Either wire up the trigger or remove the event definition."
            ),
            "severity": "info",
            "category": "BestPractices",
            "asset_path": "Assets/Game/QuestManager.asset",
            "message": "CustomEvent 'OnQuestComplete' is declared but never triggered",
            "is_auto_fixable": False,
        },
    },
    {
        "label": "VSS003 — PlayerPrefs.Set in graph",
        "issue": {
            "rule_id": "VSS003",
            "rule_name": "PlayerPrefs.Set node in graph",
            "rule_explanation": (
                "PlayerPrefs stores data as plain text on disk with no "
                "encryption. Using it for sensitive information (auth tokens, "
                "API keys, user credentials) exposes that data to anyone "
                "with file-system access to the device. Use a secure storage "
                "solution or encrypt the value before writing."
            ),
            "severity": "warning",
            "category": "Security",
            "asset_path": "Assets/Game/AuthManager.asset",
            "message": "PlayerPrefs.SetString node found — do not store sensitive data",
            "is_auto_fixable": False,
        },
    },
    # ── Unity Naming (NMU) ─────────────────────────────────────────────────
    {
        "label": "NMU001 — Unity asset missing type prefix (auto-fixable)",
        "issue": {
            "rule_id": "NMU001",
            "rule_name": "Unity asset missing type prefix",
            "rule_explanation": (
                "Unity convention requires every asset name to start with "
                "a short prefix that identifies its type. A Texture2D "
                "should be T_, a Material M_, a Prefab P_, and so on. "
                "Without the prefix, assets are harder to find in the "
                "Project window and risk name collisions between types."
            ),
            "severity": "warning",
            "category": "Naming",
            "asset_path": "Assets/Art/Textures/HeroSword.png",
            "message": (
                "Texture2D 'HeroSword.png' missing T_ prefix"
                " — rename to 'T_HeroSword.png'"
            ),
            "is_auto_fixable": True,
        },
    },
    {
        "label": "NMU009 — Unity asset in wrong folder",
        "issue": {
            "rule_id": "NMU009",
            "rule_name": "Unity asset in wrong folder",
            "rule_explanation": (
                "Each asset type has a conventional folder in the Unity "
                "project (Textures, Materials, Prefabs, Audio, etc.). "
                "Storing assets outside their expected folder makes the "
                "project harder to navigate and breaks team conventions. "
                "Move the asset to the folder that matches its type."
            ),
            "severity": "warning",
            "category": "Naming",
            "asset_path": "Assets/Scripts/T_HeroSword.png",
            "message": "Texture2D 'T_HeroSword.png' under Scripts/ — needs Textures/",
            "is_auto_fixable": False,
        },
    },
    # ── UE5 Naming (NM) ────────────────────────────────────────────────────
    {
        "label": "NM001 — UE5 asset missing type prefix (auto-fixable)",
        "issue": {
            "rule_id": "NM001",
            "rule_name": "Asset missing type prefix",
            "rule_explanation": (
                "UE5 conventions require every asset to start with a short "
                "prefix identifying its class: SM_ for Static Meshes, "
                "T_ for Textures, M_ for Materials, BP_ for Blueprints, "
                "and so on. Without a prefix, assets are hard to find by "
                "type in the Content Browser and risk colliding with other "
                "assets when referenced by name in code."
            ),
            "severity": "warning",
            "category": "Naming",
            "asset_path": "/Game/Characters/HeroSword",
            "message": (
                "StaticMesh 'HeroSword' missing SM_ prefix"
                " — rename to 'SM_HeroSword'"
            ),
            "is_auto_fixable": True,
        },
    },
    {
        "label": "NM016 — UE5 asset has wrong prefix for its type",
        "issue": {
            "rule_id": "NM016",
            "rule_name": "Asset has wrong prefix for its type",
            "rule_explanation": (
                "The asset has a valid UE5 prefix but it belongs to a "
                "different asset type than the one actually used. For example "
                "a Material named T_Concrete uses the Texture prefix. This "
                "causes confusion in the Content Browser and can break "
                "automated pipeline tools that rely on prefix-to-type mapping."
            ),
            "severity": "warning",
            "category": "Naming",
            "asset_path": "/Game/Materials/T_Concrete",
            "message": (
                "Material 'T_Concrete' uses prefix T_ (Texture)"
                " — rename to 'M_Concrete'"
            ),
            "is_auto_fixable": True,
        },
    },
]

# ── Runner ──────────────────────────────────────────────────────────────────


def run() -> None:
    print("Loading model...")
    load_model()
    print("Model ready.\n")

    passed = 0
    failed = 0

    for case in CASES:
        label = case["label"]
        issue = case["issue"]
        print("=" * 70)
        print(f"RULE: {label}")
        print(f"asset: {issue.get('asset_path', issue.get('file_path', ''))}")
        print(f"auto_fixable: {issue['is_auto_fixable']}")
        print("-" * 70)

        try:
            explanation = explain_issue(issue)
            if not explanation:
                print("[FAIL] Empty explanation returned")
                failed += 1
                continue

            print(explanation)

            # Basic quality checks
            rule_name = issue["rule_name"]
            bold_name = f"**{rule_name}**"
            has_bold = bold_name in explanation
            expected_closing = (
                "ShintTools' Auto-Fix can apply it for you."
                if issue["is_auto_fixable"]
                else "You must fix this manually."
            )
            has_closing = expected_closing in explanation

            status = []
            if has_bold:
                status.append("[OK] rule_name bold")
            else:
                status.append(f"[WARN] rule_name not bolded — got: {explanation[-60:]}")
            if has_closing:
                status.append("[OK] closing line correct")
            else:
                status.append(
                    f"[WARN] closing line wrong — expected: '{expected_closing}'"
                )

            print()
            for s in status:
                print(f"  {s}")

            if all(s.startswith("[OK]") for s in status):
                passed += 1
            else:
                failed += 1

        except Exception as e:
            print(f"[ERROR] {type(e).__name__}: {e}")
            failed += 1

        print()

    print("=" * 70)
    print(f"RESULTS: {passed}/{passed + failed} passed")
    if failed:
        print(f"  {failed} case(s) need review")


if __name__ == "__main__":
    run()
