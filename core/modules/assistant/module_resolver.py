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

from typing import Any

from . import module_registry
from .module_registry import ModuleInfo


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
    module: ModuleInfo, skip_id: str = ""
) -> dict[str, Any] | None:
    """The most recent stored scan for *module*, or None.

    This is what makes "how is the Code Validator doing?" answerable without
    that module's panel being open — the previous implementation could only
    read the one analysis id the client happened to send.

    `skip_id` excludes an analysis by id, which is how the caller asks for the
    one BEFORE the current scan to compare against.
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
    return docs[0] if docs else None


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
    return await latest_analysis(module), module
