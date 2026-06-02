"""Demo: End-to-end validation of Visual Scripting graphs via the backend.

This script builds a realistic VS asset with Instantiate in Update and
runs it through the full validation pipeline, showing what Daniel should
expect when he calls POST /validate/unity/visual.

To run: python -m core.scripts.demo_unity_vs_endpoint
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Add parent directories to path so relative imports work
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "core" / "modules"))

from code_validator.unity.parsers.unity_vs_parser import parse_unity_graph
from code_validator.unity.visual_scripting.unity_graph_orchestrator import (
    run_all_unity_graph_rules,
)


def _build_asset_yaml(
    elements: list[dict],
    connections: list[dict] | None = None,
) -> str:
    """Build a minimal VS .asset YAML with given graph structure."""
    graph_json = json.dumps(
        {
            "elements": elements,
            "connections": connections or [],
            "variables": {},
        }
    )
    escaped_json = graph_json.replace("'", "''")
    return (
        "%YAML 1.1\n"
        "%TAG !u! tag:unity3d.com,2011:\n"
        "--- !u!114 &11500000\n"
        "MonoBehaviour:\n"
        "  m_ObjectHideFlags: 0\n"
        "  m_Script: {fileID: 11500000, guid: 1b7db557dd37f, type: 3}\n"
        "  m_Name: Unity.VisualScripting.ScriptGraphAsset\n"
        "  m_EditorClassIdentifier:\n"
        "  _data:\n"
        f"    _json: '{escaped_json}'\n"
    )


# ── DEMO 1: Instantiate in Update (should trigger VSP004 error)
print("=" * 70)
print("DEMO 1: Instantiate inside Update")
print("=" * 70)

asset_yaml_1 = _build_asset_yaml(
    elements=[
        {
            "guid": "unit-1",
            "$type": "Unity.VisualScripting.OnUpdate",
            "position": [0, 0],
            "defaultValues": {},
        },
        {
            "guid": "unit-2",
            "$type": "Unity.VisualScripting.InvokeMember",
            "position": [100, 0],
            "defaultValues": {
                "member": {
                    "name": "Instantiate",
                    "targetType": "UnityEngine.Object",
                }
            },
        },
    ],
    connections=[
        {
            "sourceUnit": "unit-1",
            "sourceKey": "exit",
            "destinationUnit": "unit-2",
            "destinationKey": "enter",
        }
    ],
)

print("\nInput: OnUpdate -> Instantiate\n")
graph_1 = parse_unity_graph(asset_yaml_1, "Assets/Graphs/Demo1.asset")
if graph_1:
    print(f"[OK] Parsed successfully: {graph_1['unit_count']} units\n")
    issues_1 = run_all_unity_graph_rules([graph_1])
    if issues_1:
        print(f"Issues found: {len(issues_1)}\n")
        for issue in issues_1:
            print(f"  Rule: {issue['rule_id']}")
            print(f"  Severity: {issue['severity']}")
            print(f"  Message: {issue['message']}\n")
    else:
        print("No issues found (unexpected!)\n")
else:
    print("[FAIL] Failed to parse\n")


# ── DEMO 2: GetComponent in Update without null check (should trigger VSB005)
print("=" * 70)
print("DEMO 2: GetComponent without null check")
print("=" * 70)

asset_yaml_2 = _build_asset_yaml(
    elements=[
        {
            "guid": "unit-1",
            "$type": "Unity.VisualScripting.OnUpdate",
            "position": [0, 0],
            "defaultValues": {},
        },
        {
            "guid": "unit-2",
            "$type": "Unity.VisualScripting.InvokeMember",
            "position": [100, 0],
            "defaultValues": {
                "member": {
                    "name": "GetComponent",
                    "targetType": "UnityEngine.GameObject",
                }
            },
        },
        {
            "guid": "unit-3",
            "$type": "Unity.VisualScripting.InvokeMember",
            "position": [200, 0],
            "defaultValues": {
                "member": {
                    "name": "SetActive",
                    "targetType": "UnityEngine.GameObject",
                }
            },
        },
    ],
    connections=[
        {
            "sourceUnit": "unit-1",
            "sourceKey": "exit",
            "destinationUnit": "unit-2",
            "destinationKey": "enter",
        },
        {
            "sourceUnit": "unit-2",
            "sourceKey": "exit",
            "destinationUnit": "unit-3",
            "destinationKey": "enter",
        },
    ],
)

print("\nInput: OnUpdate -> GetComponent -> SetActive (no null check)\n")
graph_2 = parse_unity_graph(asset_yaml_2, "Assets/Graphs/Demo2.asset")
if graph_2:
    print(f"[OK] Parsed successfully: {graph_2['unit_count']} units\n")
    issues_2 = run_all_unity_graph_rules([graph_2])
    if issues_2:
        print(f"Issues found: {len(issues_2)}\n")
        for issue in issues_2:
            print(f"  Rule: {issue['rule_id']}")
            print(f"  Severity: {issue['severity']}")
            print(f"  Message: {issue['message']}\n")
    else:
        print("No issues found (unexpected!)\n")
else:
    print("[FAIL] Failed to parse\n")


# ── DEMO 3: Hardcoded secret in InvokeMember
print("=" * 70)
print("DEMO 3: Hardcoded API key (VSS001 Security)")
print("=" * 70)

asset_yaml_3 = _build_asset_yaml(
    elements=[
        {
            "guid": "unit-1",
            "$type": "Unity.VisualScripting.Start",
            "position": [0, 0],
            "defaultValues": {},
        },
        {
            "guid": "unit-2",
            "$type": "Unity.VisualScripting.InvokeMember",
            "position": [100, 0],
            "defaultValues": {
                "member": {
                    "name": "Log",
                    "targetType": "UnityEngine.Debug",
                },
                "apiKey": "sk_live_1234567890abcdefgh",
            },
        },
    ],
    connections=[
        {
            "sourceUnit": "unit-1",
            "sourceKey": "exit",
            "destinationUnit": "unit-2",
            "destinationKey": "enter",
        }
    ],
)

print("\nInput: Start -> InvokeMember with apiKey='sk_live_1234567890abcdefgh'\n")
graph_3 = parse_unity_graph(asset_yaml_3, "Assets/Graphs/Demo3.asset")
if graph_3:
    print(f"[OK] Parsed successfully: {graph_3['unit_count']} units\n")
    issues_3 = run_all_unity_graph_rules([graph_3])
    if issues_3:
        print(f"Issues found: {len(issues_3)}\n")
        for issue in issues_3:
            print(f"  Rule: {issue['rule_id']}")
            print(f"  Severity: {issue['severity']}")
            print(f"  Message: {issue['message']}\n")
    else:
        print("No issues found (unexpected!)\n")
else:
    print("[FAIL] Failed to parse\n")

print("=" * 70)
print("Demo complete. These examples show what Daniel should expect.\n")
