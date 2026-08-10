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

# Preambles that mean "the fact starts after me". Longest first WITHIN each
# family: the loop breaks on the first startswith hit, so a bare "confirm"
# placed above "confirm that" would leave a dangling "that ..." behind.
#
# Must stay in step with intent_router's markers. A phrase the router accepts
# as "remember this" but this list doesn't know is stored verbatim, preamble
# and all — the fact reads back as "Confirm that we use Nanite" instead of
# "we use Nanite", and every later comparison carries the request wording.
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
    "please confirm that",
    "please confirm",
    "confirma que",
    "confírmame que",
    "confirmame que",
    "confirmo que",
    "confirm that",
    "confirm",
    "for the record",
    "make a note that",
    "note that",
    "que conste que",
    "para que conste que",
    "para que conste",
    "ten en cuenta que",
)

_DECISION_MARKERS = ("decid", "acordamos", "agreed", "vamos a usar", "we use")


def _starts_with_word(lowered: str, preamble: str) -> bool:
    """startswith(), but the preamble has to end on a word boundary.

    Plain startswith matched "confirm" inside "confirmo que ..." and left
    "o que ..." as the fact — and "remember" inside "remembering". A stored
    fact is quoted back to the user verbatim, so a half-eaten first word is
    not cosmetic.
    """
    if not lowered.startswith(preamble):
        return False
    rest = lowered[len(preamble):]
    return not rest or not (rest[0].isalnum() or rest[0] in "áéíóúüñ")


def extract_statement(message: str) -> str:
    """The fact text: the user's sentence minus its preamble."""
    text = (message or "").strip()
    lowered = text.lower()
    for preamble in _PREAMBLES:
        if _starts_with_word(lowered, preamble):
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
