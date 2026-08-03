# core/modules/assistant/rule_runner.py
#
# Scan-side entry point: evaluate a studio's active rules over the files
# of a scan. Called from the validate routes as a best-effort add-on —
# studio rules failing must never break the built-in scan.
#
# Template rules run deterministically (rule_templates). LLM rules reuse
# custom_rule_checker's semantics with the eval cache in front: an
# unchanged file under an unchanged rule never re-invokes the model.

from __future__ import annotations

import logging
from typing import Any

from . import rule_store
from .rule_templates import evaluate_template_rule

logger = logging.getLogger("shinttools.assistant.rules")


def _llm_available() -> bool:
    try:
        from modules.agent.llm_backend import is_loaded

        return is_loaded()
    except ImportError:
        return False


async def _evaluate_llm_rule(
    rule: dict[str, Any], files: list[tuple[str, str]]
) -> list[dict[str, Any]]:
    version = int(rule.get("version", 1))
    rule_id = rule["rule_id"]

    pending: list[tuple[str, str]] = []
    out: list[dict[str, Any]] = []
    for path, content in files:
        key = rule_store.eval_cache_key(rule_id, version, content or "")
        cached = await rule_store.get_cached_eval(key)
        if cached is not None:
            out.extend(cached)
        else:
            pending.append((path, content))

    if not pending or not _llm_available():
        # No model: pending files are skipped this scan, cache still serves
        # what it has. Honest degradation, never a guess.
        return out

    try:
        from modules.agent.custom_rule_checker import (
            CustomRule,
            check_custom_rules,
        )
        from modules.agent.llm_backend import _LLAMA_LOCK

        llm_rule = rule.get("llm_rule") or {}
        custom = CustomRule(
            name=rule.get("name", rule_id),
            description=str(llm_rule.get("description", "")),
            example_violation=str(llm_rule.get("example_violation", "")),
        )
        with _LLAMA_LOCK:
            violations = check_custom_rules([custom], pending)
        by_file: dict[str, list[dict[str, Any]]] = {p: [] for p, _ in pending}
        for violation in violations:
            doc = {
                "rule_id": "STUDIO",
                "rule_name": rule.get("name", rule_id),
                "file": violation.file_path,
                "line": violation.line,
                "severity": "warning",
                "message": violation.message,
                "auto_fixable": False,
                "source": "studio_rule",
            }
            by_file.setdefault(violation.file_path, []).append(doc)
            out.append(doc)
        # Cache per file — including the empty results, which are the
        # common case and the whole point of the cache.
        for path, content in pending:
            key = rule_store.eval_cache_key(rule_id, version, content or "")
            await rule_store.save_cached_eval(key, by_file.get(path, []))
    except Exception:  # noqa: BLE001 — studio rules never break a scan
        logger.exception("LLM studio rule %s failed", rule_id)

    return out


async def evaluate_studio_rules(
    studio_id: str,
    project_id: str,
    engine: str,
    files: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    """All active+confirmed studio rules over the scan's files."""
    if not studio_id or not files:
        return []
    try:
        rules = await rule_store.active_rules(studio_id, project_id, engine)
    except Exception:  # noqa: BLE001
        return []

    out: list[dict[str, Any]] = []
    for rule in rules:
        try:
            if rule.get("tier") == "template":
                out.extend(evaluate_template_rule(rule, files))
            else:
                out.extend(await _evaluate_llm_rule(rule, files))
        except Exception:  # noqa: BLE001
            logger.exception("studio rule %s failed", rule.get("rule_id"))
    return out
