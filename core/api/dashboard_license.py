# core/api/dashboard_license.py
#
# Relay client for the ShintTools dashboard license activation endpoint.
#
# The Core never decides tier validity itself — it delegates to the
# remote dashboard and caches the result in local MongoDB. This module
# is the only place that talks to the external API; all other code uses
# api/database.py for local lookups.

import logging
import os

import httpx

DASHBOARD_URL = os.getenv("SHINTTOOLS_DASHBOARD_URL", "https://shint.tools").rstrip("/")

logger = logging.getLogger("shinttools.dashboard_license")


async def activate(license_key: str, machine_id: str) -> dict:
    """Relay a license activation request to the remote dashboard.

    Calls POST {DASHBOARD_URL}/api/public/license/activate with the
    same payload shape used by the Launcher (license_key + machine_id).

    Never raises — on any network or HTTP error returns a safe
    ``{"valid": False, "tier": "free", "error": "..."}`` dict so the
    caller can propagate the error message to the plugin without
    crashing the Core.

    Response shape (always present after normalization):
        valid           bool    — whether the key is active and bound
        tier            str     — "free" | "indie" | "studio" | "enterprise"
        studio          str     — studio name or ""
        expires_at      str     — ISO-8601 or ""
        bound_machine_id str    — machine the key is bound to or ""
        error           str     — human-readable reason on failure, "" on success
    """
    key = (license_key or "").strip()
    if not key:
        return {"valid": False, "tier": "free", "error": "No license key provided."}

    url = f"{DASHBOARD_URL}/api/public/license/activate"
    body = {
        "license_key": key,
        "machine_id": (machine_id or "").strip(),
    }

    logger.info(
        "dashboard_license.activate: key=...%s machine=...%s → %s",
        key[-6:],
        (machine_id or "")[-6:],
        url,
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=body)
    except Exception as exc:
        logger.error("dashboard_license.activate: network error — %s", exc)
        return {
            "valid": False,
            "tier": "free",
            "error": f"Could not reach the activation server: {exc}",
        }

    try:
        data: dict = resp.json() if resp.content else {}
    except Exception:
        data = {}

    if resp.status_code >= 400 and not data:
        logger.warning(
            "dashboard_license.activate: HTTP %d with empty body", resp.status_code
        )
        return {
            "valid": False,
            "tier": "free",
            "error": f"Activation server responded with HTTP {resp.status_code}.",
        }

    # Normalize — guarantee every key is present so callers never KeyError.
    data.setdefault("valid", False)
    data.setdefault("tier", "free")
    data.setdefault("studio", "")
    data.setdefault("expires_at", "")
    data.setdefault("bound_machine_id", "")
    data.setdefault(
        "error", "" if data.get("valid") else "Activation rejected by the server."
    )

    logger.info(
        "dashboard_license.activate: key=...%s valid=%s tier=%s",
        key[-6:],
        data["valid"],
        data["tier"],
    )
    return data
