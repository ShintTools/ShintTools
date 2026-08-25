# core/api/tier_guard.py
#
# Shared tier-gate for Studio-only routes (LOD Auditor, Predictive Profiler).
#
# Extracted from routes/lod_audit.py when the Predictive Profiler needed the
# identical gate — one place to keep the GH #37 lesson (Enterprise is a
# superset of Studio; gating on `!= "studio"` wrongly 403'd Enterprise).

import logging

from api.database import resolve_tier_detailed
from fastapi import HTTPException

logger = logging.getLogger("shinttools.tier_guard")

# Human-readable cause per resolve_tier reason code. Surfaced in the 403
# so the developer knows WHY the gate denied them instead of a bare
# "Forbidden" — the common case (key bound to another machine / never
# activated on this one / no key configured) is otherwise invisible
# without opening the Core's Docker logs.
REASON_MESSAGES = {
    "empty_key": (
        "No license key is configured. Sign in or paste your Indie/Studio "
        "key in the launcher (Settings → License), then restart the Core."
    ),
    "key_not_found": (
        "This license key isn't active on this machine. A key is bound 1:1 "
        "to the first machine that activates it — if it's already in use on "
        "another computer, release it from shint.tools/account/devices or "
        "use your own key."
    ),
    "db_unavailable": (
        "Couldn't reach the license database. Make sure Docker Desktop and "
        "the ShintTools Core container are running, then try again."
    ),
}


async def enforce_studio(
    api_key: str,
    route_label: str,
    feature_name: str = "This feature",
    resolver=None,
) -> str:
    """Tier-gate helper that returns the resolved tier or raises 403.

    Uses :func:`resolve_tier_detailed` so the 403 carries a specific,
    actionable reason (bound elsewhere / no key / DB down) rather than a
    generic Forbidden. ``feature_name`` personalises the error ("LOD Auditor
    requires...", "Predictive Profiler requires...").

    ``resolver`` lets a calling route pass its own module-level
    resolve_tier_detailed so existing tests that monkeypatch the route's
    global keep working (test_lod_audit.py patches
    ``api.routes.lod_audit.resolve_tier_detailed``).
    """
    tier, reason = await (resolver or resolve_tier_detailed)(api_key)
    logger.info("%s: tier=%s reason=%s", route_label, tier, reason or "-")
    # Studio AND Enterprise unlock Studio features — Enterprise is a superset
    # of Studio, so gating on `!= "studio"` wrongly 403'd Enterprise (GH #37).
    if tier not in ("studio", "enterprise"):
        logger.info(
            "%s: denied tier=%s reason=%s — Studio required",
            route_label,
            tier,
            reason or "-",
        )
        # When the tier simply isn't high enough (valid key, lower plan)
        # there's no reason code — that's a genuine upgrade prompt. When a
        # reason IS set, the key didn't resolve at all, so explain why.
        hint = REASON_MESSAGES.get(reason, "")
        detail = {
            "error": f"{feature_name} requires a Studio subscription.",
            "current_tier": tier,
            "required_tier": "studio",
        }
        if reason:
            detail["reason"] = reason
            detail["message"] = hint
        raise HTTPException(status_code=403, detail=detail)
    return tier


async def enforce_authenticated(
    api_key: str,
    route_label: str,
    feature_name: str = "This endpoint",
    resolver=None,
) -> str:
    """Auth-only gate: requires a license key that actually resolves, but
    imposes no minimum tier (unlike :func:`enforce_studio`).

    Same shape and same 401/403-with-reason UX as ``enforce_studio`` —
    reuses :func:`resolve_tier_detailed` rather than inventing a separate
    credential. For endpoints that are not feature-gated by subscription
    plan (every tier is entitled to use them) but still must not be
    reachable by a caller with no license key at all — e.g. ``POST
    /config``, which writes to disk and was previously reachable with zero
    authentication (CWE-306 / CSRF, security audit 2026-08-25).

    ``resolver`` mirrors ``enforce_studio``'s test-monkeypatch seam.
    """
    tier, reason = await (resolver or resolve_tier_detailed)(api_key)
    logger.info("%s: tier=%s reason=%s", route_label, tier, reason or "-")
    if reason:
        logger.info(
            "%s: denied — reason=%s (no resolvable license key)",
            route_label,
            reason,
        )
        detail = {
            "error": f"{feature_name} requires a valid license key.",
            "reason": reason,
            "message": REASON_MESSAGES.get(reason, ""),
        }
        raise HTTPException(status_code=401, detail=detail)
    return tier
