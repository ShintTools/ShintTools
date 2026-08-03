# core/modules/assistant/rule_store.py
#
# Persistent studio rules + LLM-evaluation cache.
#
# Replaces the ephemeral flow (rules travel in every request body, defined
# in the plugin's Settings panel, evaluated from scratch each scan) with
# versioned rules that live in the studio's local Mongo. Two tiers:
#
#   template      — Tier A, deterministic (rule_templates.py). Free to run.
#   llm_evaluated — Tier B, today's custom_rule_checker semantics, but with
#                   a cache keyed on sha1(rule_id:version:file_hash): an
#                   unchanged file under an unchanged rule NEVER re-invokes
#                   the LLM.
#
# A rule only runs in scans when status="active" AND confirmed_by_user —
# the same explicit-confirmation contract memory facts follow.

from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any

_mem_rules: dict[str, dict[str, Any]] = {}
_mem_eval_cache: dict[str, dict[str, Any]] = {}

EVAL_CACHE_TTL_S = 90 * 24 * 3600  # mirror explanation_cache's 90 days

_indexes_ready = False


def _now() -> float:
    return time.time()


async def _db():
    global _indexes_ready
    try:
        from api.database import database, ping_database

        if not await ping_database():
            return None
        rules = database["studio_rules"]
        cache = database["studio_rule_eval_cache"]
        if not _indexes_ready:
            await rules.create_index([("studio_id", 1), ("status", 1)])
            await cache.create_index("expires_at", expireAfterSeconds=0)
            _indexes_ready = True
        return rules, cache
    except Exception:  # noqa: BLE001
        return None


def _new_rule_doc(
    studio_id: str,
    project_id: str,
    name: str,
    tier: str,
    scope: dict[str, Any],
    body: dict[str, Any],
    source_conversation_id: str,
) -> dict[str, Any]:
    doc = {
        "rule_id": f"sr-{uuid.uuid4().hex[:12]}",
        "studio_id": studio_id,
        "project_id": project_id,  # "" = studio-wide
        "name": name,
        "tier": tier,  # "template" | "llm_evaluated"
        "status": "draft",
        "version": 1,
        "confirmed_by_user": False,
        "source_conversation_id": source_conversation_id,
        "scope": scope,  # {engine, applies_to}
        "created_at": _now(),
        "updated_at": _now(),
    }
    if tier == "template":
        doc["template"] = body  # {template_id, params}
    else:
        doc["llm_rule"] = body  # {description, example_violation, example_ok}
    return doc


async def create_rule(
    studio_id: str,
    project_id: str,
    name: str,
    tier: str,
    scope: dict[str, Any],
    body: dict[str, Any],
    source_conversation_id: str = "",
) -> dict[str, Any]:
    doc = _new_rule_doc(
        studio_id, project_id, name, tier, scope, body, source_conversation_id
    )
    db = await _db()
    if db is not None:
        rules, _ = db
        await rules.insert_one(dict(doc))
    else:
        _mem_rules[doc["rule_id"]] = doc
    return {k: v for k, v in doc.items() if k != "_id"}


async def set_rule_status(
    rule_id: str, *, status: str | None = None, confirmed: bool | None = None
) -> dict[str, Any] | None:
    update: dict[str, Any] = {"updated_at": _now()}
    if status is not None:
        if status not in ("draft", "active", "deprecated"):
            return None
        update["status"] = status
    if confirmed is not None:
        update["confirmed_by_user"] = confirmed

    db = await _db()
    if db is not None:
        rules, _ = db
        doc = await rules.find_one_and_update(
            {"rule_id": rule_id},
            {"$set": update},
            return_document=True,
            projection={"_id": 0},
        )
        if doc is not None:
            return doc

    doc = _mem_rules.get(rule_id)
    if doc is None:
        return None
    doc.update(update)
    return dict(doc)


async def list_rules(
    studio_id: str,
    project_id: str = "",
    *,
    statuses: tuple[str, ...] = ("draft", "active"),
) -> list[dict[str, Any]]:
    query: dict[str, Any] = {
        "studio_id": studio_id,
        "status": {"$in": list(statuses)},
    }
    if project_id:
        query["project_id"] = {"$in": [project_id, ""]}

    db = await _db()
    if db is not None:
        rules, _ = db
        docs = await rules.find(query, {"_id": 0}).sort(
            "created_at", -1
        ).to_list(length=500)
        if docs:
            return docs

    out = [
        dict(d)
        for d in _mem_rules.values()
        if d["studio_id"] == studio_id
        and d["status"] in statuses
        and (not project_id or d["project_id"] in (project_id, ""))
    ]
    out.sort(key=lambda d: d["created_at"], reverse=True)
    return out


async def active_rules(
    studio_id: str, project_id: str = "", engine: str = ""
) -> list[dict[str, Any]]:
    """Rules that may run in a scan: active + user-confirmed + engine match."""
    rules = await list_rules(studio_id, project_id, statuses=("active",))
    engine = (engine or "").strip().lower()
    out = []
    for rule in rules:
        if not rule.get("confirmed_by_user"):
            continue
        rule_engine = str(rule.get("scope", {}).get("engine", "both")).lower()
        if engine and rule_engine not in ("both", engine):
            continue
        out.append(rule)
    return out


# ── LLM evaluation cache ──────────────────────────────────────────────────────


def eval_cache_key(rule_id: str, version: int, content: str) -> str:
    file_hash = hashlib.sha1(content.encode("utf-8", "replace")).hexdigest()
    return hashlib.sha1(
        f"{rule_id}:{version}:{file_hash}".encode()
    ).hexdigest()


async def get_cached_eval(key: str) -> list[dict[str, Any]] | None:
    db = await _db()
    if db is not None:
        _, cache = db
        doc = await cache.find_one({"_id": key})
        if doc is not None:
            return doc.get("violations", [])
    entry = _mem_eval_cache.get(key)
    if entry and entry["_expires_at"] > _now():
        return entry["violations"]
    return None


async def save_cached_eval(key: str, violations: list[dict[str, Any]]) -> None:
    db = await _db()
    if db is not None:
        _, cache = db
        from datetime import datetime, timedelta, timezone

        await cache.replace_one(
            {"_id": key},
            {
                "_id": key,
                "violations": violations,
                "expires_at": datetime.now(timezone.utc)
                + timedelta(seconds=EVAL_CACHE_TTL_S),
            },
            upsert=True,
        )
        return
    _mem_eval_cache[key] = {
        "violations": violations,
        "_expires_at": _now() + EVAL_CACHE_TTL_S,
    }
