# core/api/routes/agent.py
#
# Agent layer (Sprint: AI-assisted fix planning).
#
# Endpoints:
#   POST /agent/plan   — given a validation report, return a prioritized
#                        fix plan with per-step rationale.
#
# This is Slice A of the agent architecture: the plumbing + a deterministic
# rule-based prioritizer (no LLM yet). Slice C will swap the body of
# `_score_issue` and `_rationale_for` for a llama.cpp / remote API call.
#
# Tier gating: the agent is an Indie-tier feature. Calls from a free key
# (or a missing key) return 403 — the free SKU UI shouldn't render the
# Auto-Fix Plan button at all, but we enforce on the server side too as
# defense in depth.

from __future__ import annotations

from api.database import resolve_tier
from fastapi import APIRouter, HTTPException, status
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
