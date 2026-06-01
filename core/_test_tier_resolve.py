import asyncio
from api.database import licenses, resolve_tier

async def main():
    api_key = "shnt-indie-4728b131f823cd5f"

    # 1. Verificar documento en MongoDB
    print("=== 1. MongoDB document ===")
    doc = await licenses.find_one({"api_key": api_key})
    print(f"  Raw doc (sin filtro active): {doc}")
    print()

    doc_active = await licenses.find_one({"api_key": api_key, "active": True})
    print(f"  Doc con active=True: {doc_active}")
    print()

    # 2. Usar resolve_tier tal cual lo usa el endpoint
    print("=== 2. resolve_tier() result ===")
    tier = await resolve_tier(api_key)
    print(f"  tier = '{tier}'")
    print()

    # 3. Simular el gate del endpoint
    print("=== 3. Endpoint gate simulation ===")
    if tier == "free":
        print("  RESULT: 403 - 'AI explanations are an Indie-tier feature.'")
        print("  >>> BUG REPRODUCIDO <<<")
    else:
        print(f"  RESULT: OK - pasaria al LLM con tier='{tier}'")

asyncio.run(main())
