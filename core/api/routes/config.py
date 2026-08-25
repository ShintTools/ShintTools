# core/api/routes/config.py
#
# GET  /config — read the project's shinttools.config.json (unauthenticated;
#                read-only, and the CORS allow-list already restricts which
#                browser origins can read the response back).
# POST /config — overwrite the project's shinttools.config.json.
#
# POST was previously reachable with ZERO authentication of any kind — a
# state-changing write to disk that also controls core_host/core_port and
# dashboard_url, i.e. where every subsequent scan (full source file content
# included) and every dashboard credential gets sent. That made it a CSRF
# target: any webpage the user's browser visited while the Core was running
# locally could blind-POST a forged body and silently redirect all future
# Core traffic to an attacker's server. Fixed 2026-08-25 (security audit) —
# see docs/handoff/SECURITY_HARDENING_POST_LAUNCH.md in the Launcher repo.

import json
from pathlib import Path

from api.middleware import enforce_same_origin
from api.tier_guard import enforce_authenticated
from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter()


@router.get("/config")
async def get_config(request: Request):
    """
    Reads and returns the project's shinttools.config.json.
    """
    config_path = request.app.state.config_path

    if not config_path:
        raise HTTPException(
            status_code=400,
            detail="shinttools.config.json not found in project",
        )

    path = Path(config_path)

    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Configuration file not found at: {config_path}",
        )

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@router.post("/config")
async def post_config(
    request: Request,
    new_config: dict,
    api_key: str = Query(
        default="",
        description=(
            "License API key — required. Mirrors the query-param "
            "convention already used by GET /assistant/capabilities and "
            "GET /assistant/memory rather than reshaping the config body."
        ),
    ),
):
    """
    Updates the project's shinttools.config.json.

    Two independent gates, both required:
      1. A license key that actually resolves (any tier — this endpoint is
         not feature-gated by plan, it just must not be reachable by an
         unauthenticated caller). See enforce_authenticated.
      2. Origin, if the browser sent one, must be in the CORS allow-list.
         A non-browser caller (the UE5/Unity plugin) never sends Origin at
         all, so this only ever rejects browser-driven cross-origin
         requests — exactly the CSRF vector this closes.
    """
    await enforce_authenticated(api_key, "/config", "Writing shinttools.config.json")
    enforce_same_origin(request)

    config_path = request.app.state.config_path

    if not config_path:
        raise HTTPException(
            status_code=400,
            detail="shinttools.config.json not found in project",
        )

    path = Path(config_path)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(new_config, f, indent=2)

    return {"status": "ok", "message": "Configuration updated successfully"}
