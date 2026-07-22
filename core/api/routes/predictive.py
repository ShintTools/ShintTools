# core/api/routes/predictive.py
#
# Predictive Profiler endpoints (Studio tier — see modules/predictive/).
#
#   GET  /predict/profiles       — platform budget profiles
#   POST /predict/session/start  — open a batched-ingest session      (M3)
#   POST /predict/session/ingest — one batch of assets/scene/code/config (M3)
#   POST /predict/analyze        — produce the PredictiveReport       (M1+)
#   POST /predict/simulate       — Impact Simulator over a report     (M4)
#
# M0 ships the contract + profiles; analyze/simulate answer 501 with the
# milestone that delivers them, so clients can integration-test the gate and
# the contract shape before the engine lands.

import logging
import sys
from pathlib import Path

# modules/ on sys.path BEFORE the predictive imports — same pattern as
# assets.py/validate.py. Never rely on another route having done it first
# (the agent.* import trap: resolves under pytest, breaks under uvicorn).
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "modules"))

from api.tier_guard import enforce_studio
from fastapi import APIRouter, HTTPException
from predictive.cost_model.platform_profiles import available_platform_profiles
from predictive.schema import (
    SCHEMA_VERSION,
    AnalyzeRequest,
    ProfilesResponse,
    SimulateRequest,
)

logger = logging.getLogger("shinttools.predictive")

router = APIRouter()

_FEATURE = "Predictive Profiler"


@router.get("/predict/profiles")
async def predict_profiles(api_key: str = "") -> ProfilesResponse:
    """Platform budget profiles — the denominators of every risk score.

    Studio-tier only, like the rest of the module: the profile list itself
    reveals the product surface, and gating everything uniformly keeps the
    client-side capability probe simple (one 403 means "no module").
    """
    await enforce_studio(api_key, "/predict/profiles", _FEATURE)
    return ProfilesResponse(
        schema_version=SCHEMA_VERSION,
        profiles=[p.model_dump() for p in available_platform_profiles()],
    )


@router.post("/predict/analyze")
async def predict_analyze(payload: AnalyzeRequest):
    """Predictive analysis (one-shot mode).

    M1 covers the assets section: exact VRAM totals, cooked-size bands,
    memory/build risk scores, and audit-driven cost items the Impact
    Simulator will replay. Scene/code sections are accepted but recorded as
    uncovered in ``stats`` until M2/M3; batched sessions land in M3.
    """
    await enforce_studio(payload.api_key, "/predict/analyze", _FEATURE)
    if payload.session_id:
        raise HTTPException(
            status_code=501,
            detail={
                "error": "Batched sessions ship in a later Core release — "
                "use one-shot mode (inline assets) meanwhile.",
                "milestone": "M3",
                "schema_version": SCHEMA_VERSION,
            },
        )
    from predictive.predictive_orchestrator import analyze_oneshot

    return analyze_oneshot(payload)


@router.post("/predict/simulate")
async def predict_simulate(payload: SimulateRequest):
    """Impact Simulator. Lands in M4."""
    await enforce_studio(payload.api_key, "/predict/simulate", _FEATURE)
    raise HTTPException(
        status_code=501,
        detail={
            "error": "The Impact Simulator ships in a later Core release.",
            "milestone": "M4",
            "schema_version": SCHEMA_VERSION,
        },
    )
