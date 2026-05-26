# GET /health  <- consumed by UE5 plugin (ShintCoreClient::CheckHealth)
# GET /ping    <- consumed by UE5 plugin (ShintCoreClient::Ping)
# GET /status  <- consumed by the web dashboard (unchanged)

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def get_health(request: Request):
    """
    Primary health-check endpoint for plugins.
    Returns 200 OK so that the UE5 plugin status indicator turns Online.
    Includes commit SHA for version tracking.
    """
    db_connected = getattr(request.app.state, "db_connected", False)
    commit_sha = getattr(request.app.state, "commit_sha", "unknown")
    return {
        "status": "ok",
        "version": "0.1.0",
        "commit": commit_sha,
        "database": "ok" if db_connected else "unavailable",
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
    Includes version, commit SHA, detected modules and MongoDB connection status.
    """
    db_connected = getattr(request.app.state, "db_connected", False)
    modules = getattr(request.app.state, "modules", [])
    commit_sha = getattr(request.app.state, "commit_sha", "unknown")

    return {
        "status": "ok",
        "version": "0.1.0",
        "commit": commit_sha,
        "modules": modules,
        "database": {
            "connected": db_connected,
            "status": "ok" if db_connected else "unavailable",
        },
    }
