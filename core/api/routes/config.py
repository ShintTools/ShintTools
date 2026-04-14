# core/api/routes/config.py

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

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
async def post_config(request: Request, new_config: dict):
    """
    Updates the project's shinttools.config.json.
    """
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
