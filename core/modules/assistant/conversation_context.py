# core/modules/assistant/conversation_context.py
#
# Turns the stored conversation into something the model can actually use,
# and resolves what a follow-up message is referring to.
#
# Until this module existed the thread was write-only: turns were appended
# and compaction digests were written, but no action ever read either back.
# A question that depended on the previous exchange ("and why does that
# matter?") had nothing to resolve against, because the referent lived in a
# turn nobody looked at.
#
# Two jobs, both deterministic:
#
#   1. build_history() — assembles the digest + a verbatim window of recent
#      turns into a bounded text block for the prompt.
#   2. is_continuation() / last_grounding() — decide whether a message
#      continues the previous exchange and, if so, what it is grounded on.
#
# Note what this module does NOT do: it never lets the model choose the
# grounding. A continuation inherits the PREVIOUS turn's target verbatim —
# the same analysis, the same rule, the same asset the user was already
# looking at. The worst case of a wrong continuation call is answering the
# old question again, never pointing an action at a target nobody selected.

from __future__ import annotations

import re
from typing import Any

# Verbatim turns fed back to the model. Deliberately smaller than
# memory_store.KEEP_VERBATIM_TURNS (8): compaction decides what SURVIVES,
# this decides what is worth spending prompt budget on per turn.
HISTORY_TURNS = 6

# Per-turn and total ceilings for the rendered block. An assistant turn can
# run several hundred words; without a cap a handful of them would crowd out
# the finding data that the answer is actually supposed to be grounded in.
MAX_TURN_CHARS = 400
MAX_HISTORY_CHARS = 2400

# A continuation is short. Anything longer is a new question that carries
# its own subject, even if it opens with "and".
MAX_CONTINUATION_WORDS = 14

# Openers that signal "keep going with what we were just discussing".
# Bilingual, and matched only at the START of the message: "and why?" is a
# continuation, "explain how the streaming pool and the LOD bias interact"
# is not.
_CONTINUATION_OPENERS: tuple[str, ...] = (
    "y ", "and ", "but ", "pero ", "so ", "entonces", "then ",
    "ok", "vale", "okay", "ya", "aha", "ah ",
    "why", "por que", "por qué", "how come", "y eso", "and that",
    "more", "mas ", "más ", "elaborate", "amplia", "amplía",
    "simpler", "mas simple", "más simple", "in short", "resumelo", "resúmelo",
    "que significa", "qué significa", "what do you mean", "que quieres decir",
    "qué quieres decir", "explain that", "explica eso", "explicame eso",
    "explícame eso",
)

# Bare anaphoric messages — no opener, but nothing to resolve on their own.
_ANAPHORIC_ONLY = re.compile(
    r"^(that|this|it|eso|esto|ese|esa|el mismo|lo mismo|the same)\b",
    re.IGNORECASE,
)

# A message naming a concrete target is NOT a continuation even if short:
# it carries its own subject and deserves a fresh classification.
_NAMES_TARGET = re.compile(r"\b[A-Z]{2,3}\d{3}\b|/|\\|\.(h|cpp|cs|uasset)\b")


def is_continuation(message: str) -> bool:
    """True when *message* only makes sense as a follow-up.

    Conservative on purpose. A false negative costs one re-asked question
    (the user rephrases); a false positive silently answers about the wrong
    subject, which is much harder for a user to notice.
    """
    text = (message or "").strip()
    if not text:
        return False
    if _NAMES_TARGET.search(text):
        return False
    # Naming an OPERATION outright is not a follow-up either, however short
    # the message. "y recuerda que usamos PascalCase" opens with "y" and fits
    # in the word budget, so it inherited the previous turn's intent and the
    # assistant answered the previous question again instead of storing the
    # rule. The user named what they wanted done; there is nothing to inherit.
    from .intent_router import classify_explicit

    if classify_explicit(text) is not None:
        return False
    # Naming a MODULE is naming a target too, and the regex above cannot see
    # it — module names are ordinary words. "y el code validator?" is four
    # words opening with "y", so it read as a follow-up and inherited the
    # previous turn's grounding: the user changed subject and the assistant
    # kept answering about the old one. That is the "it doesn't follow the
    # conversation" complaint, and it is a grounding bug, not a memory one.
    from .module_registry import ALIASES

    lowered_full = text.lower()
    if any(alias in lowered_full for alias, _ in ALIASES):
        return False
    if len(text.split()) > MAX_CONTINUATION_WORDS:
        return False

    lowered = text.lstrip("¿¡(\"' ").lower()
    if _ANAPHORIC_ONLY.match(lowered):
        return True
    return lowered.startswith(_CONTINUATION_OPENERS)


def last_grounding(conversation: dict[str, Any] | None) -> dict[str, str]:
    """What the most recent grounded turn was about.

    Walks backwards for the last turn carrying a real intent, and picks up
    the newest value of each grounding field independently — the user may
    have named the rule two turns ago and the analysis five turns ago, and
    both are still what they mean by "this".

    Returns empty strings for whatever the thread never established.
    """
    found = {"intent": "", "context_ref": "", "rule_id": "", "asset_path": ""}
    if not conversation:
        return found

    for turn in reversed(conversation.get("turns") or []):
        if not isinstance(turn, dict):
            continue
        for key in found:
            if found[key]:
                continue
            value = str(turn.get(key) or "").strip()
            # general_help grounds nothing — inheriting it would turn every
            # follow-up into another recital of the help text.
            if key == "intent" and value == "general_help":
                continue
            if value:
                found[key] = value
        if all(found.values()):
            break
    return found


def _speaker(role: str) -> str:
    return "User" if role == "user" else "Assistant"


def build_history(
    conversation: dict[str, Any] | None,
    summary_text: str = "",
    *,
    turns: int = HISTORY_TURNS,
    skip_last_user_turn: bool = True,
) -> str:
    """Render the thread so far as a bounded block, or "" when there is none.

    ``skip_last_user_turn`` drops the trailing user turn because the caller
    has already appended the message being answered — including it would
    show the model the same question twice, once as history and once as the
    question.
    """
    all_turns = [
        t for t in (conversation or {}).get("turns") or [] if isinstance(t, dict)
    ]
    if skip_last_user_turn and all_turns and all_turns[-1].get("role") == "user":
        all_turns = all_turns[:-1]

    window = all_turns[-turns:] if turns > 0 else []
    summary_text = (summary_text or "").strip()
    if not window and not summary_text:
        return ""

    blocks: list[str] = []
    if summary_text:
        blocks.append("Earlier in this conversation:\n" + summary_text)

    if window:
        lines: list[str] = []
        for turn in window:
            text = str(turn.get("raw_text", "")).strip().replace("\n", " ")
            if not text:
                continue
            if len(text) > MAX_TURN_CHARS:
                text = text[:MAX_TURN_CHARS].rstrip() + "…"
            lines.append(f"{_speaker(str(turn.get('role', '')))}: {text}")
        if lines:
            blocks.append("Recent turns:\n" + "\n".join(lines))

    block = "\n\n".join(blocks)
    if len(block) > MAX_HISTORY_CHARS:
        # Trim from the FRONT: the newest turns are the ones a follow-up is
        # most likely to be about.
        block = "…" + block[-MAX_HISTORY_CHARS:]
    return block
