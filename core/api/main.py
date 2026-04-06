# core/api/main.py

import sys
from contextlib import asynccontextmanager
from pathlib import Path

from api.middleware import setup_middlewares
from api.routes import assets, config, dashboard, health, validate

# (NUEVO: assets, dashboard)
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


def detect_modules() -> list[str]:
    """
    Scans the modules directory and returns a list of available modules.
    A module is considered available if it contains an __init__.py file.
    """
    modules_path = Path(__file__).resolve().parent.parent / "modules"
    available: list[str] = []

    if not modules_path.exists():
        return available

    for folder in modules_path.iterdir():
        if folder.is_dir() and (folder / "__init__.py").exists():
            available.append(folder.name)

    return sorted(available)


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

    # Detect available modules
    app.state.modules = detect_modules()
    print(f"Modules detected: {app.state.modules}")

    # Check MongoDB connection
    from api.database import ping_database

    db_connected = await ping_database()
    app.state.db_connected = db_connected

    if db_connected:
        print("MongoDB connected successfully")
    else:
        print("WARNING: MongoDB not available")

    # TODO Sprint 4: Load NLP models at startup
    yield
    # TODO Sprint 4: NLP resources cleanup


app = FastAPI(
    title="ShintTools Core",
    version="2.0.0",  # (ACTUALIZADO)
    lifespan=lifespan,
)

# Register middlewares
setup_middlewares(app)

# Register routes
app.include_router(health.router)  # GET /health  GET /ping  GET /status
app.include_router(config.router)  # GET/POST /config
app.include_router(validate.router)  # POST /validate/*
app.include_router(assets.router)  # POST /assets/scan  POST /assets/fix (NUEVO)
app.include_router(dashboard.router)  # POST /dashboard/report (NUEVO)
