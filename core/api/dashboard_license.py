# core/api/dashboard_license.py
#
# Read-only license resolver against the ShintTools dashboard.
#
# The Core never decides tier validity itself — it delegates to the
# remote dashboard and caches the result in local MongoDB. This module
# is the only place that talks to the external API; all other code uses
# api/database.py for local lookups.
#
# IMPORTANT — we hit /license/validate (READ-ONLY), never /license/activate:
#   * The dashboard's /activate endpoint creates/moves the 1:1 machine
#     binding. That is the LAUNCHER's job at install time — the Launcher
#     knows the real host fingerprint. The Core runs inside Docker and
#     cannot read it, so it must not own the binding.
#   * The Core only needs to READ the tier to gate features. /validate
#     returns the tier without consuming a machine slot.
#   * The dashboard REQUIRES a non-empty machine_id even on /validate
#     (an empty one is rejected with HTTP 400 "Invalid request body"),
#     so we mint a stable synthetic Core fingerprint when the caller
#     doesn't supply one. validate is read-only, so a fingerprint the
#     dashboard doesn't recognise still resolves to valid + tier.

import logging
import os
import uuid

import httpx

DASHBOARD_URL = os.getenv("SHINTTOOLS_DASHBOARD_URL", "https://shint.tools").rstrip("/")

logger = logging.getLogger("shinttools.dashboard_license")

# Browser-shaped User-Agent. Cloudflare 400/403s the default python-httpx
# UA the same way it does for curl; a browser-shaped UA sails through. The
# Core is a legitimate API client — Cloudflare just can't tell without it.
# Mirrors the launcher's app.auth._USER_AGENT.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Persisted synthetic machine fingerprint for /validate calls that arrive
# without one (the runtime tier-resolution path). Stored under the models
# volume so it survives container restarts; falls back to ephemeral if the
# volume isn't writable.
_MODELS_DIR = os.getenv("SHINTTOOLS_MODELS_DIR", "/app/core/models")
_MACHINE_ID_FILE = os.getenv(
    "SHINTTOOLS_MACHINE_ID_FILE", os.path.join(_MODELS_DIR, ".core_machine_id")
)


def _core_machine_id() -> str:
    """Return a stable, non-empty machine_id for dashboard /validate calls.

    Resolution order:
        1. SHINTTOOLS_MACHINE_ID env var (explicit override).
        2. Persisted UUID under _MACHINE_ID_FILE (survives restarts when
           the models/ volume is mounted).
        3. Freshly minted uuid4, persisted best-effort.

    Never raises — worst case returns an in-memory uuid4 so the request
    still carries a non-empty id.
    """
    env = (os.getenv("SHINTTOOLS_MACHINE_ID") or "").strip()
    if env:
        return env

    path = _MACHINE_ID_FILE
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                cached = f.read().strip()
            if cached:
                return cached
    except OSError as exc:
        logger.warning("dashboard_license: could not read machine_id (%s)", exc)

    mid = uuid.uuid4().hex
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(mid)
    except OSError as exc:
        logger.warning(
            "dashboard_license: could not persist machine_id (%s) — "
            "using ephemeral id for this process",
            exc,
        )
    return mid


async def validate_license(license_key: str, machine_id: str = "") -> dict:
    """Resolve a license key's tier via the dashboard's READ-ONLY validate.

    Calls POST {DASHBOARD_URL}/api/public/license/validate with the same
    payload shape the Launcher uses (license_key + machine_id). Does NOT
    create or move a binding — that's the Launcher's job at install.

    machine_id: when empty, a stable synthetic Core fingerprint is
    substituted (the dashboard rejects an empty machine_id with HTTP 400).

    Never raises — on any network or HTTP error returns a safe
    ``{"valid": False, "tier": "free", "error": "..."}`` dict so the
    caller can propagate the error message to the plugin without
    crashing the Core.

    Response shape (always present after normalization):
        valid           bool    — whether the key is active
        tier            str     — "free" | "indie" | "studio" | "enterprise"
        studio          str     — studio name or ""
        expires_at      str     — ISO-8601 or ""
        bound_machine_id str    — machine the key is bound to or ""
        error           str     — human-readable reason on failure, "" on success
    """
    key = (license_key or "").strip()
    if not key:
        return {"valid": False, "tier": "free", "error": "No license key provided."}

    mid = (machine_id or "").strip() or _core_machine_id()

    url = f"{DASHBOARD_URL}/api/public/license/validate"
    body = {
        "license_key": key,
        "machine_id": mid,
    }

    logger.info(
        "dashboard_license.validate: key=...%s machine=...%s → %s",
        key[-6:],
        mid[-6:],
        url,
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                json=body,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": _USER_AGENT,
                },
            )
    except Exception as exc:
        logger.error("dashboard_license.validate: network error — %s", exc)
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
            "dashboard_license.validate: HTTP %d with empty body", resp.status_code
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
        "dashboard_license.validate: key=...%s valid=%s tier=%s",
        key[-6:],
        data["valid"],
        data["tier"],
    )
    return data
