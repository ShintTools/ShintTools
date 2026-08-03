# core/modules/assistant/actions/remember_fact.py
#
# "Remember that we use Nanite on all characters."
#
# The action PROPOSES — it never confirms. The reply tells the user the
# fact is pending their confirmation, and the payload carries the fact_id
# so the UI can render the confirm/reject card in the thread. Muted
# projects (NDA silent mode) refuse politely instead of remembering.

from __future__ import annotations

from typing import Any

from .. import fact_extractor, memory_store

_EMPTY = (
    "Tell me what to remember — e.g. 'remember that all character meshes "
    "use Nanite'."
)

_MUTED = (
    "Memory is muted for this project, so I won't store that. You can "
    "re-enable it from the assistant's Memory panel."
)


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    statement = fact_extractor.extract_statement(payload.get("message", ""))
    if not statement:
        return {"reply": _EMPTY, "fact_id": ""}

    studio_id = str(payload.get("studio_id") or "")
    project_id = str(payload.get("project_id") or "")

    if await memory_store.is_memory_muted(studio_id, project_id):
        return {"reply": _MUTED, "fact_id": ""}

    fact = await memory_store.propose_fact(
        studio_id,
        project_id,
        fact_extractor.classify_fact_type(payload.get("message", "")),
        statement,
        {
            "conversation_id": str(payload.get("conversation_id") or ""),
            "turn_id": "",
            "module": str(payload.get("module_context") or ""),
        },
    )
    return {
        "reply": (
            f'Noted: "{statement}". I\'ll only use this once you confirm '
            "it — check the card in this thread or the Memory panel."
        ),
        "fact_id": fact["fact_id"],
        "fact_status": "proposed",
    }
