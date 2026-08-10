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

import json
import logging
from dataclasses import dataclass
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
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
    # Impact Simulator inputs: which Predictive report to replay and which
    # of its items the user ticked.
    report_id: str = ""
    selected_item_ids: list[str] = Field(default_factory=list)
    platform_profile: str = ""
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
    # The grounding this turn resolved to — echoed so a panel can show what
    # "this" meant, and so a reopened thread restores its own context.
    rule_id: str = ""
    asset_path: str = ""


class AssistantMessageResponse(BaseModel):
    error: str = ""
    conversation_id: str = ""
    tier: str = "free"
    intent: str = ""
    # True when the intent was inherited from the previous turn rather than
    # classified — lets a panel show "following up on …" instead of making
    # the user wonder why a two-word question was understood.
    continued: bool = False
    reply: AssistantTurn = Field(default_factory=AssistantTurn)
    # What this turn left awaiting a yes or no, if anything. Empty on every
    # other turn. The reply text asks for confirmation, so a client needs
    # the id to offer it as a button — without these the only confirmation
    # route was the Memory/Rules panel, and the assistant's own suggestion
    # to confirm "here" was unactionable.
    pending_fact_id: str = ""
    pending_rule_id: str = ""
    # The stored text, so a card can show WHAT is being confirmed.
    pending_subject: str = ""


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


def _resolve_intent(
    requested: str, message: str, prior_intent: str = ""
) -> tuple[str, bool]:
    """Resolve the intent for this turn; returns (intent, continued).

    Three sources, in order:
      1. The UI declared it — a button knows its own intent.
      2. Deterministic continuation: a short anaphoric message ("and why?")
         inherits the previous turn's intent. Python decides this, not the
         model, and it can only ever reuse a target the user already had on
         screen.
      3. The closed router (grammar-constrained LLM, else keyword table).
    """
    candidate = (requested or "").strip().lower()
    if candidate in ALL_INTENTS:
        return candidate, False

    from modules.assistant.conversation_context import is_continuation

    if prior_intent and is_continuation(message):
        logger.info("router: intent=%s source=continuation", prior_intent)
        return prior_intent, True

    from modules.assistant.intent_router import classify

    intent, source = classify(message)
    logger.info("router: intent=%s source=%s", intent, source)
    return intent, False


async def _dispatch(
    intent: str,
    payload: AssistantMessageRequest,
    history: str = "",
    pending: dict | None = None,
    answer: str = "",
) -> dict:
    """Run the deterministic action for *intent*; returns its whole result.

    Intents without a shipped action acknowledge honestly instead of
    pretending — actions land one per milestone under
    modules/assistant/actions/.

    ``history`` is the rendered thread so far. Actions that narrate use it
    so a follow-up reads as a continuation; actions that answer from a
    table ignore it.

    Returns the action's dict rather than just its "reply". The proposing
    actions put the id of what they created in there (fact_id, rule_id) and
    it used to be dropped on this line — so the fact the reply told the user
    to confirm was unreachable: the response model had nowhere to carry it
    and the turn recorded nothing about it. Both the confirm card in the
    client and "sí" in the next turn need that id to exist outside the Core.
    """
    from modules.assistant.actions import ACTIONS

    action = ACTIONS.get(intent)
    if action is not None:
        return await action(
            {
                "message": payload.message,
                "history": history,
                "context_ref": payload.context_ref,
                "rule_id": payload.rule_id,
                "asset_path": payload.asset_path,
                "finding": payload.finding,
                "engine": payload.engine,
                "studio_id": payload.studio_id,
                "project_id": payload.project_id,
                "module_context": payload.module_context,
                "conversation_id": payload.conversation_id,
                "report_id": payload.report_id,
                "selected_item_ids": payload.selected_item_ids,
                "platform_profile": payload.platform_profile,
                "pending": pending or {},
                "answer": answer,
            }
        )

    if intent == "general_help":
        return {"reply": _HELP_TEXT}
    return {"reply": _NOT_READY_TEXT}


# ── Endpoints ─────────────────────────────────────────────────────────────────


@dataclass
class _TurnPlan:
    """Everything both the blocking and the streaming endpoint need.

    Built once by _plan_turn so the two paths cannot drift on tier gating,
    continuation handling or history assembly — the differences between
    them start after this point and are purely about delivery.
    """

    tier: str
    persist: bool
    intent: str
    continued: bool
    conversation_id: str
    history: str
    payload: AssistantMessageRequest
    # Set only when this turn answers a proposal the previous one left open.
    pending: dict | None = None
    answer: str = ""


async def _plan_turn(payload: AssistantMessageRequest) -> _TurnPlan:
    """Resolve tier, intent, conversation and history. Raises 403/404."""
    tier, _reason = await resolve_tier_detailed(payload.api_key)
    caps = assistant_capabilities(tier)
    persist = caps["memory"] != "none"

    from modules.assistant import conversation_context, memory_store

    existing: dict | None = None
    conversation_id = payload.conversation_id.strip()
    if conversation_id:
        existing = await get_conversation(conversation_id)
        if existing is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "Conversation not found or expired."},
            )

    # A yes-or-no answering the proposal the previous turn left open is
    # resolved here, BEFORE the router — the previous turn asked a closed
    # question and this message answers it, so there is nothing to classify.
    #
    # This is the fix for "I confirm a fact and get a summary of my last
    # scan": "sí" is not a continuation (its opener list never had it), so
    # it reached classify(), where the GBNF grammar forces one of the
    # routable intents — and whichever came back inherited the previous
    # turn's context_ref and answered about the analysis instead.
    from modules.assistant import pending as pending_mod

    proposal = pending_mod.pending_proposal(existing)
    answer = pending_mod.read_affirmation(payload.message) if proposal else None

    prior = conversation_context.last_grounding(existing)
    if proposal and answer:
        intent, continued = "confirm_pending", True
        logger.info(
            "router: intent=confirm_pending source=pending kind=%s answer=%s",
            proposal.get("kind"),
            answer,
        )
    else:
        proposal, answer = None, None
        intent, continued = _resolve_intent(
            payload.intent, payload.message, prior["intent"]
        )

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

    # Inherit what the user was already looking at, field by field, only
    # where this request didn't say. An explicit value always wins.
    inherited = {
        field: prior[field]
        for field in ("context_ref", "rule_id", "asset_path")
        if not getattr(payload, field).strip() and prior[field]
    }
    if inherited:
        payload = payload.model_copy(update=inherited)
        logger.info("continuation: inherited %s", sorted(inherited))

    if not conversation_id:
        conversation_id = await start_conversation(
            payload.studio_id,
            payload.project_id,
            payload.module_context,
            persist=persist,
        )

    # Built from the conversation as it stood BEFORE this turn's message was
    # appended — the question being answered is passed separately, and
    # showing it twice would only invite the model to answer the older copy.
    history = conversation_context.build_history(
        existing, await memory_store.latest_summary(conversation_id)
    )

    return _TurnPlan(
        tier=tier,
        persist=persist,
        intent=intent,
        continued=continued,
        conversation_id=conversation_id,
        history=history,
        payload=payload,
        pending=proposal,
        answer=answer or "",
    )


async def _record_user_turn(plan: _TurnPlan) -> None:
    await append_turn(
        plan.conversation_id,
        "user",
        plan.payload.message,
        intent=plan.intent,
        context_ref=plan.payload.context_ref,
        rule_id=plan.payload.rule_id,
        asset_path=plan.payload.asset_path,
    )


def _proposal_of(result: dict) -> tuple[str, str, str]:
    """(fact_id, rule_id, subject) this action left awaiting a yes or no.

    A proposal is armed ONLY when the action declares the pending status
    itself — "proposed" for a fact, "draft" for a rule. Reading the bare id
    would re-arm the question every time it appears: confirm_pending echoes
    the id it just committed, and explain_finding returns a `rule_id` that
    is a finding's rule (CS001), nothing to confirm at all.
    """
    fact_id = (
        str(result.get("fact_id") or "")
        if result.get("fact_status") == "proposed"
        else ""
    )
    rule_id = (
        str(result.get("rule_id") or "")
        if result.get("rule_status") == "draft"
        else ""
    )
    subject = str(result.get("proposed_subject") or "")
    return fact_id, rule_id, subject


async def _record_assistant_turn(
    plan: _TurnPlan, reply_text: str, result: dict | None = None
) -> dict | None:
    """Record the assistant's turn, carrying any proposal it just made.

    ``result`` is the action's full dict. When it created something awaiting
    confirmation, its id lands on the turn — that is what lets the NEXT turn
    resolve a bare "sí" against it, and what makes the pending state survive
    reopening the thread.
    """
    fact_id, rule_id, subject = _proposal_of(result or {})

    turn = await append_turn(
        plan.conversation_id,
        "assistant",
        reply_text,
        intent=plan.intent,
        context_ref=plan.payload.context_ref,
        rule_id=plan.payload.rule_id,
        asset_path=plan.payload.asset_path,
        proposed_fact_id=fact_id,
        proposed_rule_id=rule_id,
        proposed_subject=subject,
    )
    # Fold old turns into a summary once the thread grows long. Best-effort;
    # no-op below the threshold or when the tier's memory doesn't persist.
    if turn is not None and plan.persist:
        from modules.assistant import memory_store

        try:
            await memory_store.compact_conversation(
                plan.conversation_id,
                plan.payload.studio_id,
                plan.payload.project_id,
            )
        except Exception:  # noqa: BLE001 — compaction must never fail a turn
            logger.exception("conversation compaction failed")
    return turn


@router.post("/assistant/message", response_model=AssistantMessageResponse)
async def assistant_message(
    payload: AssistantMessageRequest,
) -> AssistantMessageResponse:
    plan = await _plan_turn(payload)
    await _record_user_turn(plan)

    result = await _dispatch(
        plan.intent, plan.payload, plan.history, plan.pending, plan.answer
    )
    reply_text = str(result.get("reply") or "")

    turn = await _record_assistant_turn(plan, reply_text, result)
    if turn is None:  # conversation evaporated between the two writes
        raise HTTPException(
            status_code=404,
            detail={"error": "Conversation not found or expired."},
        )

    logger.info(
        "/assistant/message: tier=%s intent=%s conv=%s continued=%s",
        plan.tier,
        plan.intent,
        plan.conversation_id,
        plan.continued,
    )
    fact_id, rule_id, subject = _proposal_of(result)
    return AssistantMessageResponse(
        conversation_id=plan.conversation_id,
        tier=plan.tier,
        intent=plan.intent,
        continued=plan.continued,
        reply=AssistantTurn(**turn),
        pending_fact_id=fact_id,
        pending_rule_id=rule_id,
        pending_subject=subject,
    )


# ── Streaming (SSE) ───────────────────────────────────────────────────────────
#
# Same event schema as /agent/explain/stream, so the plugin's existing SSE
# parser works unchanged: `data: {json}` lines carrying {"chunk": …},
# {"error": …} and a terminal {"done": true, "full_text": …}. Assistant
# turns add a {"meta": …} event up front and extra keys on the done event;
# a parser that ignores unknown keys behaves correctly without changes.


def _sse(payload: dict) -> str:
    return "data: " + json.dumps(payload) + "\n\n"


async def _message_stream_events(
    plan: _TurnPlan,
) -> AsyncIterator[str]:
    """Body for POST /assistant/message/stream.

    Only actions that narrate at length stream token-by-token. The rest
    answer from a table in microseconds, so they emit their reply as one
    chunk — pretending to type it out would be theatre, not feedback.
    """
    from modules.assistant.stream_bridge import aiter_in_thread

    yield _sse(
        {
            "meta": {
                "conversation_id": plan.conversation_id,
                "intent": plan.intent,
                "tier": plan.tier,
                "continued": plan.continued,
            }
        }
    )

    parts: list[str] = []
    failed = False

    if plan.intent == "explain_finding":
        from modules.assistant.actions import explain_finding

        prepared = await explain_finding.prepare(
            {
                "finding": plan.payload.finding,
                "context_ref": plan.payload.context_ref,
                "rule_id": plan.payload.rule_id,
                "asset_path": plan.payload.asset_path,
            }
        )
        if "error" in prepared:
            # A resolvable target is a precondition, not a streaming
            # failure: say so as normal text and close cleanly.
            parts.append(prepared["error"])
            yield _sse({"chunk": prepared["error"]})
        else:
            finding = prepared["finding"]
            try:
                async for chunk in aiter_in_thread(
                    lambda: explain_finding.stream_text(
                        finding, plan.payload.message, plan.history
                    )
                ):
                    parts.append(chunk)
                    yield _sse({"chunk": chunk})
            except Exception as exc:  # noqa: BLE001
                failed = True
                logger.exception("assistant stream failed — degrading")
                # Degrade to the grounded deterministic text rather than
                # leaving the panel with a half sentence and an error.
                fallback = explain_finding.deterministic_reply(finding)
                parts = [fallback]
                yield _sse({"chunk": fallback})
                yield _sse({"error": f"{type(exc).__name__}: {exc}"})

    # Every other intent answers from a table in microseconds — one chunk,
    # and its full result kept so the done event can carry any proposal.
    result: dict = {}
    if plan.intent != "explain_finding":
        result = await _dispatch(
            plan.intent, plan.payload, plan.history, plan.pending, plan.answer
        )
        text = str(result.get("reply") or "")
        parts.append(text)
        yield _sse({"chunk": text})

    full_text = "".join(parts).strip()
    turn = await _record_assistant_turn(plan, full_text, result)

    fact_id, rule_id, subject = _proposal_of(result)
    yield _sse(
        {
            "done": True,
            "full_text": full_text,
            "cached": False,
            "source": "assistant",
            "degraded": failed,
            "conversation_id": plan.conversation_id,
            "intent": plan.intent,
            "continued": plan.continued,
            "turn_id": (turn or {}).get("turn_id", ""),
            "pending_fact_id": fact_id,
            "pending_rule_id": rule_id,
            "pending_subject": subject,
        }
    )


@router.post("/assistant/message/stream")
async def assistant_message_stream(
    payload: AssistantMessageRequest,
) -> StreamingResponse:
    """One conversation turn, delivered as it is generated.

    Identical inputs, gating and semantics to POST /assistant/message —
    _plan_turn is shared — so a client may choose per call. Tier 403s and
    unknown-conversation 404s are raised BEFORE the stream opens, as real
    HTTP status codes rather than an error event.
    """
    plan = await _plan_turn(payload)
    await _record_user_turn(plan)
    return StreamingResponse(
        _message_stream_events(plan),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
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


class DecisionCheckRequest(BaseModel):
    api_key: str = ""
    studio_id: str = ""
    project_id: str = ""
    # Either hand over the findings, or a context_ref to load them from.
    findings: list[dict] = Field(default_factory=list)
    context_ref: str = ""


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


# ── Studio rules (M3) ─────────────────────────────────────────────────────────
#
# Tier gate follows the capability table: "all" (Studio: templates + LLM)
# or "llm_evaluated" (Indie: Tier B only). None -> 403.


async def _require_rules(api_key: str, *, need_template: bool = False) -> str:
    tier, _ = await resolve_tier_detailed(api_key)
    allowed = assistant_capabilities(tier)["studio_rules"]
    if allowed is None or (need_template and allowed != "all"):
        raise HTTPException(
            status_code=403,
            detail={
                "error": (
                    "Deterministic template rules require a Studio plan."
                    if need_template
                    else "Persistent studio rules require an Indie plan or higher."
                ),
                "current_tier": tier,
            },
        )
    return tier


class RuleConfirmRequest(BaseModel):
    api_key: str = ""
    rule_id: str
    accept: bool  # True -> active+confirmed; False -> deprecated


@router.post("/assistant/decisions/check")
async def assistant_decisions_check(payload: DecisionCheckRequest):
    """Contradictions between a studio's confirmed memory and a scan.

    Called by the client after a scan completes. The trigger is
    deterministic Python (decision_monitor); the model is not consulted,
    and only confirmed facts participate — a proposed fact can never
    produce a proactive nudge.
    """
    from modules.assistant import decision_monitor

    await _require_full_memory(payload.api_key)

    findings = payload.findings
    if not findings and payload.context_ref:
        try:
            from api.database import analysis_results

            doc = await analysis_results.find_one(
                {"analysis_id": payload.context_ref}
            )
            findings = [
                i for i in (doc or {}).get("issues", []) if isinstance(i, dict)
            ]
        except Exception:  # noqa: BLE001
            findings = []

    pairs = await decision_monitor.check_scan(
        payload.studio_id, payload.project_id, findings
    )
    return {"contradictions": pairs}


@router.get("/assistant/rules")
async def assistant_rules(
    api_key: str = "", studio_id: str = "", project_id: str = ""
):
    from modules.assistant import rule_store

    await _require_rules(api_key)
    rules = await rule_store.list_rules(
        studio_id, project_id, statuses=("draft", "active")
    )
    return {"rules": rules}


@router.post("/assistant/rules/confirm")
async def assistant_rules_confirm(payload: RuleConfirmRequest):
    from modules.assistant import rule_store

    tier = await _require_rules(payload.api_key)
    if payload.accept:
        # Activating a template rule needs the full Studio capability.
        current = await rule_store.set_rule_status(payload.rule_id)
        if current is None:
            raise HTTPException(
                status_code=404, detail={"error": "Rule not found."}
            )
        if current.get("tier") == "template":
            await _require_rules(payload.api_key, need_template=True)
        rule = await rule_store.set_rule_status(
            payload.rule_id, status="active", confirmed=True
        )
    else:
        rule = await rule_store.set_rule_status(
            payload.rule_id, status="deprecated", confirmed=False
        )
    if rule is None:
        raise HTTPException(status_code=404, detail={"error": "Rule not found."})
    return {"rule": rule, "tier": tier}
