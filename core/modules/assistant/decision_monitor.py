# core/modules/assistant/decision_monitor.py
#
# "You decided Nanite on characters last month — why doesn't this mesh
# have it?"
#
# The trigger is deterministic Python, never the model: confirmed facts
# are matched against a scan's findings by shared terms, and a contradiction
# is reported only when a fact and a finding talk about the same thing.
# The LLM's role, if any, is wording — it cannot decide that a
# contradiction exists, and it never sees a fact the user hasn't confirmed.
#
# Precision over recall on purpose: a wrong "you contradicted yourselves"
# is far more corrosive to trust than a missed one.

from __future__ import annotations

import re
from typing import Any

from . import memory_store

# A fact only contradicts a finding if they share a distinctive term.
_STOPWORDS = frozenset(
    "the a an of on in for to and or que de la el los las un una y o con "
    "usamos usan use uses using all todos todas every para por".split()
)

# How many shared distinctive terms make a match. Two is deliberately
# strict: "texture" alone must not pair every fact with every finding.
_MIN_SHARED_TERMS = 2


def _terms(text: str) -> set[str]:
    return {
        w
        for w in re.findall(r"[a-záéíóúñü0-9_]+", (text or "").lower())
        if len(w) > 3 and w not in _STOPWORDS
    }


def _finding_text(finding: dict[str, Any]) -> str:
    return " ".join(
        str(finding.get(k, ""))
        for k in ("rule_name", "message", "asset_path", "file")
    )


def find_contradictions(
    facts: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Pairs of (confirmed fact, finding) that talk about the same thing.

    Pure function — no I/O, no model. The caller supplies already-confirmed
    facts; this never reads memory itself, so a proposed fact cannot leak
    into a proactive nudge.
    """
    pairs: list[dict[str, Any]] = []
    for fact in facts:
        fact_terms = _terms(fact.get("value", ""))
        if len(fact_terms) < _MIN_SHARED_TERMS:
            continue
        for finding in findings:
            shared = fact_terms & _terms(_finding_text(finding))
            if len(shared) >= _MIN_SHARED_TERMS:
                pairs.append(
                    {
                        "fact_id": fact.get("fact_id", ""),
                        "fact_value": fact.get("value", ""),
                        "rule_id": finding.get("rule_id", ""),
                        "asset_path": finding.get("asset_path")
                        or finding.get("file", ""),
                        "message": finding.get("message", ""),
                        "shared_terms": sorted(shared),
                    }
                )
    pairs.sort(key=lambda p: -len(p["shared_terms"]))
    return pairs[:limit]


def render(pair: dict[str, Any]) -> str:
    """One-line nudge. Deterministic — the facts speak for themselves."""
    where = pair.get("asset_path") or "this asset"
    return (
        f'Your team noted: "{pair["fact_value"]}". '
        f"{where} was just flagged: {pair['message']}"
    )


async def check_scan(
    studio_id: str,
    project_id: str,
    findings: list[dict[str, Any]],
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Contradictions between a studio's CONFIRMED memory and a scan."""
    if not studio_id or not findings:
        return []
    facts = await memory_store.confirmed_facts(studio_id, project_id)
    if not facts:
        return []
    pairs = find_contradictions(facts, findings, limit=limit)
    for pair in pairs:
        pair["nudge"] = render(pair)
    return pairs
