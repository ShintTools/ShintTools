# core/api/main.py

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from api.middleware import setup_middlewares
from api.routes import agent, assets, config, dashboard, health, metrics, validate

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

    # Sprint C: Load LLM agent model at startup. Gated by
    # SHINTTOOLS_AGENT_ENABLED (default off): the LLM agent is an
    # Indie-tier feature, so we don't pull the ~3 GB model for free users
    # — the launcher only flips this env var to "1" when the signed-in
    # account resolves to a paying tier.
    if os.getenv("SHINTTOOLS_AGENT_ENABLED") != "1":
        print(
            "LLM agent disabled (SHINTTOOLS_AGENT_ENABLED!=1). "
            "Skipping model load. Agent endpoints will report 'not available'."
        )
    else:
        try:
            from modules.agent.llm_backend import is_loaded, load_model
            from modules.agent.model_downloader import download_model

            if not is_loaded():
                print("LLM model not loaded. Checking for GGUF file...")
                try:
                    model_path = download_model()
                    print(f"Model ready at: {model_path}")
                except FileNotFoundError as e:
                    print(
                        f"WARNING: LLM model unavailable (offline?). "
                        f"Agent endpoints will report 'not available'. "
                        f"Error: {e}"
                    )
                except Exception as e:
                    print(
                        f"WARNING: Failed to prepare LLM model: {e}. "
                        f"Agent endpoints will report 'not available'."
                    )
                else:
                    try:
                        load_model()
                        print("✓ LLM model loaded successfully")
                    except Exception as e:
                        print(f"WARNING: Failed to load LLM model: {e}")
        except ImportError:
            print("INFO: Agent module not available (develop branch only)")

    yield

    # Cleanup: unload LLM model on shutdown
    try:
        from modules.agent.llm_backend import unload_model

        unload_model()
        print("LLM model unloaded")
    except Exception:
        pass


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
app.include_router(
    metrics.router
)  # GET /metrics/score/latest  GET /metrics/score/history
app.include_router(agent.router)  # POST /agent/* (Sprint C - Rules-based prioritizer)
