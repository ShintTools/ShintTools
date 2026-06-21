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
# (Qwen2.5-Coder 1.5B Q4_K_M, fetched once from ShintTools' own
# GitHub Releases by model_downloader.py). The env vars stay in place
# so we can swap the model without code changes when needed.

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Any, Iterator, Optional

# Default model: Qwen2.5-Coder 1.5B Q4_K_M (~940 MB).
# Small enough to run on a developer laptop without a GPU.
DEFAULT_MODEL_FILE = "Qwen2.5-Coder-1.5B-Instruct-Q4_K_M.gguf"

# Models live outside the source tree (in core/models/) so they don't end
# up in git or in Docker image layers we don't want to bake the model into.
DEFAULT_MODELS_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "models"
    / "agent"
    / "qwen2.5-coder-1.5b"
)


# Module-level singleton. Loaded once during FastAPI lifespan; reused
# across requests. None until load_model() is called.
_llama: Optional[Any] = None

# ── Optional LOD LoRA adapter (applied ONLY on LOD enrichment requests) ─────
#
# One base Coder GGUF stays in RAM and serves every module. The LOD Auditor
# can OPTIONALLY specialise its explanations with a LoRA adapter that is
# attached to the llama context for the duration of a single generation and
# detached immediately after — see lod_adapter(). The Deep Code Validator
# never enters that context, so its Coder output is byte-for-byte unchanged.
#
# Config (all optional — unset ⇒ feature off, plain Coder everywhere):
#   SHINTTOOLS_LOD_LORA_PATH    path to a llama.cpp GGUF LoRA adapter
#   SHINTTOOLS_LOD_LORA_SCALE   adapter strength (float, default 1.0)
#
# The adapter is produced by the deploy loop in scripts/finetune_lora.py:
#   train LoRA → convert_lora_to_gguf.py → drop the .gguf here (NO merge,
#   so the base Coder is shared, not duplicated).
_lod_adapter: Optional[Any] = None  # llama_lora_adapter_p, or None when off


def _lod_lora_scale() -> float:
    try:
        return float(os.environ.get("SHINTTOOLS_LOD_LORA_SCALE", "1.0"))
    except ValueError:
        return 1.0


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

    _init_lod_adapter()


def _init_lod_adapter() -> None:
    """Attach the optional LOD LoRA adapter to the loaded model, if configured.

    No-op (and never raises) when SHINTTOOLS_LOD_LORA_PATH is unset, the file
    is missing, or the binding/adapter fails to load — the runtime then serves
    the plain Coder for every module, exactly as before. Loading here only
    *registers* the adapter; it stays detached until lod_adapter() applies it
    around a single generation.
    """
    global _lod_adapter
    _lod_adapter = None
    if _llama is None:
        return

    raw = os.environ.get("SHINTTOOLS_LOD_LORA_PATH", "").strip()
    if not raw:
        return
    adapter_path = Path(raw)
    if not adapter_path.exists():
        return

    try:
        import llama_cpp

        handle = llama_cpp.llama_lora_adapter_init(
            _llama.model, str(adapter_path).encode("utf-8")
        )
    except Exception:
        handle = None
    # llama_lora_adapter_init returns NULL (falsy ctypes pointer) on failure.
    _lod_adapter = handle or None


def lod_adapter_loaded() -> bool:
    """True when a LOD LoRA adapter is registered and ready to apply."""
    return _lod_adapter is not None


@contextlib.contextmanager
def lod_adapter() -> Iterator[bool]:
    """Apply the LOD LoRA adapter for the duration of the block, then detach.

    Used ONLY by the LOD audit enrichment path. Yields True if the adapter was
    actually applied (so callers can log/branch), False otherwise. The adapter
    is always cleared on exit — even on exception — so a subsequent Deep Code
    Validator generation can never inherit LOD weights.

    When no adapter is configured this is a transparent no-op: the body runs
    against the plain Coder, identical to today.
    """
    applied = False
    if _llama is not None and _lod_adapter is not None:
        try:
            import llama_cpp

            rc = llama_cpp.llama_lora_adapter_set(
                _llama.ctx, _lod_adapter, _lod_lora_scale()
            )
            applied = rc == 0
        except Exception:
            applied = False
    try:
        yield applied
    finally:
        if applied and _llama is not None:
            with contextlib.suppress(Exception):
                import llama_cpp

                llama_cpp.llama_lora_adapter_clear(_llama.ctx)


def is_loaded() -> bool:
    """Return True if a model is currently loaded into memory."""
    return _llama is not None


def unload_model() -> None:
    """Release the loaded model. Mostly useful in tests."""
    global _llama, _lod_adapter
    if _lod_adapter is not None:
        with contextlib.suppress(Exception):
            import llama_cpp

            llama_cpp.llama_lora_adapter_free(_lod_adapter)
    _lod_adapter = None
    _llama = None


# Default stop sequences. The agent protocol asks for a single JSON
# object per turn; small models (1.3B-class) routinely keep generating
# past the closing brace, hallucinating "# Developer response", code
# fences, or follow-on prose. These stops cut generation as soon as
# any of those patterns START, leaving the JSON intact.
#
# Why these specific patterns:
#   "\n\n"    — A blank line. Pretty-printed JSON has single newlines
#               but never blank lines, so this only fires AFTER the
#               action JSON ends and the model tries to elaborate.
#               This catches the "# Developer response" / "# Final
#               answer" pattern observed in the first smoke run, since
#               those headings always come after a blank line.
#   "\n```"   — Markdown code fence opening — common follow-up where
#               the model tries to "show the fixed code" after the JSON.
#
# Earlier we also tried "\n# " (markdown heading right after a single
# newline), but that was too aggressive: the model often produces a
# leading `\n` before its first JSON token, and `\n# ` matched on the
# very first heading-like fragment, killing the response at zero
# tokens. The blank-line variant ("\n\n") catches the realistic noise
# pattern without ever firing inside a valid JSON action.
_DEFAULT_STOPS: list[str] = ["\n\n#", "\n```"]


def generate(
    prompt: str,
    *,
    max_tokens: int = 1024,
    temperature: float = 0.2,
    stop: list[str] | None = None,
) -> str:
    """Run a synchronous completion against the loaded model.

    Returns the full generated text once the model has finished.

    `stop` defaults to a set of patterns chosen to keep a 1.3B model on
    the agent protocol (single JSON object per turn). Pass an explicit
    list (including `[]`) to override.
    """
    if _llama is None:
        raise RuntimeError("Model not loaded — call load_model() first.")

    effective_stop = stop if stop is not None else _DEFAULT_STOPS
    out = _llama(
        prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        stop=effective_stop,
    )
    return out["choices"][0]["text"]


def generate_stream(
    prompt: str,
    *,
    max_tokens: int = 1024,
    temperature: float = 0.2,
    stop: list[str] | None = None,
) -> Iterator[str]:
    """Stream a completion token-by-token, yielding text chunks.

    Used by the /agent/explain/stream SSE endpoint so the plugin can
    show the explanation as it is being generated rather than waiting
    20-40 s for the full text. Each yielded chunk is the raw text the
    model just produced — the caller is responsible for joining the
    pieces back together if it wants the full string.

    Stops the iterator when the model emits any of the configured stop
    sequences, when max_tokens is hit, or when the model decides it is
    done. Empty chunks (which llama-cpp can emit while warming up the
    KV cache) are skipped so the SSE stream stays meaningful.

    Same `stop` semantics as `generate`: pass an explicit list
    (including `[]`) to override the conservative defaults.
    """
    if _llama is None:
        raise RuntimeError("Model not loaded — call load_model() first.")

    effective_stop = stop if stop is not None else _DEFAULT_STOPS
    # llama-cpp-python returns an iterator of chunk dicts shaped like
    #   {"choices": [{"text": "...", ...}], ...}
    # when stream=True. We unwrap and yield the text only — anything
    # downstream that needs metadata can wrap this iterator.
    stream = _llama(
        prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        stop=effective_stop,
        stream=True,
    )
    for chunk in stream:
        try:
            piece = chunk["choices"][0]["text"]
        except (KeyError, IndexError, TypeError):
            # Defensive: an unexpected chunk shape should not crash
            # the whole stream — skip and keep going.
            continue
        if piece:
            yield piece
