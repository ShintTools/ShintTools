#!/usr/bin/env python3
"""seed_license.py — Insert or update a ShintTools license in MongoDB.

Usage
-----
    # Indie tier (default)
    python core/scripts/seed_license.py --key sk_XXXXXXXX

    # Studio tier (for LOD Auditor testing)
    python core/scripts/seed_license.py --key sk_XXXXXXXX --tier studio --studio "TestStudio"  # noqa: E501

    # Custom MongoDB URL
    python core/scripts/seed_license.py --key sk_XXXXXXXX --tier studio --mongo mongodb://localhost:27017  # noqa: E501

    # List existing licenses
    python core/scripts/seed_license.py --list

Tiers: free | indie | studio | enterprise

The script upserts: if the key already exists it updates tier/active/studio;
if it doesn't it inserts a new document.

Requires pymongo:
    pip install pymongo
"""

import argparse
import sys
from datetime import datetime, timezone

try:
    from pymongo import MongoClient
    from pymongo.errors import ConnectionFailure
except ImportError:
    print("ERROR: pymongo not installed. Run: pip install pymongo")
    sys.exit(1)


DB_NAME = "shinttools"
COLLECTION = "licenses"
VALID_TIERS = ("free", "indie", "studio", "enterprise")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage ShintTools licenses in MongoDB."
    )
    parser.add_argument("--key", help="API key to insert/update (e.g. shint_abc123)")
    parser.add_argument(
        "--tier",
        default="indie",
        choices=VALID_TIERS,
        help="Subscription tier [default: indie]",
    )
    parser.add_argument("--studio", default="", help="Studio name (optional)")
    parser.add_argument(
        "--deactivate",
        action="store_true",
        help="Set active=False for this key instead of True",
    )
    parser.add_argument(
        "--list", action="store_true", help="List all licenses and exit"
    )
    parser.add_argument(
        "--mongo",
        default="mongodb://localhost:27017",
        help="MongoDB connection URL [default: mongodb://localhost:27017]",
    )
    args = parser.parse_args()

    # ── Connect ──────────────────────────────────────────────────────────────
    try:
        client: MongoClient = MongoClient(args.mongo, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        print(f"✓ Connected to MongoDB at {args.mongo}")
    except ConnectionFailure as exc:
        print(f"ERROR: Cannot connect to MongoDB at {args.mongo}\n  {exc}")
        print("\nMake sure MongoDB is running. If using Docker:")
        print("  docker run -d -p 27017:27017 --name mongo mongo:7")
        sys.exit(1)

    db = client[DB_NAME]
    col = db[COLLECTION]

    # ── List mode ────────────────────────────────────────────────────────────
    if args.list:
        docs = list(col.find({}, {"_id": 0}))
        if not docs:
            print("No licenses found in collection.")
        else:
            print(f"\n{'KEY':<30} {'TIER':<8} {'ACTIVE':<8} {'STUDIO'}")
            print("-" * 60)
            for d in docs:
                print(
                    f"{d.get('api_key','?'):<30} "
                    f"{d.get('tier','?'):<8} "
                    f"{str(d.get('active','?')):<8} "
                    f"{d.get('studio','')}"
                )
        client.close()
        return

    # ── Upsert mode ──────────────────────────────────────────────────────────
    if not args.key:
        print("ERROR: --key is required (or use --list to view existing licenses).")
        parser.print_help()
        sys.exit(1)

    active = not args.deactivate
    doc = {
        "api_key": args.key,
        "tier": args.tier,
        "active": active,
        "studio": args.studio,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    result = col.update_one(
        {"api_key": args.key},
        {
            "$set": doc,
            "$setOnInsert": {"created_at": datetime.now(timezone.utc).isoformat()},
        },
        upsert=True,
    )

    if result.upserted_id:
        print(
            f"✓ License INSERTED: key='{args.key}' tier='{args.tier}' active={active}"
        )
    else:
        print(
            f"✓ License UPDATED:  key='{args.key}' tier='{args.tier}' active={active}"
        )

    print("\nVerification — document in MongoDB:")
    saved = col.find_one({"api_key": args.key}, {"_id": 0})
    for k, v in (saved or {}).items():
        print(f"  {k}: {v}")

    print("\nNext steps:")
    print("  1. Share the key with the plugin team (Unity or UE5)")
    print("  2. They paste it in Plugin Settings → Validate to activate")
    print("  3. Or manually set api_key in shinttools.config.json + restart core")

    client.close()


if __name__ == "__main__":
    main()
