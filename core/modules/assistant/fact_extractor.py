# core/modules/assistant/fact_extractor.py
#
# Turns a remember_fact message into a proposed fact.
#
# Deliberately deterministic in M2: the stored value is the user's own
# sentence with the "remember that / recuerda que" preamble stripped —
# nothing paraphrased, so nothing can be misheard. An LLM pass that also
# fills `structured` (machine-comparable fields for the M6 proactive
# detector) can be layered on later; the proposal/confirmation contract
# doesn't change.

from __future__ import annotations

import re

# Preambles that mean "the fact starts after me". Longest-match first.
_PREAMBLES = (
    "remember that",
    "recuerda que",
    "apunta que",
    "remember",
    "recuerda",
    "apunta",
    "we decided that",
    "we decided",
    "hemos decidido que",
    "hemos decidido",
    "decidimos que",
    "decidimos",
)

_DECISION_MARKERS = ("decid", "acordamos", "agreed", "vamos a usar", "we use")


def extract_statement(message: str) -> str:
    """The fact text: the user's sentence minus its preamble."""
    text = (message or "").strip()
    lowered = text.lower()
    for preamble in _PREAMBLES:
        if lowered.startswith(preamble):
            text = text[len(preamble):].lstrip(" ,:.-")
            break
    return text.strip()


def classify_fact_type(message: str) -> str:
    """decision | preference | studio_fact — coarse, deterministic."""
    lowered = (message or "").lower()
    if any(m in lowered for m in _DECISION_MARKERS):
        return "decision"
    if re.search(r"\b(prefiero|preferimos|prefer|nos gusta)\b", lowered):
        return "preference"
    return "studio_fact"
