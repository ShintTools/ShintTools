# core/modules/assistant/module_resolver.py
#
# Which module is this turn about, and which analysis should answer it.
#
# Two decisions the assistant was never making:
#
#   1. The message can NAME a module ("how is the code validator doing?").
#      That name outranks whatever panel happens to be open — asking about one
#      module while looking at another's results is the normal case, not an
#      edge case, and the old behaviour answered about the panel every time.
#
#   2. An ambient `context_ref` is only usable when it belongs to the module
#      being asked about. FShintAssistantContext publishes an analysis_id on
#      every scan and never expires it, so a LOD audit run an hour ago was
#      still grounding questions about C++ code. Matching the analysis's own
#      `report_type` against the resolved module is what stops that.
#
# Deterministic throughout. The model is not consulted about what the user is
# asking about — a wrong guess here is exactly the failure the whole
# closed-menu design exists to prevent.

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import module_registry
from .module_registry import ModuleInfo

# How old a stored scan may be before it stops being "what the project looks
# like" and becomes "what it looked like once".
#
# latest_analysis had no time bound at all, and resolve_analysis falls back to
# it whenever the client sends no context_ref — which is every turn on a client
# that never publishes one. The result was a week-old scan answering today's
# question with no indication of its age: three different questions about
# naming all came back "2909 findings", from a scan five days stale, phrased in
# the present tense.
#
# Two thresholds rather than one, because "slightly old" and "useless" deserve
# different answers. Under FRESH, say nothing — a scan from this morning is
# simply current. Between FRESH and IGNORE, still answer from it (the numbers
# are the best available and usually still roughly true) but say how old it is,
# so nobody quotes them as current. Past IGNORE, refuse to ground on it at all
# and say why: at that range the answer is not stale, it is wrong.
_FRESH_HOURS = 24.0
_IGNORE_AFTER_HOURS = 24.0 * 7


def analysis_age_hours(doc: dict[str, Any] | None) -> float | None:
    """Age of a stored analysis in hours, or None when undatable.

    Documents are written with datetime.now(timezone.utc).isoformat(), so the
    parse is total in practice; a document that predates that convention (or
    was written by hand) returns None and is treated as ageless rather than as
    infinitely old — refusing to answer because of a missing field would be a
    worse failure than the one this guards against.
    """
    if not doc:
        return None
    raw = str(doc.get("timestamp") or "").strip()
    if not raw:
        return None
    try:
        stamp = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - stamp).total_seconds() / 3600.0


def describe_age(hours: float | None) -> str:
    """"6 days" / "3 hours" / "" — for putting an age in a sentence."""
    if hours is None:
        return ""
    if hours < 1:
        return "under an hour"
    if hours < 48:
        n = int(round(hours))
        return f"{n} hour{'s' if n != 1 else ''}"
    n = int(hours // 24)
    return f"{n} day{'s' if n != 1 else ''}"


def is_stale(doc: dict[str, Any] | None) -> bool:
    """True when *doc* is old enough that its age should be stated."""
    age = analysis_age_hours(doc)
    return age is not None and age >= _FRESH_HOURS


def resolve_module(
    message: str, module_context: str = ""
) -> tuple[ModuleInfo | None, str]:
    """Return (module, source) for this turn.

    source: "message" | "context" | "" — surfaced in logs and used by the
    caller to decide how strongly to trust the ambient grounding.
    """
    lowered = (message or "").lower()
    # Longest alias first, so "lod auditor" wins over "lod".
    for alias, module in module_registry.ALIASES:
        if alias in lowered:
            return module, "message"

    ambient = module_registry.get(module_context)
    if ambient is not None:
        return ambient, "context"

    return None, ""


async def latest_analysis(
    module: ModuleInfo, skip_id: str = "", max_age_hours: float | None = None
) -> dict[str, Any] | None:
    """The most recent stored scan for *module*, or None.

    This is what makes "how is the Code Validator doing?" answerable without
    that module's panel being open — the previous implementation could only
    read the one analysis id the client happened to send.

    `skip_id` excludes an analysis by id, which is how the caller asks for the
    one BEFORE the current scan to compare against.

    `max_age_hours` discards a scan older than that. Left None by default
    because the trend comparison in summarize_module genuinely wants the
    previous scan however old it is — "since last time" is a claim about the
    last time, not about the last day. Only the ambient-grounding path bounds
    it (see resolve_analysis).
    """
    if not module.report_types:
        return None

    query: dict[str, Any] = {"report_type": {"$in": list(module.report_types)}}
    if skip_id:
        query["analysis_id"] = {"$ne": skip_id}

    try:
        from api.database import analysis_results

        # Sorting on the ISO-8601 timestamp string is correct precisely
        # because it is ISO-8601: lexical order is chronological order. The
        # documents are written with datetime.now(timezone.utc).isoformat(),
        # so they are uniform.
        cursor = analysis_results.find(query).sort("timestamp", -1).limit(1)
        docs = await cursor.to_list(length=1)
    except Exception:  # noqa: BLE001 — Mongo is best-effort everywhere here
        return None
    if not docs:
        return None

    doc = docs[0]
    if max_age_hours is not None:
        age = analysis_age_hours(doc)
        if age is not None and age > max_age_hours:
            return None
    return doc


async def resolve_analysis(
    module: ModuleInfo | None, context_ref: str, module_source: str
) -> tuple[dict[str, Any] | None, ModuleInfo | None]:
    """Pick the analysis this turn should be grounded in.

    Returns (analysis_doc, module) — the module is returned too because a bare
    `context_ref` with no module named anywhere identifies its own module via
    its report_type, and the caller wants to say which one it answered about.

    The rule: a context_ref is honoured unless the user named a DIFFERENT
    module. Naming one is an explicit change of subject and must beat the
    ambient panel; not naming one means "the thing I'm looking at", which is
    what the context_ref is.

    An explicit context_ref is honoured at any age — the client is pointing at
    a specific analysis and is entitled to an answer about it. The unbounded
    fallback below is the one that needed a limit: nobody chose that scan, it
    is simply the newest one in the database, and past a week that is not
    "what the user is looking at" by any reading.
    """
    doc = None
    if context_ref:
        try:
            from api.database import analysis_results

            doc = await analysis_results.find_one({"analysis_id": context_ref})
        except Exception:  # noqa: BLE001
            doc = None

    if doc is not None:
        doc_module = module_registry.for_report_type(str(doc.get("report_type", "")))
        # The user named a module and it is not this document's — the ambient
        # grounding is about something else entirely, so drop it.
        named_another = (
            module is not None
            and module_source == "message"
            and doc_module is not module
        )
        if named_another:
            doc = None
        else:
            return doc, (doc_module or module)

    if module is None:
        return None, None
    return (
        await latest_analysis(module, max_age_hours=_IGNORE_AFTER_HOURS),
        module,
    )
