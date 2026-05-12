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
COLLECTION_EXPLANATION_CACHE = "explanation_cache"

# Create the async MongoDB client
client = AsyncIOMotorClient(MONGO_URL)  # type: ignore[var-annotated]

# Reference to the shinttools database
database = client[DB_NAME]

# Reference to collections
analysis_results = database[COLLECTION_ANALYSIS]
licenses = database[COLLECTION_LICENSES]
project_scores = database[COLLECTION_SCORES]
explanation_cache = database[COLLECTION_EXPLANATION_CACHE]

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
                "Run: python core/scripts/seed_license.py "
                "--key <your-key> to create it.",
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


# ── Explanation cache ─────────────────────────────────────────────────────
#
# Per-issue LLM explanations are deterministic for a given (prompt,
# model) pair, so we cache them by hash. The same rule_id + same code
# snippet + same model + same prompt template -> same explanation,
# and most projects hit the same N rules dozens of times across files,
# so the first call pays the 20-40 s LLM bill and every repeat call
# returns in single-digit milliseconds from MongoDB.
#
# Cache key (`_id`) is computed by the caller as
# ``sha1(model_id || prompt_text)``. Putting both into the hash means
# any change to the prompt template, to the rule_explanation
# docstring, or to the model file automatically invalidates the
# affected entries — no manual cache flush ever needed.
#
# Schema::
#
#     {
#         "_id":                "<sha1 cache key>",
#         "rule_id":            "CS001",
#         "rule_name":          "GetWorld without null-check",
#         "explanation":        "Your BeginPlay ...",
#         "model_id":           "deepseek-coder-1.3b-instruct.Q4_K_M",
#         "generation_seconds": 18.4,
#         "created_at":         "<ISO timestamp>",
#     }


async def get_cached_explanation(cache_key: str) -> dict | None:
    """Return the cached explanation document for the given key, or
    None on miss / DB error.

    Best-effort by design: any MongoDB hiccup degrades into a fresh
    LLM call rather than failing the request, so the cache is purely
    a perf optimisation and never a correctness boundary.
    """
    if not cache_key:
        return None
    try:
        doc = await explanation_cache.find_one({"_id": cache_key})
        return doc
    except Exception as exc:
        logger.warning(
            "get_cached_explanation: lookup FAILED (%s) — falling "
            "through to fresh LLM call.",
            exc,
        )
        return None


async def save_cached_explanation(cache_key: str, payload: dict) -> None:
    """Persist an explanation result to the cache. Best-effort:
    silently ignores DB errors so the response we already produced
    is never blocked by a write failure.

    Uses ``replace_one(upsert=True)`` so a re-generation under the
    same key just overwrites the old entry — useful when an operator
    manually re-runs an explanation to refresh a stale or low-quality
    response.
    """
    if not cache_key:
        return
    try:
        await explanation_cache.replace_one(
            {"_id": cache_key},
            {"_id": cache_key, **payload},
            upsert=True,
        )
    except Exception as exc:
        logger.warning(
            "save_cached_explanation: insert FAILED (%s) — request "
            "succeeds but the result is not cached for next time.",
            exc,
        )
