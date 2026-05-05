# core/api/routes/agent.py
#
# Agent layer (Sprint: AI-assisted fix planning + live LLM code review).
#
# Endpoints:
#   POST /agent/plan   — given a validation report, return a prioritized
#                        fix plan with per-step rationale.
#   POST /agent/review — SSE stream of live agent reasoning over source code.
#
# Slice A (plan): deterministic rule-based prioritizer.
# Slice C (review): full orchestrator pipeline with local LLM + tool calling.
#
# Tier gating: the agent is an Indie-tier feature. Calls from a free key
# (or a missing key) return 403.

from __future__ import annotations

import json
from typing import AsyncGenerator

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


# ── Review (SSE stream) models ─────────────────────────────────────────────


class AgentReviewRequest(BaseModel):
    api_key: str = Field(
        default="", description="License API key — gates the endpoint to Indie+."
    )
    file_path: str = Field(..., description="Absolute path of the file being reviewed.")
    file_content: str = Field(..., description="Full UTF-8 source text.")
    issues: list[_PlanIssue] = Field(
        default_factory=list, description="Issues from /validate/* to contextualize."
    )
    max_iterations: int = Field(
        default=8, ge=1, le=50, description="Max LLM turns before halt."
    )


class AgentReviewSSEEvent(BaseModel):
    kind: str = Field(
        ...,
        description=("'thinking' | 'tool_call' | 'tool_result' | 'done'."),
    )
    payload: str = Field(
        ...,
        description=("Event body: raw text for thinking/done, JSON for tools."),
    )
    tool_name: str = Field(
        default="",
        description="Name when kind is 'tool_call' or 'tool_result'.",
    )


# ── Diagnostics (backend-only health check) ─────────────────────────────────


class AgentDiagnosticsResponse(BaseModel):
    status: str = Field(
        ...,
        description="'ok' | 'degraded' | 'error'.",
    )
    llm_loaded: bool = Field(..., description="Is the LLM model in memory and ready?")
    llm_model_path: str = Field(default="", description="Path to GGUF if available.")
    orchestrator_ok: bool = Field(
        default=False,
        description="Did the agent orchestrator run successfully?",
    )
    test_ran: bool = Field(default=False, description="Did we execute a test case?")
    elapsed_seconds: float = Field(
        default=0.0, description="Total time to run the test."
    )
    iterations_used: int = Field(
        default=0, description="How many LLM turns before completion?"
    )
    final_answer: str = Field(
        default="",
        description="Agent's conclusion from the test code (truncated).",
    )
    error_message: str = Field(
        default="", description="Error details if status is error."
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


# ── Review endpoint ────────────────────────────────────────────────────────


async def _agent_review_sse_stream(
    payload: AgentReviewRequest,
) -> AsyncGenerator[str, None]:
    """Run the agent and emit SSE events as it executes.

    Event format for Plugin consumption (matches FShintAgentReviewEvent):
      data: {"kind": "thinking" | "tool_call" | "tool_result" | "done",
             "payload": "...", "tool_name": "..."}

    Events are emitted in order: thinking tokens, tool_call/tool_result pairs,
    final done event.
    """
    from modules.agent import AgentOrchestrator, default_tool_registry
    from modules.agent.llm_backend import generate, is_loaded

    # Validate LLM is loaded.
    if not is_loaded():
        event = {
            "kind": "done",
            "payload": "LLM model not loaded — agent is not available.",
            "tool_name": "",
        }
        yield f"data: {json.dumps(event)}\n\n"
        return

    # Build initial context for the agent (file path + issues for the orchestrator).
    initial_context = {
        "file_path": payload.file_path,
        "file_content": payload.file_content,
        "issue_count": len(payload.issues),
        "issues": [i.model_dump(mode="json") for i in payload.issues],
    }

    # Create orchestrator with real LLM backend.
    orchestrator = AgentOrchestrator(
        tool_registry=default_tool_registry,
        llm_generate_function=generate,
        max_iterations=payload.max_iterations,
    )

    # Run the agent (synchronous, blocking).
    user_request = f"Revisa el archivo {payload.file_path}"
    result = orchestrator.run(
        user_request=user_request,
        initial_context=initial_context,
    )

    # Emit events from the execution trace.
    for step in result.steps:
        action = step.parsed_action

        if action.kind.value == "tool_call" and step.tool_execution_result:
            # Emit tool call event.
            tool_call_payload = {
                "tool": action.tool_name or "",
                "arguments": action.tool_arguments or {},
            }
            event = {
                "kind": "tool_call",
                "payload": json.dumps(tool_call_payload),
                "tool_name": action.tool_name or "",
            }
            yield f"data: {json.dumps(event)}\n\n"

            # Emit tool result event (success or error).
            exec_result = step.tool_execution_result
            if exec_result.success:
                tool_result_payload = {"data": exec_result.data}
            else:
                tool_result_payload = {"error": exec_result.error_message or ""}
            result_event = {
                "kind": "tool_result",
                "payload": json.dumps(tool_result_payload),
                "tool_name": action.tool_name or "",
            }
            yield f"data: {json.dumps(result_event)}\n\n"
        elif action.kind.value == "finish" and action.final_answer:
            # Final answer event.
            event = {
                "kind": "done",
                "payload": action.final_answer,
                "tool_name": "",
            }
            yield f"data: {json.dumps(event)}\n\n"


@router.post("/review")
async def review(payload: AgentReviewRequest) -> StreamingResponse:
    """Stream live LLM-powered code review with tool calling.

    Agent reasoning over source code, calling tools to analyze, extract excerpts,
    and apply fixes. Returns SSE events matching FShintAgentReviewEvent.

    Tier-gated to Indie+. Requires the model to be loaded on startup.
    """
    tier = await resolve_tier(payload.api_key)
    if tier == "free":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agent Review is an Indie-tier feature.",
        )

    return StreamingResponse(
        _agent_review_sse_stream(payload),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable proxy buffering so events stream live.
        },
    )


# ── Diagnostics endpoint ───────────────────────────────────────────────────


@router.get("/diagnostics", response_model=AgentDiagnosticsResponse)
async def diagnostics() -> AgentDiagnosticsResponse:
    """Backend-only diagnostics: quick health check of the LLM agent.

    No API key required (internal tool). Measures agent responsiveness by
    running a minimal test case: analyze a simple C++ snippet with a known
    issue, measure round-trip time and iteration count.

    Status codes:
      - 'ok': model loaded, orchestrator ran, agent finished
      - 'degraded': model unavailable but API responsive
      - 'error': exception or fatal failure
    """
    import time

    response = AgentDiagnosticsResponse(
        status="degraded",
        llm_loaded=False,
        llm_model_path="",
        orchestrator_ok=False,
        test_ran=False,
        elapsed_seconds=0.0,
        iterations_used=0,
        final_answer="",
        error_message="",
    )

    try:
        from pathlib import Path

        from modules.agent.llm_backend import is_loaded

        # Check if model exists and is loadable.
        response.llm_loaded = is_loaded()
        try:
            # Try to find model path (matches llm_backend._resolved_model_path logic)
            import os

            models_dir = Path(
                os.environ.get(
                    "SHINTTOOLS_MODELS_DIR",
                    Path(__file__).resolve().parent.parent.parent / "models",
                )
            )
            model_file = os.environ.get(
                "SHINTTOOLS_MODEL_FILE",
                "deepseek-coder-1.3b-instruct.Q4_K_M.gguf",
            )
            model_path = models_dir / model_file
            if model_path.exists():
                response.llm_model_path = str(model_path)
        except Exception:
            pass

        if not response.llm_loaded:
            response.status = "degraded"
            response.error_message = "LLM model not loaded"
            return response

        # Test the orchestrator with simple C++ code.
        from modules.agent import AgentOrchestrator, default_tool_registry
        from modules.agent.llm_backend import generate

        test_code = """void AMyActor::BeginPlay()
{
    Super::BeginPlay();
    UWorld* World = GetWorld();
    AActor* Result = World->SpawnActor<AActor>();
    Result->SetActorLocation(FVector(0, 0, 0));
}"""

        orchestrator = AgentOrchestrator(
            tool_registry=default_tool_registry,
            llm_generate_function=generate,
            max_iterations=5,
        )

        start = time.time()
        result = orchestrator.run(
            user_request="Revisa este codigo C++ de Unreal Engine",
            initial_context={
                "file_path": "MyActor.cpp",
                "file_content": test_code,
                "issue_count": 0,
                "issues": [],
            },
        )
        elapsed = time.time() - start

        response.test_ran = True
        response.elapsed_seconds = round(elapsed, 2)
        response.iterations_used = len(result.steps)
        response.orchestrator_ok = True

        # Capture final answer (truncate to 200 chars for readability).
        if result.steps:
            last_step = result.steps[-1]
            if last_step.parsed_action.final_answer:
                response.final_answer = last_step.parsed_action.final_answer[:200]

        # Status: ok if agent finished normally.
        if result.halt_reason.value == "finished_normally":
            response.status = "ok"
        else:
            response.status = "degraded"
            response.error_message = f"Halt reason: {result.halt_reason.value}"

    except Exception as e:
        response.status = "error"
        response.error_message = str(e)

    return response
