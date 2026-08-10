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

# "all widgets start with SShint", "las texturas empiezan por T_".
# ONLY the prefix/suffix form: it is the one shape that maps to a regex with
# no interpretation. Anything vaguer about naming stays Tier B — a wrong
# naming pattern flags every file in the project at once.
_NAME_PREFIX = re.compile(
    r"(?:start(?:s|ing)? with|begin(?:s|ning)? with|prefixed with|"
    r"empiez[ae]n? (?:por|con)|comienz[ae]n? (?:por|con)|prefijo)\s+"
    r"[`\"']?(?P<prefix>[A-Za-z_][A-Za-z0-9_]*)[`\"']?",
    re.IGNORECASE,
)
_NAME_SUFFIX = re.compile(
    r"(?:end(?:s|ing)? with|suffixed with|termin[ae]n? (?:por|con)|sufijo)\s+"
    r"[`\"']?(?P<suffix>[A-Za-z_][A-Za-z0-9_]*)[`\"']?",
    re.IGNORECASE,
)
# The extension a naming/required rule is scoped to, when the sentence says.
_FILE_EXT = re.compile(r"[`\"']?(?P<ext>\.(?:h|hpp|cpp|cs|uasset|umap))\b",
                       re.IGNORECASE)

# "every Actor must call Super::BeginPlay", "todo .cpp debe incluir X"
_REQUIRED = re.compile(
    r"(?:must (?:call|include|contain|have)|deben? (?:llamar a|incluir|"
    r"contener|tener)|tiene que (?:llamar a|incluir|contener))\s+"
    r"[`\"']?(?P<required>[A-Za-z_][A-Za-z0-9_:\.<>]*)[`\"']?",
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

    # naming_pattern and required_text existed in rule_templates from the
    # start but nothing here ever produced them, so the single most common
    # kind of studio rule — a naming convention — could not reach its own
    # deterministic template and always fell through to Tier B.
    prefix = _NAME_PREFIX.search(text)
    suffix = _NAME_SUFFIX.search(text)
    pattern = ""
    if prefix is not None:
        pattern = re.escape(prefix.group("prefix")) + r".*"
    elif suffix is not None:
        pattern = r".*" + re.escape(suffix.group("suffix"))
    if pattern:
        name_params: dict[str, Any] = {"pattern": pattern}
        ext = _FILE_EXT.search(text)
        if ext:
            name_params["file_glob_suffix"] = ext.group("ext").lower()
        return {
            "tier": "template",
            "template": {"template_id": "naming_pattern",
                         "params": name_params},
            "confidence": "high",
        }

    match = _REQUIRED.search(text)
    if match:
        required = match.group("required")
        # "must have more than 3 LODs" is a budget, not a required token.
        if required.lower() not in {"more", "less", "at", "a", "an", "the",
                                    "mas", "más", "menos", "un", "una"}:
            req_params: dict[str, Any] = {"required": required}
            ext = _FILE_EXT.search(text)
            if ext:
                req_params["scope_suffixes"] = [ext.group("ext").lower()]
            return {
                "tier": "template",
                "template": {"template_id": "required_text",
                             "params": req_params},
                "confidence": "high",
            }

    return {"tier": "llm_evaluated", "confidence": "low"}
