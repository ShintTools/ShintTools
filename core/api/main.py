# core/api/main.py

import sys
from contextlib import asynccontextmanager

from api.routes import health
from fastapi import FastAPI

# Leemos --config-path de los argumentos si existe
config_path = None
if "--config-path" in sys.argv:
    idx = sys.argv.index("--config-path")
    config_path = sys.argv[idx + 1]


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.config_path = config_path
    # TODO Sprint 4: Cargar modelos NLP
    yield
    # TODO Sprint 4: Limpieza de recursos


app = FastAPI(
    title="ShintTools Core",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)  # GET /status
