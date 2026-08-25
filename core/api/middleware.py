# core/api/middleware.py

import logging

from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("shinttools")

# Single source of truth for "who is allowed to talk to this Core from a
# browser". Shared by CORSMiddleware below AND enforce_same_origin() —
# CORS only gates whether browser JS is allowed to READ a cross-origin
# response, it does nothing to stop a "simple" cross-origin request (no
# preflight — e.g. a JSON body sent with no Content-Type header) from
# being SENT and processed server-side. That gap is a CSRF vector against
# every state-changing endpoint reachable at this fixed, well-known
# localhost address (security audit 2026-08-25 — see
# docs/handoff/SECURITY_HARDENING_POST_LAUNCH.md in the Launcher repo).
ALLOWED_ORIGINS = [
    "http://localhost",  # web dashboard (no port)
    "http://localhost:18200",  # UE5 plugin default port
    "http://127.0.0.1:18200",  # UE5 plugin via loopback IP
    "http://127.0.0.1",  # loopback without port
]


def enforce_same_origin(request: Request) -> None:
    """Reject a request whose Origin header is present and not in
    ALLOWED_ORIGINS.

    A browser ALWAYS attaches Origin on a cross-origin fetch/XHR/form POST
    and page JS cannot spoof or omit it — so this blocks a malicious
    webpage's forged request while leaving every non-browser caller (the
    UE5/Unity plugins, which never send an Origin header at all) untouched.
    Call this explicitly from route handlers that mutate state and were not
    already behind a mandatory, unguessable api_key — CORSMiddleware alone
    does not stop the request from being sent, only from being read back.
    """
    origin = request.headers.get("origin")
    if origin and origin not in ALLOWED_ORIGINS:
        logger.warning("Rejected cross-origin request: Origin=%s path=%s",
                        origin, request.url.path)
        raise HTTPException(
            status_code=403,
            detail={"error": "Cross-origin request rejected."},
        )


class LoggingMiddleware(BaseHTTPMiddleware):
    """Logs every incoming request and its response status."""

    async def dispatch(self, request: Request, call_next) -> Response:
        logger.info(f"Request: {request.method} {request.url}")
        response = await call_next(request)
        logger.info(f"Response: {response.status_code}")
        return response


def setup_middlewares(app) -> None:
    """
    Registers all middlewares on the server.
    Call from main.py at startup.
    """

    # CORS: covers bare localhost (browser / dashboard)
    # AND the UE5 plugin which
    # includes the port number in the Origin header.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(LoggingMiddleware)
