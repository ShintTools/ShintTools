import asyncio
from api.database import licenses

KEYS_TO_CHECK = [
    "shnt-indie-4728b131f823cd5f",
    "shnt_indie_4728c1319e23cd5f",
]

async def main():
    print("=== Licencias existentes en MongoDB ===")
    async for doc in licenses.find({"studio": "ShintTools_Unity"}):
        print(f"  api_key: '{doc.get('api_key')}'  tier: {doc.get('tier')}  active: {doc.get('active')}")
    print()

    print("=== Verificando claves de Daniel ===")
    for key in KEYS_TO_CHECK:
        doc = await licenses.find_one({"api_key": key})
        if doc:
            print(f"  [EXISTE] '{key}' -> tier={doc.get('tier')} active={doc.get('active')}")
        else:
            print(f"  [NO EXISTE] '{key}'")
            result = await licenses.insert_one({
                "api_key": key,
                "tier": "indie",
                "studio": "ShintTools_Unity",
                "active": True
            })
            print(f"  [CREADA] '{key}' -> MongoDB ID: {result.inserted_id}")

asyncio.run(main())
