# core/modules/assistant/rule_compiler.py
#
# Classifies a natural-language studio rule into Tier A (template) or
# Tier B (LLM-evaluated). Deliberately conservative and deterministic:
# a template match must extract every required parameter unambiguously,
# or the rule falls through to Tier B — a wrong Tier B rule wastes some
# LLM cycles, a wrong Tier A rule produces confident false findings.
#
# The LLM never writes code and never fills template params in M3; a
# grammar-constrained extraction pass can be layered on later behind the
# same propose->confirm contract.

from __future__ import annotations

import re
from typing import Any

# "never use X", "prohibido X", "don't call X", "forbid X in headers"
_FORBIDDEN = re.compile(
    r"(?:never use|don'?t (?:use|call)|forbid|prohibido|prohibida|"
    r"no (?:usar|uséis|uses)|nunca (?:uses|usar|useis|uséis))\s+"
    r"[`\"']?(?P<api>[A-Za-z_][A-Za-z0-9_:\.]*)[`\"']?",
    re.IGNORECASE,
)

_IN_HEADERS = re.compile(r"\b(header|\.h\b|cabecera)", re.IGNORECASE)

# "X files must be under Y", "los tests van en Source/Tests"
_LOCATION = re.compile(
    r"[`\"']?\*?(?P<suffix>\.[A-Za-z0-9]+|[A-Za-z0-9_]+\.[A-Za-z0-9]+)[`\"']?"
    r".{0,40}?(?:must (?:live|be|go) (?:in|under)|van en|deben (?:ir|estar) en)"
    r"\s+[`\"']?(?P<dir>[A-Za-z0-9_/\\\.]+)[`\"']?",
    re.IGNORECASE,
)


def compile_rule(description: str) -> dict[str, Any]:
    """Classify *description*; returns {tier, template?, confidence}.

    tier: "template" (with template body ready to store) or
          "llm_evaluated" (Tier B — description carried verbatim).
    """
    text = (description or "").strip()

    match = _FORBIDDEN.search(text)
    if match:
        api = match.group("api")
        # Guard against swallowing prose ("never use more than...").
        if api.lower() not in {"more", "less", "any", "the", "mas", "más"}:
            params: dict[str, Any] = {"api": api}
            if _IN_HEADERS.search(text):
                params["scope_suffixes"] = [".h", ".hpp"]
            return {
                "tier": "template",
                "template": {"template_id": "forbidden_api", "params": params},
                "confidence": "high",
            }

    match = _LOCATION.search(text)
    if match:
        return {
            "tier": "template",
            "template": {
                "template_id": "file_location",
                "params": {
                    "file_glob_suffix": match.group("suffix"),
                    "required_dir": match.group("dir").replace("\\", "/"),
                },
            },
            "confidence": "high",
        }

    return {"tier": "llm_evaluated", "confidence": "low"}
