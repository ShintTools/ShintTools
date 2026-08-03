# core/modules/assistant/actions/recall_fact.py
#
# "What did we decide about lightmaps?"
#
# Grounds exclusively on CONFIRMED facts — a proposed fact is invisible
# here by design (memory_store.confirmed_facts is the only view read).
# Retrieval is keyword overlap over the small per-studio corpus; the
# documented threshold for revisiting this with local vector search is
# ~500 active facts per project.

from __future__ import annotations

import re
from typing import Any

from .. import memory_store

_NOTHING_YET = (
    "I don't have any confirmed team facts yet. Tell me one with "
    "'remember that …' and confirm it, and I'll keep it."
)

_NO_MATCH = (
    "Nothing in the confirmed team memory matches that. You can see "
    "everything I know in the Memory panel."
)

_STOPWORDS = frozenset(
    "the a an of on in for to and or que de la el los las un una y o "
    "sobre con at is are was what did we our nuestro nuestra".split()
)


def _terms(text: str) -> set[str]:
    return {
        w
        for w in re.findall(r"[a-záéíóúñü0-9_]+", (text or "").lower())
        if len(w) > 2 and w not in _STOPWORDS
    }


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    studio_id = str(payload.get("studio_id") or "")
    project_id = str(payload.get("project_id") or "")

    facts = await memory_store.confirmed_facts(studio_id, project_id)
    if not facts:
        return {"reply": _NOTHING_YET, "facts": []}

    query_terms = _terms(payload.get("message", ""))
    scored = []
    for fact in facts:
        overlap = len(query_terms & _terms(fact.get("value", "")))
        if overlap:
            scored.append((overlap, fact))
    scored.sort(key=lambda pair: (-pair[0], -pair[1]["created_at"]))

    matched = [fact for _, fact in scored[:5]]
    if not matched:
        return {"reply": _NO_MATCH, "facts": []}

    lines = [f'- {fact["value"]}' for fact in matched]
    return {
        "reply": "Here's what the team decided:\n" + "\n".join(lines),
        "facts": [fact["fact_id"] for fact in matched],
    }
