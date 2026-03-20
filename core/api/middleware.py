# core/api/middleware.py

import logging

from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("shinttools")


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
    # CORS: allows local connections from UE5 and Unity plugins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(LoggingMiddleware)
