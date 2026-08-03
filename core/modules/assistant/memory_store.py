# core/modules/assistant/memory_store.py
#
# Studio memory: facts, per-project settings, conversation summaries.
#
# The hard rule this module enforces mechanically: a fact NEVER influences
# anything while status="proposed". fact_extractor proposes; only an
# explicit user confirmation (POST /assistant/memory/confirm) promotes to
# "confirmed", and only confirmed facts are returned by the grounding
# queries the actions and the future proactive detector read. There is no
# code path from "the model heard something" to "the assistant acts on it"
# that does not pass through a human.
#
# Everything is local: same Mongo instance as the rest of the Core, same
# best-effort posture, same in-process fallback pattern as
# conversation_store. Facts have NO TTL — memory is the product; deletion
# is explicit (retract / purge_project for NDA close-outs).

from __future__ import annotations

import time
import uuid
from typing import Any

_mem_facts: dict[str, dict[str, Any]] = {}
_mem_settings: dict[str, dict[str, Any]] = {}
_mem_summaries: dict[str, list[dict[str, Any]]] = {}

_indexes_ready = False

FACT_STATUSES = ("proposed", "confirmed", "superseded", "retracted")


def _now() -> float:
    return time.time()


async def _db():
    """(facts, settings, summaries) collections, or None when unavailable."""
    global _indexes_ready
    try:
        from api.database import database, ping_database

        if not await ping_database():
            return None
        facts = database["assistant_memory_facts"]
        settings = database["assistant_settings"]
        summaries = database["assistant_conversation_summaries"]
        if not _indexes_ready:
            await facts.create_index([("studio_id", 1), ("project_id", 1)])
            await facts.create_index("status")
            _indexes_ready = True
        return facts, settings, summaries
    except Exception:  # noqa: BLE001 — Mongo is best-effort in the Core
        return None


# ── Facts ─────────────────────────────────────────────────────────────────────


def _new_fact_doc(
    studio_id: str,
    project_id: str,
    fact_type: str,
    value: str,
    source: dict[str, Any],
) -> dict[str, Any]:
    return {
        "fact_id": f"af-{uuid.uuid4().hex[:12]}",
        "studio_id": studio_id,
        "project_id": project_id,  # "" = studio-wide
        "type": fact_type,  # studio_fact | preference | decision
        "value": value,
        "structured": {},
        "status": "proposed",
        "superseded_by": "",
        "source": source,  # {conversation_id, turn_id, module}
        "created_at": _now(),
        "updated_at": _now(),
        "last_confirmed_at": None,
        "tags": [],
    }


async def propose_fact(
    studio_id: str,
    project_id: str,
    fact_type: str,
    value: str,
    source: dict[str, Any],
) -> dict[str, Any]:
    doc = _new_fact_doc(studio_id, project_id, fact_type, value, source)
    db = await _db()
    if db is not None:
        facts, _, _ = db
        await facts.insert_one(dict(doc))
    else:
        _mem_facts[doc["fact_id"]] = doc
    return {k: v for k, v in doc.items() if k != "_id"}


async def set_fact_status(fact_id: str, status: str) -> dict[str, Any] | None:
    """Confirm / retract a proposed fact. Returns the updated doc or None."""
    if status not in FACT_STATUSES:
        return None
    update = {"status": status, "updated_at": _now()}
    if status == "confirmed":
        update["last_confirmed_at"] = _now()

    db = await _db()
    if db is not None:
        facts, _, _ = db
        result = await facts.find_one_and_update(
            {"fact_id": fact_id},
            {"$set": update},
            return_document=True,
            projection={"_id": 0},
        )
        if result is not None:
            return result

    doc = _mem_facts.get(fact_id)
    if doc is None:
        return None
    doc.update(update)
    return dict(doc)


async def list_facts(
    studio_id: str,
    project_id: str = "",
    *,
    statuses: tuple[str, ...] = ("proposed", "confirmed"),
) -> list[dict[str, Any]]:
    """Facts for a studio: project-scoped ones plus studio-wide ones."""
    query = {
        "studio_id": studio_id,
        "status": {"$in": list(statuses)},
        "project_id": {"$in": [project_id, ""]} if project_id else "",
    }
    if not project_id:
        query.pop("project_id")

    db = await _db()
    if db is not None:
        facts, _, _ = db
        cursor = facts.find(query, {"_id": 0}).sort("created_at", -1)
        docs = await cursor.to_list(length=500)
        if docs:
            return docs

    out = [
        dict(d)
        for d in _mem_facts.values()
        if d["studio_id"] == studio_id
        and d["status"] in statuses
        and (not project_id or d["project_id"] in (project_id, ""))
    ]
    out.sort(key=lambda d: d["created_at"], reverse=True)
    return out


async def confirmed_facts(
    studio_id: str, project_id: str = ""
) -> list[dict[str, Any]]:
    """The ONLY view actions and detectors may ground on."""
    return await list_facts(studio_id, project_id, statuses=("confirmed",))


async def purge_project(studio_id: str, project_id: str) -> int:
    """Hard-delete every fact and summary of a project (NDA close-out)."""
    removed = 0
    db = await _db()
    if db is not None:
        facts, _, summaries = db
        r1 = await facts.delete_many(
            {"studio_id": studio_id, "project_id": project_id}
        )
        removed += r1.deleted_count
        await summaries.delete_many(
            {"studio_id": studio_id, "project_id": project_id}
        )
    for fid in [
        f
        for f, d in _mem_facts.items()
        if d["studio_id"] == studio_id and d["project_id"] == project_id
    ]:
        _mem_facts.pop(fid, None)
        removed += 1
    return removed


# ── Per-project settings (silent mode) ────────────────────────────────────────


async def set_memory_muted(
    studio_id: str, project_id: str, muted: bool
) -> None:
    key = f"{studio_id}:{project_id}"
    db = await _db()
    if db is not None:
        _, settings, _ = db
        await settings.replace_one(
            {"_id": key},
            {"_id": key, "memory_muted": muted, "updated_at": _now()},
            upsert=True,
        )
        return
    _mem_settings[key] = {"memory_muted": muted}


async def is_memory_muted(studio_id: str, project_id: str) -> bool:
    key = f"{studio_id}:{project_id}"
    db = await _db()
    if db is not None:
        _, settings, _ = db
        doc = await settings.find_one({"_id": key})
        if doc is not None:
            return bool(doc.get("memory_muted"))
    return bool(_mem_settings.get(key, {}).get("memory_muted"))


# ── Conversation summaries (compaction) ───────────────────────────────────────

# Verbatim turns kept when compacting; older ones collapse into a digest.
KEEP_VERBATIM_TURNS = 8
# Compact once a conversation exceeds this many turns.
COMPACT_THRESHOLD = 24


def digest_turns(turns: list[dict[str, Any]]) -> str:
    """Deterministic digest of old turns — no LLM, nothing invented.

    One line per user turn: its intent and the opening of the message.
    An LLM-written summary can replace this later; the contract (summary
    text + covered range) stays the same.
    """
    lines: list[str] = []
    for turn in turns:
        if turn.get("role") != "user":
            continue
        head = str(turn.get("raw_text", ""))[:90].replace("\n", " ")
        lines.append(f"[{turn.get('intent', '?')}] {head}")
    return "\n".join(lines)


async def compact_conversation(
    conversation_id: str, studio_id: str, project_id: str
) -> bool:
    """Fold old turns into a summary doc when the thread grows long.

    Returns True when a compaction happened. Mongo-only: the in-process
    fallback keeps full turns (they die with the process anyway).
    """
    db = await _db()
    if db is None:
        return False
    _, _, summaries = db

    try:
        from api.database import database

        conversations = database["assistant_conversations"]
        doc = await conversations.find_one(
            {"conversation_id": conversation_id}, {"turns": 1}
        )
        if not doc:
            return False
        turns = doc.get("turns", [])
        if len(turns) <= COMPACT_THRESHOLD:
            return False

        old, kept = turns[:-KEEP_VERBATIM_TURNS], turns[-KEEP_VERBATIM_TURNS:]
        await summaries.insert_one(
            {
                "summary_id": f"as-{uuid.uuid4().hex[:12]}",
                "conversation_id": conversation_id,
                "studio_id": studio_id,
                "project_id": project_id,
                "summary_text": digest_turns(old),
                "covers_turns": len(old),
                "created_at": _now(),
            }
        )
        await conversations.update_one(
            {"conversation_id": conversation_id},
            {"$set": {"turns": kept, "compacted": True}},
        )
        return True
    except Exception:  # noqa: BLE001
        return False
