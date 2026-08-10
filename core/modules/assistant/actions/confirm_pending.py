# core/modules/assistant/actions/confirm_pending.py
#
# "Yes" / "no" to the confirmation the assistant just asked for.
#
# The counterpart to remember_fact and define_rule: they propose, this
# commits or drops. Nothing else in the assistant may flip a fact to
# confirmed or a rule to active from free text — the whole point of the
# proposal contract is that a statement never becomes a stored decision
# without the user saying so, and this is the one place that "so" is read.
#
# The pending target is resolved by pending.pending_proposal() from the
# thread itself, never from the model and never from the message: the
# message is only ever a yes or a no.

from __future__ import annotations

from typing import Any

from .. import memory_store, pending, rule_store

_NOTHING_PENDING = (
    "There's nothing waiting on a yes or no right now. Tell me what to "
    "remember, or describe a rule, and I'll ask you to confirm it."
)

_GONE = (
    "That proposal is no longer available — it may have expired or already "
    "been resolved. Check the Memory panel, or tell me again and I'll "
    "propose it fresh."
)


def _quote(subject: str) -> str:
    """The stored text, short enough to sit inside a sentence.

    Quoting is not decoration: the reply has to show WHAT was committed, or
    a confirmation is indistinguishable from the assistant agreeing with
    itself. Same reason define_rule._describe stopped being a constant.
    """
    text = (subject or "").strip()
    if not text:
        return ""
    return f' "{text}"' if len(text) <= 140 else f' "{text[:139].rstrip()}…"'


async def _commit_fact(fact_id: str, subject: str, accept: bool) -> dict:
    status = "confirmed" if accept else "retracted"
    fact = await memory_store.set_fact_status(fact_id, status)
    if fact is None:
        return {"reply": _GONE, "fact_id": ""}

    quoted = _quote(subject or str(fact.get("value") or ""))
    reply = (
        f"Saved{quoted}. I'll apply it from now on — in future scans and in "
        "this conversation."
        if accept
        else f"Dropped{quoted}. It won't be stored or used anywhere."
    )
    return {"reply": reply, "fact_id": fact_id, "fact_status": status}


async def _commit_rule(rule_id: str, subject: str, accept: bool) -> dict:
    if accept:
        rule = await rule_store.set_rule_status(
            rule_id, status="active", confirmed=True
        )
    else:
        rule = await rule_store.set_rule_status(
            rule_id, status="deprecated", confirmed=False
        )
    if rule is None:
        return {"reply": _GONE, "rule_id": ""}

    quoted = _quote(subject or str(rule.get("name") or ""))
    reply = (
        f"Rule active{quoted}. It starts enforcing on the next scan."
        if accept
        else f"Rule dropped{quoted}. It won't run on any scan."
    )
    # rule_status is never "draft" here, so _proposal_of will not re-arm the
    # question with the id this turn just committed.
    return {
        "reply": reply,
        "rule_id": rule_id,
        "rule_status": "active" if accept else "deprecated",
    }


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    """Commit or drop whatever the previous assistant turn proposed.

    ``pending`` and ``answer`` are put in the payload by the route, which
    already resolved both to decide this action should run at all. Falling
    back to re-reading the message keeps the action usable on its own (a UI
    may declare the intent directly).
    """
    proposal = payload.get("pending") or {}
    answer = payload.get("answer") or pending.read_affirmation(
        str(payload.get("message") or "")
    )

    if not proposal or not proposal.get("id"):
        return {"reply": _NOTHING_PENDING}
    if answer not in ("accept", "reject"):
        return {"reply": _NOTHING_PENDING}

    accept = answer == "accept"
    subject = str(proposal.get("subject") or "")

    if proposal.get("kind") == "fact":
        return await _commit_fact(str(proposal["id"]), subject, accept)
    return await _commit_rule(str(proposal["id"]), subject, accept)
