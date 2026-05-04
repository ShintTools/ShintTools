# core/modules/agent/llm_backend.py
#
# Local LLM backend via llama-cpp-python.
# Loads a GGUF model from disk and exposes generate().
#
# Sprint C — Fase 1.
#
# Configuration via env vars (so the same code runs on a developer
# laptop and on the studio's on-prem deployment):
#   SHINTTOOLS_MODELS_DIR   directory holding .gguf files
#   SHINTTOOLS_MODEL_FILE   exact .gguf filename to load
#
# For the MVP the whole product ships with a single bundled model
# (DeepSeek Coder 1.3B Q4_K_M, fetched once from ShintTools' own
# GitHub Releases by model_downloader.py). The env vars stay in place
# so we can swap the model without code changes when needed.

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

# Default model: DeepSeek Coder 1.3B Q4_K_M (~800 MB).
# Small enough to run on a developer laptop without a GPU.
DEFAULT_MODEL_FILE = "deepseek-coder-1.3b-instruct.Q4_K_M.gguf"

# Models live outside the source tree (in core/models/) so they don't end
# up in git or in Docker image layers we don't want to bake the model into.
DEFAULT_MODELS_DIR = Path(__file__).resolve().parent.parent.parent / "models"


# Module-level singleton. Loaded once during FastAPI lifespan; reused
# across requests. None until load_model() is called.
_llama: Optional[Any] = None


def _resolved_model_path() -> Path:
    """Return the absolute path of the GGUF the backend should load.

    Reads SHINTTOOLS_MODELS_DIR / SHINTTOOLS_MODEL_FILE env vars; falls
    back to the dev defaults declared above.
    """
    models_dir = Path(os.environ.get("SHINTTOOLS_MODELS_DIR", str(DEFAULT_MODELS_DIR)))
    file_name = os.environ.get("SHINTTOOLS_MODEL_FILE", DEFAULT_MODEL_FILE)
    return models_dir / file_name


def load_model(*, n_ctx: int = 4096, n_threads: int | None = None) -> None:
    """Load the configured GGUF into memory. Idempotent.

    Call once at FastAPI lifespan startup. Subsequent calls are no-ops.
    Raises RuntimeError if the file is missing — caller should run
    `python -m modules.agent.model_downloader` first.
    """
    global _llama
    if _llama is not None:
        return

    path = _resolved_model_path()
    if not path.exists():
        raise RuntimeError(
            f"Model file not found at {path}. "
            "Run `python -m modules.agent.model_downloader` to download it."
        )

    # Imported here, not at module load, so unit tests can monkeypatch
    # _llama without paying the cost of importing the native library.
    from llama_cpp import Llama

    _llama = Llama(
        model_path=str(path),
        n_ctx=n_ctx,
        n_threads=n_threads,
        verbose=False,
    )


def is_loaded() -> bool:
    """Return True if a model is currently loaded into memory."""
    return _llama is not None


def unload_model() -> None:
    """Release the loaded model. Mostly useful in tests."""
    global _llama
    _llama = None


def generate(
    prompt: str,
    *,
    max_tokens: int = 512,
    temperature: float = 0.2,
    stop: list[str] | None = None,
) -> str:
    """Run a synchronous completion against the loaded model.

    Returns the generated text (no metadata). Streaming is added in
    Fase 4 when the SSE endpoint is wired up.
    """
    if _llama is None:
        raise RuntimeError("Model not loaded — call load_model() first.")

    out = _llama(
        prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        stop=stop or [],
    )
    return out["choices"][0]["text"]
