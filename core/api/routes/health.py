from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/status")
async def get_status(request: Request):
    """
    Returns the current status of the Core Engine.
    Includes version, available modules and MongoDB connection status.
    """
    db_status = "ok" if request.app.state.db_connected else "unavailable"

    return {
        "status": "ok",
        "version": "0.1.0",
        "modules": request.app.state.modules,
        "database": {
            "connected": request.app.state.db_connected,
            "status": db_status,
        },
    }
