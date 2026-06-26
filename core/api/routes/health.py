# GET /health  <- consumed by UE5 plugin (ShintCoreClient::CheckHealth)
# GET /ping    <- consumed by UE5 plugin (ShintCoreClient::Ping)
# GET /status  <- consumed by the web dashboard (unchanged)

from api.version import CORE_VERSION
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def get_health(request: Request):
    """
    Primary health-check endpoint for plugins.
    Returns 200 OK so that the UE5 plugin status indicator turns Online.

    IMPORTANT: This endpoint MUST stay fast and non-blocking. The marketplace
    UE5 wizard times out at 60 s, so anything that could delay startup (LLM
    model download, large I/O) lives in a background task and is reported
    via app.state.llm_status — never awaited here.
    """
    db_connected = getattr(request.app.state, "db_connected", False)
    commit_sha = getattr(request.app.state, "commit_sha", "unknown")
    llm_status = getattr(request.app.state, "llm_status", "disabled")
    edition = getattr(request.app.state, "edition", "free")
    return {
        "status": "ok",
        "version": CORE_VERSION,
        "commit": commit_sha,
        "edition": edition,
        "database": "ok" if db_connected else "unavailable",
        "llm_status": llm_status,
    }


@router.get("/ping")
async def ping():
    """
    Lightweight round-trip test.
    No DB access, no app.state reads — always returns instantly.
    """
    return {"pong": True}


@router.get("/status")
async def get_status(request: Request):
    """
    Detailed status endpoint for the web dashboard.
    Includes version, commit SHA, detected modules, MongoDB connection
    status, and LLM background-load status.
    """
    db_connected = getattr(request.app.state, "db_connected", False)
    modules = getattr(request.app.state, "modules", [])
    commit_sha = getattr(request.app.state, "commit_sha", "unknown")
    llm_status = getattr(request.app.state, "llm_status", "disabled")
    edition = getattr(request.app.state, "edition", "free")

    return {
        "status": "ok",
        "version": CORE_VERSION,
        "commit": commit_sha,
        "edition": edition,
        "modules": modules,
        "database": {
            "connected": db_connected,
            "status": "ok" if db_connected else "unavailable",
        },
        "llm": {
            "status": llm_status,
        },
    }
