# core/modules/assistant/conversation_store.py
#
# Conversations + turns for the assistant.
#
# Storage follows the Predictive session_store pattern exactly: MongoDB with
# TTL indexes when reachable, in-process fallback otherwise, Mongo always
# best-effort (its absence must never break a turn). One deliberate twist:
# persistence is a per-conversation decision driven by the caller's tier
# capability ("none" -> in-process only, even with Mongo up), because Free
# conversations must not outlive the session by contract.

from __future__ import annotations

import time
import uuid
from typing import Any

# Active conversations idle longer than this are gone. Long enough for a
# working day with breaks, short enough that an abandoned editor session
# doesn't accumulate forever.
CONVERSATION_TTL_S = 12 * 3600

_mem_conversations: dict[str, dict[str, Any]] = {}

_ttl_ready = False


def _now() -> float:
    return time.time()


def _purge_mem() -> None:
    cutoff = _now()
    for key in [
        k
        for k, v in _mem_conversations.items()
        if v.get("_expires_at", 0) < cutoff
    ]:
        _mem_conversations.pop(key, None)


async def _collection():
    """The Mongo conversations collection, or None when unavailable."""
    global _ttl_ready
    try:
        from api.database import database, ping_database

        if not await ping_database():
            return None
        conversations = database["assistant_conversations"]
        if not _ttl_ready:
            await conversations.create_index(
                "expires_at", expireAfterSeconds=0
            )
            _ttl_ready = True
        return conversations
    except Exception:  # noqa: BLE001 — Mongo is best-effort in the Core
        return None


def _new_conversation_doc(
    studio_id: str, project_id: str, module_context: str
) -> dict[str, Any]:
    return {
        "conversation_id": f"ac-{uuid.uuid4().hex[:12]}",
        "studio_id": studio_id,
        "project_id": project_id,
        "module_context": module_context,
        "status": "active",
        "turns": [],
        "started_at": _now(),
        "last_active_at": _now(),
    }


def _expiry():
    from datetime import datetime, timedelta, timezone

    return datetime.now(timezone.utc) + timedelta(seconds=CONVERSATION_TTL_S)


async def start_conversation(
    studio_id: str,
    project_id: str,
    module_context: str = "",
    *,
    persist: bool = True,
) -> str:
    """Create a conversation and return its id.

    ``persist=False`` (Free tier's memory="none") keeps it in process memory
    regardless of Mongo availability — by contract, not by accident.
    """
    doc = _new_conversation_doc(studio_id, project_id, module_context)

    if persist:
        col = await _collection()
        if col is not None:
            mongo_doc = dict(doc)
            mongo_doc["expires_at"] = _expiry()
            await col.insert_one(mongo_doc)
            return doc["conversation_id"]

    _purge_mem()
    doc["_expires_at"] = _now() + CONVERSATION_TTL_S
    _mem_conversations[doc["conversation_id"]] = doc
    return doc["conversation_id"]


async def get_conversation(conversation_id: str) -> dict[str, Any] | None:
    col = await _collection()
    if col is not None:
        doc = await col.find_one(
            {"conversation_id": conversation_id}, {"_id": 0, "expires_at": 0}
        )
        if doc is not None:
            return doc

    _purge_mem()
    doc = _mem_conversations.get(conversation_id)
    if doc is None:
        return None
    return {k: v for k, v in doc.items() if k != "_expires_at"}


async def append_turn(
    conversation_id: str,
    role: str,
    raw_text: str,
    *,
    intent: str = "",
    context_ref: str = "",
    rule_id: str = "",
    asset_path: str = "",
) -> dict[str, Any] | None:
    """Append a turn; returns the turn dict, or None if the conversation
    doesn't exist (expired or never created).

    ``rule_id``/``asset_path`` are stored alongside ``context_ref`` so a
    later follow-up can inherit what "this" referred to
    (conversation_context.last_grounding). Without them the analysis is
    recoverable but the row within it is not, and "and why does that
    matter?" would re-answer about the wrong finding.
    """
    turn = {
        "turn_id": f"at-{uuid.uuid4().hex[:12]}",
        "role": role,
        "intent": intent,
        "raw_text": raw_text,
        "context_ref": context_ref,
        "rule_id": rule_id,
        "asset_path": asset_path,
        "created_at": _now(),
    }

    col = await _collection()
    if col is not None:
        result = await col.update_one(
            {"conversation_id": conversation_id},
            {
                "$push": {"turns": turn},
                "$set": {"last_active_at": _now(), "expires_at": _expiry()},
            },
        )
        if result.matched_count:
            return turn

    _purge_mem()
    doc = _mem_conversations.get(conversation_id)
    if doc is None:
        return None
    doc["turns"].append(turn)
    doc["last_active_at"] = _now()
    doc["_expires_at"] = _now() + CONVERSATION_TTL_S
    return turn
