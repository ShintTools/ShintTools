#!/usr/bin/env python3
"""Create a test license key in MongoDB for development."""

import asyncio
import os

from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = "shinttools"


async def create_test_license():
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    licenses = db["licenses"]

    # Insert test license
    result = await licenses.insert_one(
        {
            "api_key": "sk-test-indie",
            "tier": "indie",
            "studio": "TestStudio",
            "active": True,
        }
    )

    print(f"[OK] License created with ID: {result.inserted_id}")
    print("     API Key: sk-test-indie")
    print("     Tier: indie")
    print("\nRaul can now use this key in the plugin.")

    client.close()


if __name__ == "__main__":
    asyncio.run(create_test_license())
