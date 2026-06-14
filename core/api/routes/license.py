# core/api/routes/license.py
#
# License endpoints:
#   POST /license          — resolve current tier from local MongoDB
#   POST /license/activate — validate against remote dashboard + seed MongoDB

import time

from api.dashboard_license import validate_license as dashboard_validate
from api.database import resolve_tier, seed_license
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

# ── Tier ↔ integer mapping ─────────────────────────────────────────────────────
#
# Integer codes consumed by the plugin UI enum.
# Add new tiers here only — never change existing values.

_TIER_TO_INT: dict[str, int] = {
    "free": 0,
    "indie": 1,
    "studio": 2,
    "enterprise": 3,
}

_DEFAULT_LICENSE_INT: int = 0  # fallback = free


# ── Models ─────────────────────────────────────────────────────────────────────


class LicenseRequest(BaseModel):
    api_key: str = ""
    license: int = 0  # locally cached license the plugin already knows


class ActivateRequest(BaseModel):
    api_key: str = ""
    machine_id: str = (
        ""  # 32-hex from %APPDATA%/ShintTools/machine_id.txt; "" = no binding
    )


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.post("/license")
async def get_license(payload: LicenseRequest):
    """Resolve the server-side license tier for the given api_key.

    Looks up the key in local MongoDB first; falls back to the remote
    dashboard automatically if the key is not found locally.

    Output:
        error   — non-empty string if something went wrong
        time    — request duration in seconds
        license — 0 = free, 1 = indie, 2 = studio, 3 = enterprise
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


@router.post("/license/status")
async def get_license_status(payload: LicenseRequest):
    """Resolve the server-side license tier as a STRING for the plugin's
    top-bar indicator.

    The marketplace plugin (FShintLicenseApi::RequestStatus) POSTs
    ``{"api_key": "..."}`` here and reads ``{"tier": "...", "error": "...",
    "time": 0.0}``. This is the string-tier sibling of POST /license (which
    returns an integer ``license`` code for the plugin's enum); both resolve
    through resolve_tier() — local MongoDB first, remote dashboard fallback.

    Without this route the plugin's POST 404'd, RequestStatus set
    bSuccess=false, and the indicator defaulted to "free" for EVERY user —
    paid tiers included — which also hid the dashboard-sync action that is
    gated on a paid tier.

    Output:
        error   — non-empty string if something went wrong
        time    — request duration in seconds
        tier    — "free" | "indie" | "studio" | "enterprise"
    """
    t0 = time.perf_counter()
    try:
        tier: str = await resolve_tier(payload.api_key)
        return {
            "error": "",
            "time": round(time.perf_counter() - t0, 4),
            "tier": tier or "free",
        }
    except Exception as exc:
        return {
            "error": str(exc),
            "time": round(time.perf_counter() - t0, 4),
            "tier": "free",
        }


@router.post("/license/activate")
async def activate_license(payload: ActivateRequest):
    """Validate a license key against the remote dashboard and seed MongoDB.

    Called by the plugin Settings panel when the user pastes a key and
    clicks Validate / Activate. Does NOT require the Launcher to have
    seeded MongoDB first.

    Flow:
      1. Relay key + machine_id to the remote dashboard.
      2. If valid, upsert the license document in local MongoDB.
      3. Return the authoritative tier so the plugin unlocks features
         immediately without a restart.

    Output:
        valid   — true if the key is active and accepted
        tier    — "free" | "indie" | "studio" | "enterprise"
        license — integer code (0=free, 1=indie, 2=studio, 3=enterprise)
        error   — human-readable reason on failure, "" on success
        time    — request duration in seconds
    """
    t0 = time.perf_counter()

    result = await dashboard_validate(payload.api_key, payload.machine_id)

    if not result.get("valid"):
        return {
            "valid": False,
            "tier": "free",
            "license": _DEFAULT_LICENSE_INT,
            "error": result.get("error") or "Activation rejected.",
            "time": round(time.perf_counter() - t0, 4),
        }

    tier = str(result.get("tier") or "free").lower()
    studio = str(result.get("studio") or "")

    await seed_license(payload.api_key, tier, studio)

    return {
        "valid": True,
        "tier": tier,
        "license": _TIER_TO_INT.get(tier, _DEFAULT_LICENSE_INT),
        "error": "",
        "time": round(time.perf_counter() - t0, 4),
    }
