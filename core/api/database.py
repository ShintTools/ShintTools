import logging
import os

from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger("shinttools.db")

# MongoDB connection URL — reads from environment variable or to localhost
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")

# Database and collection names
DB_NAME = "shinttools"
COLLECTION_ANALYSIS = "analysis_results"
COLLECTION_LICENSES = "licenses"
COLLECTION_SCORES = "project_scores"

# Create the async MongoDB client
client = AsyncIOMotorClient(MONGO_URL)  # type: ignore[var-annotated]

# Reference to the shinttools database
database = client[DB_NAME]

# Reference to collections
analysis_results = database[COLLECTION_ANALYSIS]
licenses = database[COLLECTION_LICENSES]
project_scores = database[COLLECTION_SCORES]

# Default tier when no license is found
_DEFAULT_TIER = "free"


async def ping_database() -> bool:
    """
    Checks if the MongoDB connection is alive.
    Returns True if connected, False otherwise.
    """
    try:
        await client.admin.command("ping")
        return True
    except Exception:
        return False


async def resolve_tier(api_key: str) -> str:
    """Resolve an api_key to a subscription tier name.

    Looks up the key in the 'licenses' collection.
    Expected document shape::

        {
            "api_key": "sk-xxxx",
            "tier": "indie",       # "free" | "indie"
            "studio": "StudioName",
            "active": true
        }

    Returns the tier name, or 'free' if the key is missing,
    inactive, or MongoDB is unreachable.
    """
    if not api_key:
        logger.warning(
            "resolve_tier: api_key is EMPTY — defaulting to 'free'. "
            "Set 'api_key' in shinttools.config.json and restart the core."
        )
        return _DEFAULT_TIER

    try:
        doc = await licenses.find_one(
            {"api_key": api_key, "active": True},
            {"tier": 1},
        )
        if doc and doc.get("tier"):
            tier = doc["tier"]
            logger.info("resolve_tier: key=...%s → tier='%s'", api_key[-6:], tier)
            return tier
        else:
            logger.warning(
                "resolve_tier: api_key='...%s' not found in 'licenses' collection "
                "(or 'active' is false). Defaulting to 'free'. "
                "Run: python core/scripts/seed_license.py --key <your-key> to create it.",
                api_key[-6:],
            )
    except Exception as exc:
        logger.error(
            "resolve_tier: MongoDB query FAILED (%s). Defaulting to 'free'. "
            "Is MongoDB running? Check MONGO_URL env var (current: %s).",
            exc,
            os.getenv("MONGO_URL", "mongodb://localhost:27017"),
        )

    return _DEFAULT_TIER


async def persist_score(score_doc: dict) -> None:
    """Save a Quality Score document to MongoDB.

    Best-effort — silently ignores errors so the main
    response is never blocked by a database failure.
    """
    try:
        await project_scores.insert_one(score_doc)
    except Exception:
        pass


async def get_latest_score(project_id: str) -> dict | None:
    """Return the most recent score document for a project."""
    try:
        doc = await project_scores.find_one(
            {"project_id": project_id},
            sort=[("timestamp", -1)],
        )
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc
    except Exception:
        return None


async def get_score_history(
    project_id: str,
    limit: int = 30,
) -> list[dict]:
    """Return the last *limit* score documents for a project."""
    try:
        cursor = (
            project_scores.find({"project_id": project_id})
            .sort("timestamp", -1)
            .limit(limit)
        )
        docs = await cursor.to_list(length=limit)
        for d in docs:
            d["_id"] = str(d["_id"])
        return docs
    except Exception:
        return []