# core/modules/predictive/session_store.py
#
# Batched-ingest sessions + report cache.
#
# Big projects can't ship one giant analyze payload (the LOD audit learned
# this the hard way — clients batch at 150 assets/request). A session
# accumulates ingests server-side until /predict/analyze runs it; the
# resulting report is cached so /predict/simulate (M4) can replay
# selections against it without re-analysis.
#
# Storage: MongoDB with a TTL index (sessions 6h, reports 24h) via the same
# motor client the rest of the Core uses. Mongo being down must never break
# the feature (the Core treats Mongo as best-effort everywhere) — an
# in-process fallback keeps sessions working for the single-container case,
# with the documented caveat that they don't survive a restart.

from __future__ import annotations

import time
import uuid
from typing import Any

SESSION_TTL_S = 6 * 3600
REPORT_TTL_S = 24 * 3600

# In-process fallback when Mongo is unreachable. Keyed by id; each value
# carries "_expires_at" checked on read.
_mem_sessions: dict[str, dict[str, Any]] = {}
_mem_reports: dict[str, dict[str, Any]] = {}

_ttl_ready = False


def _now() -> float:
    return time.time()


def _purge_mem() -> None:
    now = _now()
    for store in (_mem_sessions, _mem_reports):
        for key in [k for k, v in store.items() if v.get("_expires_at", 0) < now]:
            store.pop(key, None)


async def _collections():
    """(sessions, reports) Mongo collections, or None when unavailable."""
    global _ttl_ready
    try:
        from api.database import database, ping_database

        if not await ping_database():
            return None
        sessions = database["predictive_sessions"]
        reports = database["predictive_reports"]
        if not _ttl_ready:
            # TTL indexes are idempotent — Mongo no-ops when they exist.
            await sessions.create_index("expires_at", expireAfterSeconds=0)
            await reports.create_index("expires_at", expireAfterSeconds=0)
            _ttl_ready = True
        return sessions, reports
    except Exception:  # noqa: BLE001 — Mongo is best-effort in the Core
        return None


def _new_session_doc(engine: str, project_name: str, platform_profile: str) -> dict:
    return {
        "session_id": f"ps-{uuid.uuid4().hex[:12]}",
        "engine": engine,
        "project_name": project_name,
        "platform_profile": platform_profile,
        "assets": [],
        "scenes": [],
        "code_issues": [],
        "code_files": [],
        "config": {},
        "created_at": _now(),
    }


async def start_session(
    engine: str, project_name: str, platform_profile: str
) -> str:
    doc = _new_session_doc(engine, project_name, platform_profile)
    cols = await _collections()
    if cols is not None:
        sessions, _ = cols
        from datetime import datetime, timedelta, timezone

        mongo_doc = dict(doc)
        mongo_doc["expires_at"] = datetime.now(timezone.utc) + timedelta(
            seconds=SESSION_TTL_S
        )
        try:
            await sessions.insert_one(mongo_doc)
            return doc["session_id"]
        except Exception:  # noqa: BLE001
            pass
    _purge_mem()
    doc["_expires_at"] = _now() + SESSION_TTL_S
    _mem_sessions[doc["session_id"]] = doc
    return doc["session_id"]


# kind -> (payload key it arrives under, session list it lands in)
_KIND_FIELDS = {
    "assets": ("assets", "assets"),
    "scene": ("scenes", "scenes"),
    "code": ("issues", "code_issues"),
    # Preferred over "code": raw source Predictive scans itself. See
    # AnalyzeRequest.code_files in schema.py.
    "code_files": ("files", "code_files"),
}


async def ingest(
    session_id: str, kind: str, payload: dict[str, Any]
) -> tuple[int, dict[str, int]] | None:
    """Append one batch to the session. Returns (accepted, totals) or None
    when the session is unknown/expired."""
    cols = await _collections()
    if cols is not None:
        sessions, _ = cols
        try:
            doc = await sessions.find_one({"session_id": session_id})
        except Exception:  # noqa: BLE001
            doc = None
        if doc is not None:
            update, accepted = _build_update(kind, payload)
            if update:
                try:
                    await sessions.update_one(
                        {"session_id": session_id}, update
                    )
                    fresh = await sessions.find_one({"session_id": session_id})
                    return accepted, _totals(fresh or doc)
                except Exception:  # noqa: BLE001
                    pass
    _purge_mem()
    doc = _mem_sessions.get(session_id)
    if doc is None:
        return None
    accepted = _apply_mem(doc, kind, payload)
    return accepted, _totals(doc)


def _build_update(kind: str, payload: dict[str, Any]):
    if kind == "config":
        return {"$set": {"config": payload.get("config") or payload}}, 1
    mapping = _KIND_FIELDS.get(kind)
    if mapping is None:
        return None, 0
    src_key, dest = mapping
    items = payload.get(src_key) or []
    return {"$push": {dest: {"$each": list(items)}}}, len(items)


def _apply_mem(doc: dict[str, Any], kind: str, payload: dict[str, Any]) -> int:
    if kind == "config":
        doc["config"] = payload.get("config") or payload
        return 1
    mapping = _KIND_FIELDS.get(kind)
    if mapping is None:
        return 0
    src_key, dest = mapping
    items = list(payload.get(src_key) or [])
    doc[dest].extend(items)
    return len(items)


def _totals(doc: dict[str, Any]) -> dict[str, int]:
    return {
        "assets": len(doc.get("assets") or []),
        "scenes": len(doc.get("scenes") or []),
        "code_issues": len(doc.get("code_issues") or []),
        "code_files": len(doc.get("code_files") or []),
        "config": 1 if doc.get("config") else 0,
    }


async def get_session(session_id: str) -> dict[str, Any] | None:
    cols = await _collections()
    if cols is not None:
        sessions, _ = cols
        try:
            doc = await sessions.find_one({"session_id": session_id})
            if doc is not None:
                doc.pop("_id", None)
                return doc
        except Exception:  # noqa: BLE001
            pass
    _purge_mem()
    return _mem_sessions.get(session_id)


async def save_report(report_id: str, report: dict[str, Any]) -> None:
    """Cache a finished report for the simulator. Best-effort."""
    cols = await _collections()
    if cols is not None:
        _, reports = cols
        from datetime import datetime, timedelta, timezone

        try:
            await reports.replace_one(
                {"report_id": report_id},
                {
                    "report_id": report_id,
                    "report": report,
                    "expires_at": datetime.now(timezone.utc)
                    + timedelta(seconds=REPORT_TTL_S),
                },
                upsert=True,
            )
            return
        except Exception:  # noqa: BLE001
            pass
    _purge_mem()
    _mem_reports[report_id] = {
        "report": report,
        "_expires_at": _now() + REPORT_TTL_S,
    }


async def get_report(report_id: str) -> dict[str, Any] | None:
    cols = await _collections()
    if cols is not None:
        _, reports = cols
        try:
            doc = await reports.find_one({"report_id": report_id})
            if doc is not None:
                return doc.get("report")
        except Exception:  # noqa: BLE001
            pass
    _purge_mem()
    entry = _mem_reports.get(report_id)
    return entry.get("report") if entry else None
