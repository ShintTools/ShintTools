# core/api/main.py

import sys
from contextlib import asynccontextmanager
from pathlib import Path

from api.routes import health
from fastapi import FastAPI


def find_config_path() -> Path | None:
    """
    Searches for shinttools.config.json automatically.
    First checks for --config-path argument, then walks up
    to 5 levels from the current file location.
    """
    if "--config-path" in sys.argv:
        idx = sys.argv.index("--config-path")
        return Path(sys.argv[idx + 1])

    current = Path(__file__).resolve().parent
    for _ in range(5):  # Max 5 levels to avoid infinite loops on long paths
        candidate = current / "shinttools.config.json"
        if candidate.exists():
            return candidate
        current = current.parent

    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages server startup and shutdown lifecycle.
    """
    config_path = find_config_path()
    app.state.config_path = config_path

    if config_path:
        print(f"Config found at: {config_path}")
    else:
        print("shinttools.config.json not found")

    # TODO Sprint 4: Load NLP models at startup
    yield
    # TODO Sprint 4: NLP resources cleanup


app = FastAPI(
    title="ShintTools Core",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)  # GET /status
