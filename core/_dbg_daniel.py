"""Quick debug: reproduce Daniel's exact request locally."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "modules"))

from code_validator.unity.parsers.unity_vs_parser import parse_unity_graph
from code_validator.unity.visual_scripting.unity_graph_orchestrator import (
    run_all_unity_graph_rules,
)

# Daniel's exact payload from input(1).txt
DANIEL_CONTENT = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!114 &11400000
MonoBehaviour:
  m_ObjectHideFlags: 0
  m_CorrespondingSourceObject: {fileID: 0}
  m_PrefabInstance: {fileID: 0}
  m_PrefabAsset: {fileID: 0}
  m_GameObject: {fileID: 0}
  m_Enabled: 1
  m_EditorHideFlags: 0
  m_Script: {fileID: 11500000, guid: 95e66c6366d904e98bc83428217d4fd7, type: 3}
  m_Name: Test
  m_EditorClassIdentifier:
  _data:
    _json: '{"graph":{"variables":{"Kind":"Flow","collection":{"$content":[],"$version":"A"},"$version":"A"},"controlInputDefinitions":[],"controlOutputDefinitions":[],"valueInputDefinitions":[],"valueOutputDefinitions":[],"title":null,"summary":null,"pan":{"x":322.2922,"y":105.3333},"zoom":1.0,"elements":[{"coroutine":false,"defaultValues":{},"position":{"x":-204.0,"y":-144.0},"guid":"c174b41c-e1c3-442e-b9f2-b7e27ffb7c70","$version":"A","$type":"Unity.VisualScripting.Start","$id":"9"},{"coroutine":false,"defaultValues":{},"position":{"x":-204.0,"y":60.0},"guid":"529e3287-7bc4-4229-8a38-3924955fbc2e","$version":"A","$type":"Unity.VisualScripting.Update","$id":"11"},{"chainable":false,"parameterNames":["original"],"member":{"name":"Instantiate","parameterTypes":["UnityEngine.Object"],"targetType":"UnityEngine.GameObject","targetTypeName":"UnityEngine.GameObject","$version":"A"},"defaultValues":{"%original":{"$content":0,"$type":"UnityEngine.Object"}},"position":{"x":-7.0,"y":60.0},"guid":"1908cf02-2b24-4385-b59c-c2451081fe63","$version":"A","$type":"Unity.VisualScripting.InvokeMember","$id":"13"},{"chainable":false,"parameterNames":["type"],"member":{"name":"GetComponent","parameterTypes":["System.Type"],"targetType":"UnityEngine.GameObject","targetTypeName":"UnityEngine.GameObject","$version":"A"},"defaultValues":{"target":null,"%type":{"$content":"UnityEngine.MeshRenderer","$type":"System.RuntimeType"}},"position":{"x":247.0,"y":59.0},"guid":"01c610ff-2c07-441b-8541-f11d5f5194cd","$version":"A","$type":"Unity.VisualScripting.InvokeMember","$id":"17"},{"chainable":false,"parameterNames":["value"],"member":{"name":"SetActive","parameterTypes":["System.Boolean"],"targetType":"UnityEngine.GameObject","targetTypeName":"UnityEngine.GameObject","$version":"A"},"defaultValues":{"target":{"$content":1,"$type":"UnityEngine.Object"},"%value":{"$content":false,"$type":"System.Boolean"}},"position":{"x":625.0,"y":59.0},"guid":"0ba282bd-a5ec-40a1-905e-10ee893858ee","$version":"A","$type":"Unity.VisualScripting.InvokeMember","$id":"21"},{"chainable":false,"parameterNames":["methodName","time"],"member":{"name":"Invoke","parameterTypes":["System.String","System.Single"],"targetType":"UnityEngine.MonoBehaviour","targetTypeName":"UnityEngine.MonoBehaviour","$version":"A"},"defaultValues":{"target":null,"%methodName":{"$content":"\\"apiKey\\": \\"sk_live_1234567890abcdefgh\\"","$type":"System.String"},"%time":{"$content":0.0,"$type":"System.Single"}},"position":{"x":-14.0,"y":-144.0},"guid":"93f1316a-8ed2-4cdc-bf6f-c11ce7baf5f4","$version":"A","$type":"Unity.VisualScripting.InvokeMember","$id":"25"},{"sourceUnit":{"$ref":"13"},"sourceKey":"exit","destinationUnit":{"$ref":"17"},"destinationKey":"enter","guid":"6f2cc39a-233d-429e-93bf-9b613a038a77","$type":"Unity.VisualScripting.ControlConnection"},{"sourceUnit":{"$ref":"11"},"sourceKey":"trigger","destinationUnit":{"$ref":"13"},"destinationKey":"enter","guid":"6fa824a6-3695-4276-b88b-c49e36f203ca","$type":"Unity.VisualScripting.ControlConnection"},{"sourceUnit":{"$ref":"9"},"sourceKey":"trigger","destinationUnit":{"$ref":"25"},"destinationKey":"enter","guid":"d6b3bca1-e869-4b79-9180-f5e19bfe1f24","$type":"Unity.VisualScripting.ControlConnection"},{"sourceUnit":{"$ref":"17"},"sourceKey":"exit","destinationUnit":{"$ref":"21"},"destinationKey":"enter","guid":"7f6f1940-2e9f-4ebd-8491-94894bf586e8","$type":"Unity.VisualScripting.ControlConnection"},{"sourceUnit":{"$ref":"17"},"sourceKey":"result","destinationUnit":{"$ref":"21"},"destinationKey":"target","guid":"0c8b29a1-6e33-4cc5-9d50-554f4e622d51","$type":"Unity.VisualScripting.ValueConnection"},{"sourceUnit":{"$ref":"13"},"sourceKey":"result","destinationUnit":{"$ref":"17"},"destinationKey":"target","guid":"b6178236-e9ff-4af2-8949-e68a4b086f64","$type":"Unity.VisualScripting.ValueConnection"}],"$version":"A"}}'
    _objectReferences:
    - {fileID: 6919741639559314521, guid: 53221ed6f53e33c4c9d9ae8ed450e8a6, type: 3}
    - {fileID: 6919741639559314521, guid: 53221ed6f53e33c4c9d9ae8ed450e8a6, type: 3}
"""

print("=" * 70)
print("Parsing Daniel's exact asset")
print("=" * 70)

g = parse_unity_graph(DANIEL_CONTENT, "Assets/Scripts/Test.asset")
if g is None:
    print("[FAIL] Parser returned None")
else:
    print(f"[OK] unit_count: {g['unit_count']}")
    print(f"[OK] connections: {len(g['connections'])}")
    print(f"[OK] has_update_root: {g['has_update_root']}")
    print(f"[OK] graph_type: {g['graph_type']}")
    print()
    print("Units:")
    for u in g["units"]:
        member = u.get("member")
        member_str = ""
        if member:
            member_str = f" name={member.get('name')} target={member.get('targetType')}"
        print(f"  - {u['type']}{member_str}")
    print()
    print("Connections:")
    for c in g["connections"]:
        print(f"  - {c['source_unit'][:8]} -> {c['destination_unit'][:8]}")
    print()

    issues = run_all_unity_graph_rules([g])
    print(f"Issues found: {len(issues)}")
    for i in issues:
        print(f"  {i['rule_id']} ({i['severity']}): {i['message']}")
