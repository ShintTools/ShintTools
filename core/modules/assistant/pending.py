# core/modules/assistant/pending.py
#
# "Yes." — the turn that closes a confirmation loop.
#
# remember_fact and define_rule both PROPOSE: they write a fact/rule in a
# pending state and ask the user to confirm. Until this module existed there
# was no way to answer that question in the conversation. "sí" carries no
# module, no rule id and no verb, so:
#
#   * is_continuation() said False (its opener list has "ok" and "vale" but
#     never had "sí"/"yes"/"confirmo"), and
#   * classify() therefore ran, and the GBNF grammar FORCES one of the eight
#     intents — for a bare "sí" whichever one comes back is arbitrary. Landing
#     on summarize_module or explain_finding then inherited the previous
#     turn's context_ref and answered about the last scan.
#
# That is the whole bug: the user confirms a fact and gets a scan summary.
#
# Both halves of the decision live here and both are pure Python. A pending
# proposal is a fact about the thread, and an affirmation is a closed lexicon
# — neither is a judgement call, so neither goes to a 1.5B model. Same
# principle intent_router already states for the module correction: anything
# decidable in Python is not delegated.

from __future__ import annotations

import re
from typing import Any, Literal

Answer = Literal["accept", "reject"]

# Bare affirmations/negations, bilingual — studio chat is. Matched against
# the whole normalised message, never as substrings: "no" must not fire on
# "no me convence el resumen", and "si" must not fire on "si arreglo esto".
_AFFIRMATIVES: frozenset[str] = frozenset(
    {
        "si", "sí", "si.", "sip", "claro", "vale", "ok", "okay", "oki",
        "dale", "adelante", "correcto", "exacto", "eso es", "asi es",
        "así es", "confirmo", "confirmado", "confirma", "confirmalo",
        "confírmalo", "confirmar", "hazlo", "guardalo", "guárdalo",
        "recuerdalo", "recuérdalo", "acepto", "aceptar", "de acuerdo",
        "perfecto", "yes", "yep", "yeah", "yup", "sure", "confirm",
        "confirmed", "confirm it", "do it", "save it", "remember it",
        "accept", "agreed", "go ahead", "that's right", "thats right",
        "correct",
    }
)

_NEGATIVES: frozenset[str] = frozenset(
    {
        "no", "no.", "nope", "nah", "cancela", "cancelar", "cancel",
        "olvidalo", "olvídalo", "dejalo", "déjalo", "mejor no", "retira",
        "retiralo", "retíralo", "descarta", "descartalo", "descártalo",
        "borralo", "bórralo", "no lo guardes", "discard", "reject",
        "forget it", "drop it", "never mind", "nevermind", "don't", "dont",
    }
)

# A confirmation is a whole message, not a prefix. "sí, pero solo para Unity"
# adds a constraint the proposal doesn't carry — confirming it would store
# something the user did not agree to, so anything past this budget goes back
# to normal routing and gets answered on its merits.
_MAX_ANSWER_WORDS = 4

_PUNCT = re.compile(r"[¡!¿?.,;:\"'()]+")


def _normalise(message: str) -> str:
    text = _PUNCT.sub(" ", (message or "").strip().lower())
    return " ".join(text.split())


def read_affirmation(message: str) -> Answer | None:
    """"accept" / "reject" for a bare yes-or-no, else None.

    None means "this is not an answer to the pending question" — the caller
    must then route the message normally. Conservative on purpose: a false
    negative costs the user one extra click in the Memory panel, a false
    positive silently stores something nobody agreed to.
    """
    text = _normalise(message)
    if not text or len(text.split()) > _MAX_ANSWER_WORDS:
        return None
    if text in _AFFIRMATIVES:
        return "accept"
    if text in _NEGATIVES:
        return "reject"
    return None


def pending_proposal(
    conversation: dict[str, Any] | None,
) -> dict[str, str] | None:
    """The proposal awaiting an answer, or None.

    Only the LAST assistant turn counts. A proposal from ten turns ago is not
    what "sí" means now — the user is answering the question they were just
    asked, and treating an older one as still open would confirm the wrong
    thing on a thread that moved on.

    Returns {"kind": "fact"|"rule", "id": …, "subject": …}; `subject` is the
    stored text, so the reply can quote what was confirmed instead of
    answering with a fixed sentence.
    """
    turns = [
        t
        for t in (conversation or {}).get("turns") or []
        if isinstance(t, dict)
    ]
    for turn in reversed(turns):
        if turn.get("role") != "assistant":
            continue
        fact_id = str(turn.get("proposed_fact_id") or "").strip()
        if fact_id:
            return {
                "kind": "fact",
                "id": fact_id,
                "subject": str(turn.get("proposed_subject") or ""),
            }
        rule_id = str(turn.get("proposed_rule_id") or "").strip()
        if rule_id:
            return {
                "kind": "rule",
                "id": rule_id,
                "subject": str(turn.get("proposed_subject") or ""),
            }
        return None  # newest assistant turn proposed nothing
    return None
