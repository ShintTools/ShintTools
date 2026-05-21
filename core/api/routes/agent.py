# core/api/routes/agent.py
#
# Agent layer — AI-assisted fix planning and per-issue LLM explanations.
#
# Endpoints:
#   POST /agent/plan            — given a validation report, return a
#                                 prioritized fix plan with per-step
#                                 rationale (rule-based, deterministic
#                                 — no LLM).
#   POST /agent/explain         — single-issue customer-facing
#                                 explanation. Synchronous: client
#                                 waits for the full text. Cached by
#                                 sha1(model_id, prompt) in MongoDB.
#   POST /agent/explain/stream  — same input as /agent/explain but
#                                 returns the explanation as a stream
#                                 of Server-Sent Events so the plugin
#                                 can show tokens as they arrive
#                                 instead of waiting 20-40 s on a
#                                 cold cache miss.
#
# Tier gating: all explain endpoints are Indie-tier features. Calls
# from a free key (or a missing key) return 403.

from __future__ import annotations

import json
from typing import AsyncIterator

from api.database import resolve_tier
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/agent", tags=["agent"])


# ── Request / response shapes ───────────────────────────────────────────────


class _PlanIssue(BaseModel):
    """One issue from a `/validate/*` response. We don't reuse the validate
    module's models so the agent can be invoked stand-alone with whatever
    JSON the plugin already has cached client-side."""

    rule_id: str = Field(..., description="Rule identifier, e.g. 'CS001'")
    rule_name: str = Field(
        default="",
        description=(
            "Humanized title for the rule (e.g. 'GetWorld without"
            " null-check'). The LLM and the plugin use this in"
            " customer-facing copy; rule_id is internal only."
        ),
    )
    rule_explanation: str = Field(
        default="",
        description=(
            "Authoritative explanation extracted from the detector's"
            " docstring (first paragraph). The LLM grounds its"
            " answers in this text instead of guessing UE5 semantics."
        ),
    )
    severity: str = Field(..., description="error | warning | info")
    category: str = Field(
        default="",
        description=(
            "security | performance |"
            " best_practices | maintainability"
            " | naming | …"
        ),
    )
    file_path: str = Field(default="")
    line: int = Field(default=0, ge=0)
    message: str = Field(default="")
    fix_suggestion: str = Field(default="")
    snippet: str = Field(
        default="", description="Code snippet context from the issue location."
    )
    is_auto_fixable: bool = Field(default=False)


class AgentPlanRequest(BaseModel):
    api_key: str = Field(
        default="", description="License API key — gates the endpoint to Indie+."
    )
    issues: list[_PlanIssue] = Field(default_factory=list)
    # Soft cap so the planner doesn't blow up on pathological scans; the
    # plugin should already trim to what fits in the user's UI.
    max_steps: int = Field(default=200, ge=1, le=2000)


class AgentPlanStep(BaseModel):
    order: int = Field(..., ge=1)
    rule_id: str
    file_path: str
    line: int
    severity: str
    priority: str = Field(..., description="critical | high | medium | low")
    rationale: str
    is_auto_fixable: bool


class AgentPlanResponse(BaseModel):
    success: bool = True
    tier: str = "indie"
    steps: list[AgentPlanStep] = Field(default_factory=list)
    summary: str = Field(default="", description="Human-readable bucket counts.")


# ── Explain (single-issue direct LLM call) models ──────────────────────────


class AgentExplainRequest(BaseModel):
    """Single-issue explanation request. Plugin sends ONE issue (already
    enriched by the orchestrators with rule_name + rule_explanation) and
    gets a short customer-facing explanation back. No tools, no
    orchestrator loop — the deterministic rules already detected the
    issue, the LLM only writes the explanation."""

    api_key: str = Field(
        default="", description="License API key — gates the endpoint to Indie+."
    )
    issue: _PlanIssue = Field(
        ..., description="The issue to explain. Must include rule_name."
    )


class AgentExplainResponse(BaseModel):
    success: bool = True
    explanation: str = Field(default="")
    generation_seconds: float = Field(
        default=0.0,
        description=(
            "Wall-clock time spent in the LLM call. 0.0 on a prefab or"
            " cache hit — the explanation was served without invoking"
            " the model."
        ),
    )
    cached: bool = Field(
        default=False,
        description=(
            "True when the response was served instantly from any"
            " non-LLM source (prefab OR MongoDB cache). The plugin can"
            " use this to skip its 'generating…' spinner animation."
        ),
    )
    source: str = Field(
        default="live",
        description=(
            "Where the explanation came from: 'prefab' (curated Opus"
            " 4.7 explanation shipped with the backend),"
            " 'cache' (prior LLM output stored in MongoDB), or 'live'"
            " (fresh local LLM generation). Telemetry / debugging"
            " field; the plugin can ignore it."
        ),
    )
    tier: str = Field(default="indie")
    error_message: str = Field(
        default="",
        description="Populated only when success=false (LLM unavailable etc).",
    )


# ── Prioritization buckets (rule-based, deterministic) ─────────────────────
#
# This is intentionally hand-rolled rather than using an LLM in Slice A.
# The bucket score combines:
#
#   - Rule prefix    (CS=security, CP=perf, CB=best practices, CM=maint,
#                    BPB/BPP/BPM=blueprint variants, NM=naming).
#   - Severity       (error >> warning >> info).
#   - Auto-fixable   (small bonus — quick wins go up).
#
# Lower score = higher priority (sorted ascending).

_PREFIX_BASE_SCORE: dict[str, int] = {
    "CS": 0,  # C++ Security                — always first
    "BPP": 5,  # BP performance              — visible perf hits
    "CP": 10,  # C++ performance
    "BPB": 20,  # BP best practices           — naming, structure
    "CB": 25,  # C++ best practices
    "BPM": 35,  # BP maintainability
    "CM": 40,  # C++ maintainability
    "NM": 60,  # Asset naming                — cosmetic, low risk
}

_SEVERITY_OFFSET: dict[str, int] = {
    "error": 0,
    "warning": 50,
    "info": 100,
}


def _score_issue(issue: _PlanIssue) -> int:
    prefix = "".join(ch for ch in issue.rule_id if ch.isalpha())[:3]
    base = _PREFIX_BASE_SCORE.get(prefix, 80)
    sev_offset = _SEVERITY_OFFSET.get(issue.severity.lower(), 200)
    fixable_bonus = -2 if issue.is_auto_fixable else 0
    return base + sev_offset + fixable_bonus


def _priority_label(score: int) -> str:
    if score < 20:
        return "critical"
    if score < 50:
        return "high"
    if score < 100:
        return "medium"
    return "low"


# Per-rule rationale templates. When the rule isn't in the table we fall
# back to the issue's own `message`. Slice C will replace this with an LLM
# explanation that knows the surrounding code context.
_RATIONALE: dict[str, str] = {
    # Security
    "CS001": (
        "GetWorld() puede devolver nullptr durante"
        " level transitions; sin guarda, este"
        " acceso provoca crash en runtime."
    ),
    "CS002": (
        "SpawnActor sin validar el resultado:"
        " cualquier fallo de spawn (presupuesto,"
        " location bloqueada) deja el puntero a"
        " nullptr y acceder a sus campos crashea."
    ),
    "CS003": (
        "Cast<T>() devuelve nullptr cuando el tipo"
        " no coincide; sin null-check, una"
        " asignación o llamada subsecuente"
        " revienta."
    ),
    "CS004": (
        "División por cero produce NaN en floats"
        " y crash en ints; el guard explícito"
        " evita comportamiento indefinido."
    ),
    "CS005": (
        "Acceso a array sin verificar"
        " IsValidIndex — out-of-bounds en TArray"
        " es un crash directo."
    ),
    # Performance
    "CP001": (
        "FindObject en Tick recorre la GC root"
        " cada frame (potencialmente miles de"
        " UObjects) — coste lineal sobre el"
        " tamaño del world."
    ),
    "CP002": (
        "GetComponent en Tick es O(n) sobre los"
        " componentes del actor; cachéalo en"
        " BeginPlay."
    ),
    "CP003": (
        "Tick muy largo bloquea el game thread;"
        " refactoriza el cuerpo en sub-funciones"
        " llamadas por estado o usa Timer"
        " manager."
    ),
    "CP004": (
        "UE_LOG dentro de Tick spamea la consola"
        " y serializa strings cada frame —"
        " costoso incluso si el output está"
        " silenciado."
    ),
    "CP005": (
        "Sleep en game thread congela el render"
        " y el input; usa async tasks o"
        " LatentActions."
    ),
    "CP006": (
        "GetAllActorsOfClass itera cada actor del"
        " world; en Tick o se cachea o se cambia"
        " a una lista pre-poblada."
    ),
    "CP007": (
        "Activar Tick desde el constructor altera"
        " el orden de inicialización; muévelo a"
        " BeginPlay."
    ),
    "CP016": (
        "Forzar GC manual interrumpe el frame;"
        " deja al engine programar GC salvo en"
        " transiciones de nivel concretas."
    ),
}


def _rationale_for(issue: _PlanIssue) -> str:
    canned = _RATIONALE.get(issue.rule_id)
    if canned:
        return canned
    if issue.fix_suggestion:
        return f"{issue.message} · sugerencia: {issue.fix_suggestion}"
    return issue.message or "Pendiente de revisión manual."


# ── Endpoint ───────────────────────────────────────────────────────────────


@router.post("/plan", response_model=AgentPlanResponse)
async def plan(payload: AgentPlanRequest) -> AgentPlanResponse:
    tier = await resolve_tier(payload.api_key)
    if tier == "free":
        # Defense in depth — the free plugin shouldn't even render the
        # Auto-Fix Plan button, but if someone reverse-engineers the call
        # this fails closed.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Auto-Fix Plan is an Indie-tier feature.",
        )

    if not payload.issues:
        return AgentPlanResponse(success=True, tier=tier, steps=[], summary="0 issues")

    # Score, sort, paginate.
    scored = [(_score_issue(i), idx, i) for idx, i in enumerate(payload.issues)]
    # Stable: secondary sort key is the original index so equal scores keep
    # the validator's reading order (top of file first).
    scored.sort(key=lambda t: (t[0], t[1]))

    steps: list[AgentPlanStep] = []
    bucket_counts: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for order, (score, _idx, issue) in enumerate(scored[: payload.max_steps], start=1):
        priority = _priority_label(score)
        bucket_counts[priority] += 1
        steps.append(
            AgentPlanStep(
                order=order,
                rule_id=issue.rule_id,
                file_path=issue.file_path,
                line=issue.line,
                severity=issue.severity,
                priority=priority,
                rationale=_rationale_for(issue),
                is_auto_fixable=issue.is_auto_fixable,
            )
        )

    summary = " · ".join(f"{n} {label}" for label, n in bucket_counts.items() if n)
    return AgentPlanResponse(
        success=True,
        tier=tier,
        steps=steps,
        summary=summary or "0 issues",
    )


# ── Explain endpoint (direct LLM, no agent orchestrator) ───────────────────


@router.post("/explain", response_model=AgentExplainResponse)
async def explain(payload: AgentExplainRequest) -> AgentExplainResponse:
    """Generate a short customer-facing explanation for a single issue.

    This endpoint bypasses the agent orchestrator entirely: there are no
    tools, no JSON protocol, no parser. The deterministic rules have
    already detected the issue and enriched it with rule_name and
    rule_explanation; the LLM's only job is to turn that into 2-4
    grounded sentences the developer can act on.

    Resolution order (fastest to slowest):
        1) Prefab lookup by rule_id — curated Opus 4.7 explanation
           shipped with the backend. Resolves in microseconds.
        2) MongoDB explanation_cache by sha1(model_id + prompt) —
           prior LLM output for this exact prompt, valid for 90 days.
        3) Live local LLM call — 20-40 s on CPU.

    The MongoDB cache key automatically invalidates whenever the
    prompt template, the rule's docstring, OR the model file changes
    — no manual flush. Prefab entries are regenerated by re-running
    core/scripts/generate_prefab_cache.py.

    Tier-gated to Indie+. Returns success=false with an explanation of
    why if the LLM is not loaded, instead of raising — this lets the
    plugin show the deterministic message+fix_suggestion as a fallback
    without crashing the UX.
    """
    import time

    from modules.agent.explainer import explain_issue
    from modules.agent.llm_backend import is_loaded
    from modules.agent.prefab_explanations import lookup_prefab

    tier = await resolve_tier(payload.api_key)
    if tier == "free":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="AI explanations are an Indie-tier feature.",
        )

    # 1) Prefab lookup — instant, in-memory, never touches the LLM.
    prefab = lookup_prefab(payload.issue.rule_id)
    if prefab and prefab.get("explanation"):
        return AgentExplainResponse(
            success=True,
            explanation=prefab["explanation"],
            generation_seconds=0.0,
            cached=True,
            source="prefab",
            tier=tier,
            error_message="",
        )

    # Pydantic strips unknown fields by default. We pass the issue as a
    # plain dict to the explainer so any extra fields the orchestrator
    # added (context_before, snippet, asset_path, graph) survive.
    issue_payload_dict = payload.issue.model_dump(mode="json")

    # 2) MongoDB cache DISABLED — always generate fresh.
    # Explanations are logged to local JSONL for fine-tuning instead.

    # 3) Live LLM call (always).
    if not is_loaded():
        return AgentExplainResponse(
            success=False,
            explanation="",
            generation_seconds=0.0,
            cached=False,
            source="live",
            tier=tier,
            error_message="LLM model not loaded — agent is not available.",
        )

    started_at = time.perf_counter()
    try:
        generated_text = explain_issue(issue_payload_dict)
    except Exception as unexpected_error:
        return AgentExplainResponse(
            success=False,
            explanation="",
            generation_seconds=round(time.perf_counter() - started_at, 2),
            cached=False,
            source="live",
            tier=tier,
            error_message=(
                f"LLM generation failed: "
                f"{type(unexpected_error).__name__}: {unexpected_error}"
            ),
        )

    generation_seconds = round(time.perf_counter() - started_at, 2)

    # Log to local JSONL for fine-tuning. Best-effort — a write
    # failure does not affect the response we already produced.
    from modules.agent.finetuning_logger import log_explanation

    log_explanation(
        rule_id=payload.issue.rule_id,
        rule_name=payload.issue.rule_name,
        rule_explanation=payload.issue.rule_explanation,
        explanation_generated=generated_text,
        issue_payload=issue_payload_dict,
        generation_seconds=generation_seconds,
    )

    return AgentExplainResponse(
        success=True,
        explanation=generated_text,
        generation_seconds=generation_seconds,
        cached=False,
        source="live",
        tier=tier,
        error_message="",
    )


# ── Explain (streaming SSE) ────────────────────────────────────────────────


async def _explain_stream_events(
    payload: AgentExplainRequest, tier: str
) -> AsyncIterator[str]:
    """Produce the Server-Sent Events body for /agent/explain/stream.

    Event shapes (one per `data:` line, JSON-encoded):

        {"chunk": "<text fragment>"}
            One slice of the model's output. Multiple of these per
            stream; the plugin appends them to its display.

        {"error": "<message>"}
            Fatal condition (LLM not loaded, generation crashed).
            Always followed by a done event with full_text="".

        {"done": true,
         "full_text": "<concatenated chunks>",
         "cached": <bool>,
         "generation_seconds": <float>}
            Final event marking the end of the stream. The plugin
            stops its spinner / typing indicator when this arrives.

    On a cache hit we emit one big chunk with the cached text and an
    immediate done event with cached=true and generation_seconds=0.0
    — no LLM call.
    """
    import time

    from modules.agent.explainer import explain_issue_stream
    from modules.agent.llm_backend import is_loaded
    from modules.agent.prefab_explanations import lookup_prefab

    # 1) Prefab — emit as one chunk + done, no DB, no model.
    prefab = lookup_prefab(payload.issue.rule_id)
    if prefab and prefab.get("explanation"):
        prefab_text = prefab["explanation"]
        yield "data: " + json.dumps({"chunk": prefab_text}) + "\n\n"
        yield (
            "data: "
            + json.dumps(
                {
                    "done": True,
                    "full_text": prefab_text,
                    "cached": True,
                    "source": "prefab",
                    "generation_seconds": 0.0,
                }
            )
            + "\n\n"
        )
        return

    issue_payload_dict = payload.issue.model_dump(mode="json")

    # 2) MongoDB cache DISABLED — always generate fresh.
    # Explanations are logged to local JSONL for fine-tuning instead.

    if not is_loaded():
        yield "data: " + json.dumps(
            {"error": "LLM model not loaded — agent is not available."}
        ) + "\n\n"
        yield "data: " + json.dumps(
            {
                "done": True,
                "full_text": "",
                "cached": False,
                "source": "live",
                "generation_seconds": 0.0,
            }
        ) + "\n\n"
        return

    # Cache miss + model ready → stream the generation, accumulating
    # text so we can persist it once the stream ends.
    started_at = time.perf_counter()
    accumulated_parts: list[str] = []
    stream_failed: Exception | None = None
    try:
        for chunk in explain_issue_stream(issue_payload_dict):
            accumulated_parts.append(chunk)
            yield "data: " + json.dumps({"chunk": chunk}) + "\n\n"
    except Exception as unexpected_error:
        stream_failed = unexpected_error
        yield "data: " + json.dumps(
            {
                "error": (
                    f"LLM generation failed: "
                    f"{type(unexpected_error).__name__}: {unexpected_error}"
                )
            }
        ) + "\n\n"

    generation_seconds = round(time.perf_counter() - started_at, 2)
    accumulated_text = "".join(accumulated_parts).strip()

    # Persist the new explanation IF the stream completed cleanly and
    # we actually produced text. Best-effort — a write failure does
    # Log to local JSONL for fine-tuning. Best-effort — a write
    # failure does not affect what we already sent down the wire.
    if stream_failed is None and accumulated_text:
        from modules.agent.finetuning_logger import log_explanation

        log_explanation(
            rule_id=payload.issue.rule_id,
            rule_name=payload.issue.rule_name,
            rule_explanation=payload.issue.rule_explanation,
            explanation_generated=accumulated_text,
            issue_payload=issue_payload_dict,
            generation_seconds=generation_seconds,
        )

    yield (
        "data: "
        + json.dumps(
            {
                "done": True,
                "full_text": accumulated_text,
                "cached": False,
                "source": "live",
                "generation_seconds": generation_seconds,
            }
        )
        + "\n\n"
    )


@router.post("/explain/stream")
async def explain_stream(payload: AgentExplainRequest) -> StreamingResponse:
    """Stream a customer-facing explanation token-by-token via SSE.

    Same input contract as POST /agent/explain. The response is a
    text/event-stream of `data: {json}\\n\\n` events; see
    `_explain_stream_events` for the schema.

    On a cache hit the stream closes within milliseconds (one chunk
    event + one done event). On a miss the model produces tokens at
    ~10-15 tok/s on CPU, so the plugin sees content within ~3-5 s of
    the request — far better UX than waiting 20-40 s for the
    synchronous /agent/explain to return the full text.

    Tier-gated to Indie+. The free tier gets a 403 before the stream
    is even opened, so the plugin never sees a half-open SSE on a
    license-gated endpoint.
    """
    tier = await resolve_tier(payload.api_key)
    if tier == "free":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="AI explanations are an Indie-tier feature.",
        )

    return StreamingResponse(
        _explain_stream_events(payload, tier),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Disable proxy buffering so events arrive promptly at the
            # plugin instead of being held back until the body fills.
            "X-Accel-Buffering": "no",
        },
    )
