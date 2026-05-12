# core/modules/agent/prefab_explanations.py
#
# Prefab (pre-generated) customer-facing explanations for the 114
# detector rules. Two entries per rule × 114 rules = 228 entries.
#
# Why this exists:
#   The local DeepSeek 1.3B model takes 20-40 s on CPU to produce one
#   explanation. The prefabs were authored offline by Claude Opus 4.7
#   (see core/scripts/generate_prefab_cache.py) and capture the same
#   tone and structure we want from the live explainer — but they
#   resolve in microseconds because they live in memory.
#
#   Resolution order in /agent/explain (and /agent/explain/stream):
#     1) prefab lookup by rule_id      → ~µs, served from this module
#     2) MongoDB explanation_cache     → ~ms, served if we've run the
#                                        LLM on this exact prompt
#                                        within the last 90 days
#     3) live local LLM call           → 20-40 s on CPU
#
# The prefab snippets are synthetic and may not match the customer's
# real code, so the plugin should label the explanation accordingly
# (the response's `source` field tells it which path served the
# answer). A future iteration can rank the 2 entries per rule against
# the user's snippet to pick the closer one; v1 returns example_num=1
# deterministically.

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("shinttools.agent.prefab")

# data/prefabricated_explanations.json lives at the project root.
# This file is at core/modules/agent/prefab_explanations.py so we go
# up three parents to reach the repo root.
_PREFAB_FILE = (
    Path(__file__).resolve().parents[3] / "data" / "prefabricated_explanations.json"
)

# Cached on first access. Each value is the list of prefab entries for
# that rule_id (always 2 today, but the loader doesn't assume a count).
_PREFAB_INDEX: dict[str, list[dict]] = {}
_LOAD_ATTEMPTED = False


def _load_index() -> dict[str, list[dict]]:
    """Lazy-load the prefab JSON into an in-memory index keyed by rule_id.

    Safe to call repeatedly: the first successful load populates the
    module-level cache and every subsequent call is a dict-return. A
    failed load (missing file, malformed JSON) is logged once and the
    empty index is returned — every prefab lookup will then miss and
    the request falls through to the MongoDB cache / live LLM path.
    """
    global _LOAD_ATTEMPTED
    if _PREFAB_INDEX or _LOAD_ATTEMPTED:
        return _PREFAB_INDEX
    _LOAD_ATTEMPTED = True

    if not _PREFAB_FILE.exists():
        logger.warning(
            "prefab cache file not found at %s — prefab lookups will "
            "all miss and the LLM path will run for every request. "
            "Re-run `python core/scripts/generate_prefab_cache.py` to "
            "regenerate it.",
            _PREFAB_FILE,
        )
        return _PREFAB_INDEX

    try:
        with open(_PREFAB_FILE, "r", encoding="utf-8") as f:
            entries = json.load(f)
    except Exception as exc:
        logger.error(
            "prefab cache load FAILED (%s) — fallback to MongoDB / LLM path.",
            exc,
        )
        return _PREFAB_INDEX

    index: dict[str, list[dict]] = {}
    for entry in entries:
        rule_id = entry.get("rule_id")
        if not rule_id:
            continue
        index.setdefault(rule_id, []).append(entry)

    # Stable order within each rule so lookup_prefab is deterministic.
    for rule_id in index:
        index[rule_id].sort(key=lambda e: e.get("example_num", 0))

    _PREFAB_INDEX.update(index)
    logger.info(
        "prefab cache loaded: %d entries across %d rules from %s",
        len(entries),
        len(index),
        _PREFAB_FILE,
    )
    return _PREFAB_INDEX


def lookup_prefab(rule_id: str) -> dict | None:
    """Return the first prefab entry for *rule_id* or None on miss.

    The returned dict carries the schema produced by
    core/scripts/generate_prefab_cache.py:
        rule_id, rule_name, example_num, complexity, domain,
        snippet, explanation, generated_with, created_at.
    """
    if not rule_id:
        return None
    index = _load_index()
    entries = index.get(rule_id)
    if not entries:
        return None
    return entries[0]


def is_loaded() -> bool:
    """True when the prefab index has at least one entry loaded."""
    return bool(_load_index())


def get_stats() -> dict:
    """Coverage stats for /agent/explain admin / health checks."""
    index = _load_index()
    total = sum(len(v) for v in index.values())
    return {
        "rule_count": len(index),
        "total_entries": total,
        "source_file": str(_PREFAB_FILE),
    }
