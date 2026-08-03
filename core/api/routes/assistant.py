# core/api/routes/assistant.py
#
# Native AI assistant — conversational surface over the deterministic Core.
#
# Endpoints:
#   POST /assistant/message               — one conversation turn
#   GET  /assistant/conversations/{id}    — full conversation (history)
#   GET  /assistant/capabilities          — what the caller's tier may do
#
# Registered for EVERY edition and every tier (unlike /agent/* which is
# paid-image only): the assistant serves Free too, degraded per the
# capability table in modules/assistant/tiers.py. Intents outside the
# caller's tier return 403 per-action — never a blanket 403 on the route.
#
# M0 scope: deterministic dispatch only. The intent comes from the request
# (the UI knows which button/context produced the message); the LLM router
# for free-text classification arrives in M1 and slots in where
# `_resolve_intent` is today.

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.database import resolve_tier_detailed
from modules.assistant import (
    append_turn,
    get_conversation,
    start_conversation,
)
from modules.assistant.tiers import (
    ALL_INTENTS,
    allowed_intents_for,
    assistant_capabilities,
)

logger = logging.getLogger("shinttools.assistant")

router = APIRouter()


# ── Request / response models ─────────────────────────────────────────────────


class AssistantMessageRequest(BaseModel):
    api_key: str = ""
    message: str = Field(..., min_length=1, max_length=8000)
    # Omitted on the first turn; the response returns the id to continue.
    conversation_id: str = ""
    # The intent, when the UI already knows it (an "Explain" button knows it
    # is explain_finding). Empty -> the closed-menu router classifies the
    # free text (grammar-constrained LLM when loaded, keyword table
    # otherwise — never an open-ended guess).
    intent: str = ""
    # What the user is looking at: an analysis_id from a finished scan.
    # Resolved server-side against analysis_results — the assistant never
    # re-collects project data on its own.
    context_ref: str = ""
    # Selectors within the referenced analysis (which row is "this one").
    rule_id: str = ""
    asset_path: str = ""
    # The finding itself, inline — the UI has the row on screen. Same shape
    # /agent/explain receives today; skips the context_ref lookup.
    finding: dict = Field(default_factory=dict)
    # Grounding metadata the client already has on screen.
    studio_id: str = ""
    project_id: str = ""
    module_context: str = ""  # "lod_audit" | "code_validator" | ...
    engine: str = ""  # "unreal" | "unity"


class AssistantTurn(BaseModel):
    turn_id: str = ""
    role: str = ""
    intent: str = ""
    raw_text: str = ""
    context_ref: str = ""


class AssistantMessageResponse(BaseModel):
    error: str = ""
    conversation_id: str = ""
    tier: str = "free"
    intent: str = ""
    reply: AssistantTurn = Field(default_factory=AssistantTurn)


# ── Deterministic M0 dispatch ─────────────────────────────────────────────────

_HELP_TEXT = (
    "I'm the ShintTools assistant. I answer questions about your scans — "
    "explain a finding, summarize a module's results, or tell you why a "
    "rule exists — grounded in the analysis you already ran, never in "
    "guesses. Run a scan in any module and ask me about what it found."
)

_NOT_READY_TEXT = (
    "That capability isn't wired up yet — it's on the roadmap. For now I "
    "can help you understand findings from your latest scan."
)


def _resolve_intent(requested: str, message: str) -> str:
    """The UI's declared intent wins; free text goes through the closed
    router (grammar-constrained LLM when loaded, keyword table otherwise)."""
    candidate = (requested or "").strip().lower()
    if candidate in ALL_INTENTS:
        return candidate
    from modules.assistant.intent_router import classify

    intent, source = classify(message)
    logger.info("router: intent=%s source=%s", intent, source)
    return intent


async def _dispatch(intent: str, payload: AssistantMessageRequest) -> str:
    """Run the deterministic action for *intent* and return the reply text.

    Intents without a shipped action acknowledge honestly instead of
    pretending — actions land one per milestone under
    modules/assistant/actions/.
    """
    from modules.assistant.actions import ACTIONS

    action = ACTIONS.get(intent)
    if action is not None:
        result = await action(
            {
                "message": payload.message,
                "context_ref": payload.context_ref,
                "rule_id": payload.rule_id,
                "asset_path": payload.asset_path,
                "finding": payload.finding,
                "engine": payload.engine,
                "studio_id": payload.studio_id,
                "project_id": payload.project_id,
                "module_context": payload.module_context,
                "conversation_id": payload.conversation_id,
            }
        )
        return result["reply"]

    if intent == "general_help":
        return _HELP_TEXT
    return _NOT_READY_TEXT


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/assistant/message", response_model=AssistantMessageResponse)
async def assistant_message(
    payload: AssistantMessageRequest,
) -> AssistantMessageResponse:
    tier, reason = await resolve_tier_detailed(payload.api_key)
    caps = assistant_capabilities(tier)
    intent = _resolve_intent(payload.intent, payload.message)

    if intent not in allowed_intents_for(tier):
        # Per-action gate: the endpoint always answers, the capability
        # doesn't. Mirrors the shape of tier_guard's 403 detail.
        raise HTTPException(
            status_code=403,
            detail={
                "error": f"The '{intent}' capability requires a higher plan.",
                "current_tier": tier,
                "allowed_intents": sorted(allowed_intents_for(tier)),
            },
        )

    persist = caps["memory"] != "none"

    conversation_id = payload.conversation_id.strip()
    if conversation_id:
        existing = await get_conversation(conversation_id)
        if existing is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "Conversation not found or expired."},
            )
    else:
        conversation_id = await start_conversation(
            payload.studio_id,
            payload.project_id,
            payload.module_context,
            persist=persist,
        )

    await append_turn(
        conversation_id,
        "user",
        payload.message,
        intent=intent,
        context_ref=payload.context_ref,
    )

    reply_text = await _dispatch(intent, payload)

    turn = await append_turn(
        conversation_id,
        "assistant",
        reply_text,
        intent=intent,
        context_ref=payload.context_ref,
    )
    if turn is None:  # conversation evaporated between the two writes
        raise HTTPException(
            status_code=404,
            detail={"error": "Conversation not found or expired."},
        )

    # Fold old turns into a summary once the thread grows long. Best-effort
    # and non-blocking for the reply; no-op below the threshold or when the
    # tier's memory doesn't persist.
    if persist:
        from modules.assistant import memory_store

        try:
            await memory_store.compact_conversation(
                conversation_id, payload.studio_id, payload.project_id
            )
        except Exception:  # noqa: BLE001 — compaction must never fail a turn
            logger.exception("conversation compaction failed")

    logger.info(
        "/assistant/message: tier=%s intent=%s conv=%s reason=%s",
        tier,
        intent,
        conversation_id,
        reason or "-",
    )
    return AssistantMessageResponse(
        conversation_id=conversation_id,
        tier=tier,
        intent=intent,
        reply=AssistantTurn(**turn),
    )


@router.get("/assistant/conversations/{conversation_id}")
async def assistant_conversation(conversation_id: str):
    doc = await get_conversation(conversation_id)
    if doc is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "Conversation not found or expired."},
        )
    return doc


@router.get("/assistant/capabilities")
async def assistant_caps(api_key: str = ""):
    tier, _ = await resolve_tier_detailed(api_key)
    caps = assistant_capabilities(tier)
    return {
        "tier": tier,
        "intents": sorted(caps["intents"]),
        "memory": caps["memory"],
        "model_profile": caps["model_profile"],
        "studio_rules": caps["studio_rules"],
    }


# ── Memory (M2) ───────────────────────────────────────────────────────────────
#
# Facts are Studio-tier by capability table (memory="full"). The gate here
# mirrors the per-intent one: a specific 403, never a hidden feature.


async def _require_full_memory(api_key: str) -> str:
    tier, _ = await resolve_tier_detailed(api_key)
    if assistant_capabilities(tier)["memory"] != "full":
        raise HTTPException(
            status_code=403,
            detail={
                "error": "Persistent team memory requires a Studio plan.",
                "current_tier": tier,
            },
        )
    return tier


class MemoryConfirmRequest(BaseModel):
    api_key: str = ""
    fact_id: str
    accept: bool  # True -> confirmed; False -> retracted


class MemoryMuteRequest(BaseModel):
    api_key: str = ""
    studio_id: str = ""
    project_id: str = ""
    muted: bool = True


@router.get("/assistant/memory")
async def assistant_memory(
    api_key: str = "", studio_id: str = "", project_id: str = ""
):
    from modules.assistant import memory_store

    await _require_full_memory(api_key)
    facts = await memory_store.list_facts(studio_id, project_id)
    muted = await memory_store.is_memory_muted(studio_id, project_id)
    return {"facts": facts, "memory_muted": muted}


@router.post("/assistant/memory/confirm")
async def assistant_memory_confirm(payload: MemoryConfirmRequest):
    from modules.assistant import memory_store

    await _require_full_memory(payload.api_key)
    status = "confirmed" if payload.accept else "retracted"
    fact = await memory_store.set_fact_status(payload.fact_id, status)
    if fact is None:
        raise HTTPException(
            status_code=404, detail={"error": "Fact not found."}
        )
    return {"fact": fact}


@router.post("/assistant/memory/mute")
async def assistant_memory_mute(payload: MemoryMuteRequest):
    from modules.assistant import memory_store

    await _require_full_memory(payload.api_key)
    await memory_store.set_memory_muted(
        payload.studio_id, payload.project_id, payload.muted
    )
    return {"studio_id": payload.studio_id, "project_id": payload.project_id,
            "memory_muted": payload.muted}


@router.delete("/assistant/memory/project")
async def assistant_memory_purge(
    api_key: str = "", studio_id: str = "", project_id: str = ""
):
    """Hard-delete a project's facts and summaries (NDA close-out)."""
    from modules.assistant import memory_store

    await _require_full_memory(api_key)
    if not project_id:
        raise HTTPException(
            status_code=422,
            detail={"error": "project_id is required for a purge."},
        )
    removed = await memory_store.purge_project(studio_id, project_id)
    return {"removed": removed}
