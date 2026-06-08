import logging
import os
from datetime import datetime, timedelta, timezone

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

# Create the async MongoDB client.
#
# Timeouts kept low (2s) so an unreachable Mongo fails fast and the request
# can fall back to the Free tier instead of hanging the editor for 30s
# (the pymongo default). The penalty is paid once per process; subsequent
# requests reuse the same client and its cached topology.
client = AsyncIOMotorClient(  # type: ignore[var-annotated]
    MONGO_URL,
    serverSelectionTimeoutMS=2000,
    connectTimeoutMS=2000,
    socketTimeoutMS=2000,
)

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
    tier, _ = await resolve_tier_detailed(api_key)
    return tier


async def _resolve_tier_via_dashboard(api_key: str) -> tuple[str, str]:
    """Fallback: validate the key against the remote dashboard and seed locally.

    Called automatically by resolve_tier_detailed when the key is absent
    from the local 'licenses' collection — covers the case where the
    Launcher seed never ran (container not started, wrong container name,
    key added after installation, etc.).

    Passes machine_id="" because the Core runs inside Docker and cannot
    read the host machine fingerprint. The dashboard validates by key
    validity alone in that case; binding is enforced only when the
    plugin explicitly calls /license/activate with the real machine_id.
    """
    from api.dashboard_license import activate  # lazy import — avoids circular dep

    try:
        result = await activate(api_key, machine_id="")
    except Exception as exc:
        logger.error("_resolve_tier_via_dashboard: unexpected error — %s", exc)
        return _DEFAULT_TIER, "db_unavailable"

    if not result.get("valid"):
        logger.warning(
            "_resolve_tier_via_dashboard: key=...%s not valid — %s",
            api_key[-6:],
            result.get("error", ""),
        )
        return _DEFAULT_TIER, "key_not_found"

    tier = str(result.get("tier") or "free").lower()
    studio = str(result.get("studio") or "")
    await seed_license(api_key, tier, studio)
    logger.info(
        "_resolve_tier_via_dashboard: auto-healed key=...%s → tier='%s'",
        api_key[-6:],
        tier,
    )
    return tier, ""


async def seed_license(api_key: str, tier: str, studio: str = "") -> None:
    """Upsert a license document into the local 'licenses' collection.

    Best-effort: logs and swallows any MongoDB error so that a write
    failure never blocks an activation that already succeeded against
    the remote dashboard.
    """
    if not api_key:
        return
    try:
        await licenses.update_one(
            {"api_key": api_key},
            {
                "$set": {
                    "api_key": api_key,
                    "tier": (tier or "free").lower(),
                    "studio": studio or "",
                    "active": True,
                }
            },
            upsert=True,
        )
        logger.info("seed_license: upserted key=...%s tier='%s'", api_key[-6:], tier)
    except Exception as exc:
        logger.error("seed_license: upsert FAILED key=...%s (%s)", api_key[-6:], exc)


async def resolve_tier_detailed(api_key: str) -> tuple[str, str]:
    """Like resolve_tier but also returns a machine-readable reason code.

    Returns (tier, reason) so callers that gate features can surface
    a specific error message in the HTTP response instead of the
    generic 'X is an Indie-tier feature.' — helping developers
    diagnose config problems without opening Docker logs.

    Reason codes:
        ""               — resolved successfully
        "empty_key"      — api_key field is blank in shinttools.config.json
        "key_not_found"  — key absent or inactive in 'licenses' collection
        "db_unavailable" — MongoDB unreachable
    """
    api_key = api_key.strip()
    if not api_key:
        logger.warning(
            "resolve_tier: api_key is EMPTY — defaulting to 'free'. "
            "Set 'api_key' in shinttools.config.json and restart the core."
        )
        return _DEFAULT_TIER, "empty_key"

    try:
        doc = await licenses.find_one(
            {"api_key": api_key, "active": True},
            {"tier": 1},
        )
        if doc and doc.get("tier"):
            tier = doc["tier"]
            logger.info("resolve_tier: key=...%s → tier='%s'", api_key[-6:], tier)
            return tier, ""
        else:
            logger.warning(
                "resolve_tier: api_key='...%s' not found locally — "
                "attempting dashboard fallback to auto-heal.",
                api_key[-6:],
            )
            return await _resolve_tier_via_dashboard(api_key)
    except Exception as exc:
        logger.error(
            "resolve_tier: MongoDB query FAILED (%s). Defaulting to 'free'. "
            "Is MongoDB running? Check MONGO_URL env var (current: %s).",
            exc,
            os.getenv("MONGO_URL", "mongodb://localhost:27017"),
        )

    return _DEFAULT_TIER, "db_unavailable"


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


# Cache entries older than this are treated as misses on read so a
# refreshed prompt template or improved model eventually replaces
# stale text in production. 90 days lines up with our LLM-iteration
# cadence — older than that and the answer is almost certainly worse
# than what the current model would produce.
EXPLANATION_CACHE_MAX_AGE_DAYS = 90


async def get_cached_explanation(
    cache_key: str,
    max_age_days: int = EXPLANATION_CACHE_MAX_AGE_DAYS,
) -> dict | None:
    """Return the cached explanation document for the given key, or
    None on miss / DB error / TTL expiry.

    Best-effort by design: any MongoDB hiccup degrades into a fresh
    LLM call rather than failing the request, so the cache is purely
    a perf optimisation and never a correctness boundary.

    Entries older than *max_age_days* are treated as misses. Pass
    ``max_age_days=0`` to disable the TTL check (rarely useful — only
    for admin tooling that wants to see every stored entry).
    """
    if not cache_key:
        return None
    try:
        doc = await explanation_cache.find_one({"_id": cache_key})
    except Exception as exc:
        logger.warning(
            "get_cached_explanation: lookup FAILED (%s) — falling "
            "through to fresh LLM call.",
            exc,
        )
        return None

    if not doc:
        return None

    if max_age_days > 0:
        created_at_raw = doc.get("created_at")
        if created_at_raw:
            try:
                # `created_at` is stored as an ISO-8601 string by
                # save_cached_explanation. We never wrote a tz-naive
                # value, but be defensive in case an older entry was.
                created_at = datetime.fromisoformat(created_at_raw)
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                age_cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
                if created_at < age_cutoff:
                    logger.info(
                        "get_cached_explanation: entry _id=%s is older "
                        "than %d days — treating as miss so a fresh "
                        "explanation is generated.",
                        cache_key[:12],
                        max_age_days,
                    )
                    return None
            except (ValueError, TypeError):
                # Malformed created_at — keep the entry rather than
                # discarding it; better stale text than no text.
                pass

    return doc


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
