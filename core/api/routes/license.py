# core/api/routes/license.py
#
# POST /license
#
# Called by the Unity plugin at startup to resolve the real server-side
# tier and display the correct license label in the UI — before any scan
# has been performed.
#
# Integer license codes (matches Unity plugin enum):
#   0 = free
#   1 = indie
#   (2 = personal — reserved for future plan, not yet in DB)

import time

from api.database import resolve_tier
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

# ── Tier ↔ integer mapping ─────────────────────────────────────────────────────

_TIER_TO_INT: dict[str, int] = {
    "free": 0,
    "indie": 1,
}

_DEFAULT_LICENSE_INT: int = 0  # fallback = free


# ── Models ─────────────────────────────────────────────────────────────────────


class LicenseRequest(BaseModel):
    api_key: str = ""
    license: int = 0  # locally cached license the plugin already knows


# ── Endpoint ───────────────────────────────────────────────────────────────────


@router.post("/license")
async def get_license(payload: LicenseRequest):
    """Resolve the server-side license tier for the given api_key.

    Returns the integer license code so the plugin can update its UI
    immediately at startup, independently of any scan call.

    Output:
        error   — non-empty string if something went wrong
        time    — request duration in seconds
        license — 0 = free, 1 = indie
    """
    t0 = time.perf_counter()

    try:
        tier: str = await resolve_tier(payload.api_key)
        license_int: int = _TIER_TO_INT.get(tier, _DEFAULT_LICENSE_INT)

        return {
            "error": "",
            "time": round(time.perf_counter() - t0, 4),
            "license": license_int,
        }

    except Exception as exc:
        return {
            "error": str(exc),
            "time": round(time.perf_counter() - t0, 4),
            "license": _DEFAULT_LICENSE_INT,
        }
