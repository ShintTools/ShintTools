# core/api/main.py

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from api.middleware import setup_middlewares
from api.routes import (
    assets,
    config,
    health,
    license,
    metrics,
    unity,
    validate,
)

# NOTE: the paid-only routers (agent, lod_audit, dashboard) are imported
# lazily in the registration block below — they are physically absent from the
# free image, so a top-level import here would crash the free Core on boot.
from api.version import CORE_VERSION

# ── Image edition gate ────────────────────────────────────────────────────────
#
# Two published editions of the Core image share this codebase:
#
#   free  (default, ghcr …:latest)  — the Fab / free-tier surface only.
#   paid  (ghcr …:paid)             — adds the Indie + Studio routers: the LLM
#                                     agent (/agent/*), the LOD Auditor
#                                     (/assets/lod/*) and dashboard upload
#                                     (/dashboard/*).
#
# The edition is baked into each image via a Docker ARG→ENV (SHINT_CORE_EDITION)
# so the free image never *exposes* paid endpoints (they 404 rather than 403)
# and never loads the paid LLM model. Defaults to "free" so any build without
# the flag is the safe, restricted one.
SHINT_CORE_EDITION = os.getenv("SHINT_CORE_EDITION", "free").strip().lower()
_IS_PAID_EDITION = SHINT_CORE_EDITION == "paid"

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


def get_commit_sha() -> str:
    """
    Returns the current git commit SHA (7-char short form).
    Falls back to 'unknown' if not in a git repository or git is unavailable.
    """
    try:
        import subprocess

        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


async def _load_llm_in_background(app: FastAPI) -> None:
    """Download + load + warm up the LLM model without blocking the lifespan.

    The marketplace UE5 wizard times out the Core's first-boot health check at
    60 s. The Qwen 1.5B GGUF is ~940 MB — on a slow connection that download
    alone exceeds the budget, never mind warm-up. Doing this work after
    `yield` means /health responds 200 immediately while the model is still
    arriving; the agent endpoints (/agent/explain, /agent/plan) check
    is_loaded() themselves and report 'not available' until the task finishes.

    State machine (exposed via /health.llm_status and /status.llm.status):
        loading           — download or load in progress
        ready             — model loaded, warm-up done
        loaded_no_warmup  — loaded but warm-up failed (still usable)
        unavailable       — download failed (offline / 404 / hash mismatch)
        load_failed       — download ok but load_model() threw
        not_installed     — agent module missing entirely (free-tier image)
    """
    app.state.llm_status = "loading"

    # Free edition ships no paid surface — the LLM agent is Indie+/Studio only.
    # Skip the ~940 MB download/load entirely rather than warm a model that has
    # no reachable route in this image.
    if not _IS_PAID_EDITION:
        print("INFO: free edition — LLM agent disabled (paid image only)")
        app.state.llm_status = "not_installed"
        return

    try:
        from modules.agent.llm_backend import is_loaded, load_model
        from modules.agent.model_downloader import download_model
    except ImportError:
        print("INFO: Agent module not available (develop branch only)")
        app.state.llm_status = "not_installed"
        return

    if is_loaded():
        app.state.llm_status = "ready"
        return

    print("LLM model not loaded. Checking for GGUF file...")
    try:
        model_path = download_model()
        print(f"Model ready at: {model_path}")
    except FileNotFoundError as e:
        print(
            f"WARNING: LLM model unavailable (offline?). "
            f"Agent endpoints will report 'not available'. Error: {e}"
        )
        app.state.llm_status = "unavailable"
        return
    except Exception as e:
        print(
            f"WARNING: Failed to prepare LLM model: {e}. "
            f"Agent endpoints will report 'not available'."
        )
        app.state.llm_status = "unavailable"
        return

    try:
        load_model()
        print("✓ LLM model loaded successfully")
    except Exception as e:
        print(f"WARNING: Failed to load LLM model: {e}")
        app.state.llm_status = "load_failed"
        return

    try:
        from modules.agent.explainer import warmup as _warmup

        elapsed = _warmup()
        print(f"✓ LLM warm-up done ({elapsed:.1f}s) — KV cache primed")
        app.state.llm_status = "ready"
    except Exception as e:
        print(f"WARNING: LLM warm-up failed: {e}")
        app.state.llm_status = "loaded_no_warmup"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages server startup and shutdown lifecycle.

    Anything that can take more than a couple of seconds (LLM model
    download, warm-up) is dispatched to a background task — the marketplace
    wizard times out /health at 60 s, so the lifespan body itself must
    finish well under that.
    """
    config_path = find_config_path()
    app.state.config_path = config_path

    # Surface the image edition so /health + /status report it (lets the
    # launcher/plugin hide paid UI against a free Core instead of 404-probing).
    app.state.edition = SHINT_CORE_EDITION

    if config_path:
        print(f"Config found at: {config_path}")
    else:
        print("shinttools.config.json not found")

    # Detect available modules
    app.state.modules = detect_modules()
    print(f"Modules detected: {app.state.modules}")

    # Get git commit SHA
    app.state.commit_sha = get_commit_sha()
    print(f"Commit: {app.state.commit_sha}")

    # Check MongoDB connection
    from api.database import ping_database

    db_connected = await ping_database()
    app.state.db_connected = db_connected

    if db_connected:
        print("MongoDB connected successfully")
    else:
        print("WARNING: MongoDB not available")

    # Sprint C: LLM agent. Gated by SHINTTOOLS_AGENT_ENABLED (default off):
    # the LLM agent is an Indie-tier feature, so we don't pull the ~940 MB
    # model for free users — the launcher only flips this env var to "1"
    # when the signed-in account resolves to a paying tier.
    #
    # When enabled, the download + load + warm-up runs in a background
    # task so /health stays responsive during first boot (marketplace
    # wizard times out at 60 s).
    llm_task: asyncio.Task | None = None
    if os.getenv("SHINTTOOLS_AGENT_ENABLED") != "1":
        print(
            "LLM agent disabled (SHINTTOOLS_AGENT_ENABLED!=1). "
            "Skipping model load. Agent endpoints will report 'not available'."
        )
        app.state.llm_status = "disabled"
    else:
        llm_task = asyncio.create_task(_load_llm_in_background(app))

    yield

    # Cleanup: cancel any pending LLM load, then unload the model.
    if llm_task is not None and not llm_task.done():
        llm_task.cancel()
        try:
            await llm_task
        except (asyncio.CancelledError, Exception):
            pass

    try:
        from modules.agent.llm_backend import unload_model

        unload_model()
        print("LLM model unloaded")
    except Exception:
        pass


app = FastAPI(
    title="ShintTools Core",
    version=CORE_VERSION,
    lifespan=lifespan,
)

# Register middlewares
setup_middlewares(app)

# Register routes
# ── Free-tier surface (both editions) ─────────────────────────────────────────
# Code Validator, Asset Naming, license + config + health. These serve free
# users too and stay runtime tier-gated (resolve_tier / filter_issues_by_tier).
app.include_router(health.router)  # GET /health  GET /ping  GET /status
app.include_router(config.router)  # GET/POST /config
app.include_router(validate.router)  # POST /validate/*
app.include_router(
    assets.router
)  # POST /assets/scan  POST /assets/fix  POST /assets/unity/scan
app.include_router(
    metrics.router
)  # GET /metrics/score/latest  GET /metrics/score/history
app.include_router(license.router)  # POST /license
app.include_router(unity.router)  # POST /validate/unity/scan

# ── Paid surface (Indie + Studio) — paid image only ───────────────────────────
# Registered solely when SHINT_CORE_EDITION=paid. The paid sources are *physically
# stripped* from the free image (see Dockerfile), so the guarded import is the
# real gate: setting `-e SHINT_CORE_EDITION=paid` on a free image can't unlock
# anything because the modules aren't there to import. A free user hitting these
# routes gets 404, and the paid LLM agent never loads (see _load_llm_in_background).
if _IS_PAID_EDITION:
    try:
        from api.routes import agent, dashboard, lod_audit

        app.include_router(agent.router)  # POST /agent/*            (Indie+)
        app.include_router(lod_audit.router)  # POST /assets/lod/*       (Studio)
        app.include_router(dashboard.router)  # POST /dashboard/report   (Indie+)
    except ImportError as exc:
        # Paid edition requested but the paid sources are absent (free image
        # with the env flipped). Fall back to free so /health reports honestly.
        print(f"WARNING: paid routers unavailable — running as free ({exc})")
        SHINT_CORE_EDITION = "free"
        _IS_PAID_EDITION = False

print(f"INFO: ShintTools Core edition = {SHINT_CORE_EDITION}")
