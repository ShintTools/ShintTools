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
    # is explain_finding). Empty = M1's router will classify; in M0 empty
    # falls back to general_help.
    intent: str = ""
    # What the user is looking at: an analysis_id from a finished scan.
    # Resolved server-side against analysis_results — the assistant never
    # re-collects project data on its own.
    context_ref: str = ""
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


def _resolve_intent(requested: str) -> str:
    """M0: trust the UI's declared intent; empty/unknown -> general_help.

    M1 replaces the fallback branch with the grammar-constrained LLM router.
    """
    candidate = (requested or "").strip().lower()
    return candidate if candidate in ALL_INTENTS else "general_help"


def _dispatch(intent: str) -> str:
    """Run the deterministic action for *intent* and return the reply text.

    M0 ships only general_help; every other intent acknowledges honestly
    instead of pretending. Actions land one per milestone under
    modules/assistant/actions/ and replace branches here.
    """
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
    intent = _resolve_intent(payload.intent)

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

    reply_text = _dispatch(intent)

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
