# core/api/routes/predictive.py
#
# Predictive Profiler endpoints (Studio tier — see modules/predictive/).
#
#   GET  /predict/profiles       — platform budget profiles
#   POST /predict/session/start  — open a batched-ingest session      (M3)
#   POST /predict/session/ingest — one batch: assets|scene|code|code_files|config
#   POST /predict/analyze        — produce the PredictiveReport       (M1+)
#   POST /predict/simulate       — Impact Simulator over a report     (M4)
#
# M0 ships the contract + profiles; analyze/simulate answer 501 with the
# milestone that delivers them, so clients can integration-test the gate and
# the contract shape before the engine lands.

import asyncio
import logging
import sys
from pathlib import Path

# modules/ on sys.path BEFORE the predictive imports — same pattern as
# assets.py/validate.py. Never rely on another route having done it first
# (the agent.* import trap: resolves under pytest, breaks under uvicorn).
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "modules"))

from api.tier_guard import enforce_studio  # noqa: E402
from fastapi import APIRouter, HTTPException  # noqa: E402
from predictive.cost_model.platform_profiles import (  # noqa: E402
    available_platform_profiles,
)
from predictive.schema import (  # noqa: E402
    INGEST_KINDS,
    SCHEMA_VERSION,
    AnalyzeRequest,
    IngestRequest,
    IngestResponse,
    ProfilesResponse,
    SessionStartRequest,
    SessionStartResponse,
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


@router.post("/predict/session/start")
async def predict_session_start(payload: SessionStartRequest):
    """Open a batched-ingest session. Big projects chunk their sections
    across /predict/session/ingest calls (150 assets/request, the LOD-audit
    precedent) instead of one giant analyze payload."""
    await enforce_studio(payload.api_key, "/predict/session/start", _FEATURE)
    from predictive import session_store

    session_id = await session_store.start_session(
        payload.engine, payload.project_name, payload.platform_profile
    )
    return SessionStartResponse(session_id=session_id)


@router.post("/predict/session/ingest")
async def predict_session_ingest(payload: IngestRequest):
    """Append one batch (assets | scene | code | code_files | config) to a session."""
    await enforce_studio(payload.api_key, "/predict/session/ingest", _FEATURE)
    if payload.kind not in INGEST_KINDS:
        raise HTTPException(
            status_code=422,
            detail={
                "error": f"unknown ingest kind {payload.kind!r}",
                "valid_kinds": sorted(INGEST_KINDS),
            },
        )
    from predictive import session_store

    result = await session_store.ingest(
        payload.session_id, payload.kind, payload.payload
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "unknown or expired session",
                    "session_id": payload.session_id},
        )
    accepted, totals = result
    return IngestResponse(
        session_id=payload.session_id,
        kind=payload.kind,
        accepted=accepted,
        total_ingested=totals,
    )


@router.post("/predict/analyze")
async def predict_analyze(payload: AnalyzeRequest):
    """Predictive analysis.

    Session mode (``session_id``): analyzes the batched-ingest session.
    One-shot mode: inline sections — small projects, curl demos, tests.
    Either way the finished report is cached so /predict/simulate can
    replay selections against it (M4).

    Analysis itself runs in a worker thread: a large project (tens of
    thousands of assets/issues) is pure synchronous CPU work — inline in
    this async handler it stalls the event loop for seconds, so /health
    and every other in-flight request queue up behind it (measured: p95
    /health latency during a 20k-asset analyze jumped from ~3 ms to over
    1.6 s). Same pattern as the LLM enrichment in lod_audit.py and
    explain_finding.py.
    """
    await enforce_studio(payload.api_key, "/predict/analyze", _FEATURE)
    from predictive import session_store
    from predictive.predictive_orchestrator import analyze_oneshot, analyze_session

    if payload.session_id:
        session = await session_store.get_session(payload.session_id)
        if session is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "unknown or expired session",
                        "session_id": payload.session_id},
            )
        report = await asyncio.to_thread(analyze_session, session)
    else:
        report = await asyncio.to_thread(analyze_oneshot, payload)

    await session_store.save_report(report.report_id, report.model_dump())
    return report


@router.post("/predict/simulate")
async def predict_simulate(payload: SimulateRequest):
    """Impact Simulator — replay a selection against a cached report.

    Pure arithmetic over the report's cost items (no re-analysis): deltas
    per dimension, before/after risk scores, and next-fix recommendations.
    ``platform_profile`` switches both sides of the comparison to another
    platform's budgets (the porting scenario). When the cached report has
    expired the client may inline ``cost_items`` — deltas and
    recommendations still work; the scores need the report's totals.
    """
    await enforce_studio(payload.api_key, "/predict/simulate", _FEATURE)
    from predictive import session_store
    from predictive.layers.layer5_simulator import simulate

    report = None
    if payload.report_id:
        report = await session_store.get_report(payload.report_id)
        if report is None and not payload.cost_items:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "unknown or expired report — re-run "
                    "/predict/analyze or inline cost_items",
                    "report_id": payload.report_id,
                },
            )
    return simulate(
        report,
        payload.selected_item_ids,
        payload.cost_items,
        payload.platform_profile,
    )
