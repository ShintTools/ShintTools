import httpx
import json

payload = {
    "api_key": "shnt-indie-4728b131f823cd5f",
    "project_name": "ShintTools_Unity",
    "project_id": "",
    "issue": {
        "rule_id": "UN004",
        "rule_name": "Debug.Log in Update",
        "rule_explanation": "",
        "file_path": "Assets/Scripts/Script.cs",
        "asset_path": "Assets/Scripts/Script.cs",
        "message": "Debug.Log inside Update floods the console and serialises strings every frame.",
        "is_auto_fixable": True,
        "severity": "warning"
    }
}

print("--- Sending request to /agent/explain ---")
print(f"api_key: {payload['api_key']}")
print(f"rule_id: {payload['issue']['rule_id']}")
print()

try:
    r = httpx.post("http://localhost:18200/agent/explain", json=payload, timeout=60)
    print(f"Status: {r.status_code}")
    print(f"Response: {json.dumps(r.json(), indent=2)}")
except httpx.ConnectError:
    print("ERROR: No se puede conectar a localhost:18200 — el servidor no esta corriendo")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
