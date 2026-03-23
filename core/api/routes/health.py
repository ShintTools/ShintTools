# core/api/routes/health.py

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/status")
async def get_status(request: Request):
    """
    Returns the current status of the Core Engine.
    Includes version and list of available modules detected at startup.
    """
    return {
        "status": "ok",
        "version": "0.1.0",
        "modules": request.app.state.modules,
    }
