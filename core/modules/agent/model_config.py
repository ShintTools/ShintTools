# core/modules/agent/model_config.py
#
# Model-specific configuration (system prompts, stop tokens, etc.)
#
# When the backend loads a GGUF, it identifies which model it is and
# pulls the corresponding prompt template and generation parameters.
# This keeps model-specific tuning out of the core explainer logic.

from __future__ import annotations

import os
from typing import NamedTuple


class ModelConfig(NamedTuple):
    """Configuration for a specific model."""

    name: str  # Human-readable name
    system_prompt: str  # System instruction for this model
    stop_tokens: list[str]  # Generation stop sequences


# Qwen2.5-Coder 1.5B
QWEN_CONFIG = ModelConfig(
    name="Qwen2.5-Coder 1.5B",
    system_prompt=(
        "You are a senior code reviewer for game projects (Unity and Unreal Engine). "
        "ShintTools' deterministic rules already detected the issue below "
        "— your job is to explain in your own words why it matters and "
        "what they should do next, the way you would say it out loud at a desk.\n"
        "\n"
        "Style:\n"
        "  - Friendly and conversational. Speak in the second person.\n"
        "  - 2 to 4 short sentences in English. No headings, lists, or code blocks.\n"
        "  - Active voice. Say 'you call', not 'is called'.\n"
        "\n"
        "Rules:\n"
        "  - Mention the rule_name in **bold**. Never use rule_id (e.g. CS001).\n"
        "  - Ground every claim in the rule_explanation. Do NOT invent APIs,"
        " editors, or tools that the explanation does not mention.\n"
        "  - Quote tiny code inline with backticks (one expression max).\n"
        "  - Closing line — read is_auto_fixable carefully before writing it:\n"
        "      * is_auto_fixable: true  → end with exactly:"
        " 'ShintTools\\' Auto-Fix can apply it for you.'\n"
        "      * is_auto_fixable: false → end with exactly:"
        " 'You must fix this manually.'\n"
        "  - Stop immediately after the closing line."
        " Do not add headings, labels, or extra sentences after it."
    ),
    stop_tokens=["\n\nINPUT", "INPUT\n"],
)

# Map GGUF filenames to their configs
_MODEL_CONFIGS = {
    "Qwen2.5-Coder-1.5B-Instruct-Q4_K_M.gguf": QWEN_CONFIG,
}


def get_config(model_filename: str) -> ModelConfig:
    """Get the config for a specific GGUF filename.

    Falls back to Qwen config if the model is unknown.
    """
    return _MODEL_CONFIGS.get(model_filename, QWEN_CONFIG)


def detect_config_from_env() -> ModelConfig:
    """Detect the currently configured model and return its config.

    Reads SHINTTOOLS_MODEL_FILE env var (or uses default) and returns
    the corresponding ModelConfig.
    """
    model_file = os.environ.get(
        "SHINTTOOLS_MODEL_FILE", "Qwen2.5-Coder-1.5B-Instruct-Q4_K_M.gguf"
    )
    return get_config(model_file)
