# core/modules/assistant/model_profile.py
#
# light vs advanced model profiles — a configuration layer over the
# EXISTING runtime, not a second backend. Both profiles load through
# llm_backend's singleton + lock; what changes is which .gguf and which
# n_ctx get passed in. The router/actions contract is identical for both:
# a bigger model buys router precision on ambiguous phrasing and better
# prose, never free-form tool-calling.
#
# advanced is Studio-only and guarded three times before it ever loads:
#   1. capability table says the tier may use it
#   2. the .gguf actually exists on disk (nothing is auto-downloaded here;
#      the launcher provisions it for Studio installs that opt in)
#   3. the machine has headroom: model size + working margin in available
#      RAM — otherwise fall back to light with a single logged warning,
#      never a hard failure.
#
# Whether advanced becomes the Studio DEFAULT is decided by the M4 eval
# (scripts/assistant_router_eval.py against the golden set), not here.

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("shinttools.assistant.model")

_MODELS_ROOT = Path(__file__).resolve().parent.parent.parent / "models" / "agent"

PROFILES: dict[str, dict[str, Any]] = {
    "light": {
        "model_file": "Qwen2.5-Coder-1.5B-Instruct-Q4_K_M.gguf",
        "models_dir": _MODELS_ROOT / "qwen2.5-coder-1.5b",
        "n_ctx": 4096,
        # ~940 MB file; loaded working set with KV cache under ~2.5 GB.
        "min_available_ram_gb": 3.0,
    },
    "advanced": {
        # Same family/tokenizer as light — the whole prompt registry and
        # LoRA pipeline carry over unchanged.
        "model_file": "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf",
        "models_dir": _MODELS_ROOT / "qwen2.5-coder-7b",
        "n_ctx": 8192,
        # ~4.7 GB file; leave the editor + Core real headroom.
        "min_available_ram_gb": 10.0,
    },
}

# Env overrides, mirroring llm_backend's knobs:
#   SHINTTOOLS_ASSISTANT_PROFILE      force a profile name ("light"/"advanced")
#   SHINTTOOLS_ADVANCED_MODEL_FILE    override the advanced .gguf filename
#   SHINTTOOLS_ADVANCED_MODELS_DIR    override the advanced model directory


def _available_ram_gb() -> float | None:
    """Available system RAM in GB, or None when undeterminable.

    /proc/meminfo covers the Docker/Linux runtime (the shipped Core).
    Elsewhere (bare Windows dev runs) we return None and the caller
    treats "can't tell" as "don't risk it".
    """
    try:
        with open("/proc/meminfo", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / (1024 * 1024)
    except OSError:
        pass
    return None


def profile_config(name: str) -> dict[str, Any]:
    config = dict(PROFILES.get(name, PROFILES["light"]))
    if name == "advanced":
        config["model_file"] = os.environ.get(
            "SHINTTOOLS_ADVANCED_MODEL_FILE", config["model_file"]
        )
        override_dir = os.environ.get("SHINTTOOLS_ADVANCED_MODELS_DIR")
        if override_dir:
            config["models_dir"] = Path(override_dir)
    return config


def resolve_profile(tier_profile: str) -> tuple[str, str]:
    """The profile that should actually serve, given the tier's entitlement.

    Returns (profile_name, reason). reason explains any downgrade so the
    panel can surface it once ("advanced model not installed", "not
    enough memory") instead of silently serving different quality.
    """
    forced = (os.environ.get("SHINTTOOLS_ASSISTANT_PROFILE") or "").strip().lower()
    requested = forced or (tier_profile or "light").strip().lower()
    if requested not in PROFILES:
        requested = "light"
    if requested == "light":
        return "light", ""

    config = profile_config("advanced")
    model_path = Path(config["models_dir"]) / config["model_file"]
    if not model_path.is_file():
        logger.warning(
            "advanced profile requested but %s is not installed — serving light",
            model_path,
        )
        return "light", "advanced_model_not_installed"

    available = _available_ram_gb()
    needed = float(config["min_available_ram_gb"])
    if available is None or available < needed:
        logger.warning(
            "advanced profile needs %.0f GB available RAM (have: %s) — serving light",
            needed,
            f"{available:.1f} GB" if available is not None else "unknown",
        )
        return "light", "insufficient_memory"

    return "advanced", ""
