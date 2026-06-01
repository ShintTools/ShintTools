# core/modules/agent/custom_rule_checker.py
#
# LLM-based checker for user-defined (natural-language) rules.
#
# Flow per rule:
#   1. Python pre-filter  — drop files that obviously don't apply.
#   2. Batch             — split surviving files into groups of N.
#   3. LLM call          — one prompt per batch: RULE + FILES → JSON array.
#   4. Parse             — extract violations from JSON, discard malformed
#                          entries without raising.
#
# KV-cache strategy: system prompt + few-shots + rule description form a
# constant prefix across every batch for the same rule, so llama.cpp
# reuses the cached prefix keys/values and only processes the short
# per-batch file section on each call.
#
# Context budget (n_ctx=4096 default):
#   System + few-shots  : ~500 tokens
#   Rule description    : ~60 tokens
#   3 files × 300 tok   : ~900 tokens
#   Response            : ~300 tokens
#   ─────────────────────────────────
#   Total               : ~1760 / 4096  ← comfortable headroom

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .llm_backend import generate as _llm_generate
from .prompts.registry import PromptTemplate, load_template

# ── Public data types ──────────────────────────────────────────────────────


@dataclass
class CustomRule:
    """A user-defined rule expressed in natural language."""

    name: str
    description: str
    example_violation: str = ""  # optional — improves few-shot grounding


@dataclass
class RuleViolation:
    """One finding produced by the LLM for a (rule, file) pair."""

    file_path: str
    rule_name: str
    finding: str
    fix_suggestion: str
    line: int = 0  # 0 when the model cannot pinpoint an exact line


# ── Public API ─────────────────────────────────────────────────────────────


def check_custom_rules(
    rules: list[CustomRule],
    files: list[tuple[str, str]],
    *,
    batch_size: int = 3,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> list[RuleViolation]:
    """Check a list of user-defined rules against a set of source files.

    Args:
        rules:       Natural-language rules to enforce.
        files:       ``(file_path, content)`` pairs to check.
        batch_size:  Files per LLM call. Default 3 keeps the prompt well
                     within the 4096-token context window.
        max_tokens:  Override the template's max_tokens for generation.
        temperature: Override the template's temperature.

    Returns:
        Flat list of :class:`RuleViolation` objects. One entry per
        finding; a clean file produces no entries.
    """
    template = load_template("custom_rule_checker", "generic")
    effective_max = max_tokens if max_tokens is not None else template.max_tokens
    effective_temp = temperature if temperature is not None else template.temperature

    results: list[RuleViolation] = []
    for rule in rules:
        relevant = _prefilter_files(rule, files)
        for i in range(0, len(relevant), batch_size):
            batch = relevant[i : i + batch_size]
            violations = _check_rule_batch(
                rule,
                batch,
                template,
                max_tokens=effective_max,
                temperature=effective_temp,
            )
            results.extend(violations)

    return results


# ── Pre-filter ─────────────────────────────────────────────────────────────

_STOP_WORDS: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "that",
        "this",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "not",
        "no",
        "any",
        "all",
        "each",
        "every",
        "both",
        "either",
        "code",
        "file",
        "files",
        "rule",
        "rules",
        "check",
        "should",
        "when",
        "where",
        "what",
        "which",
        "these",
        "those",
        "their",
        "them",
        "they",
        "then",
        "than",
        "also",
        "only",
        "more",
        "some",
    }
)


def _extract_keywords(rule: CustomRule) -> frozenset[str]:
    """Pull meaningful words out of the rule to use as a pre-filter.

    Tokens must be at least 5 characters and not in the stop-word list.
    Returns an empty set when no useful keywords can be extracted (the
    caller then keeps all files rather than over-filtering).
    """
    raw = f"{rule.name} {rule.description} {rule.example_violation}"
    tokens = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{4,}\b", raw)
    return frozenset(t.lower() for t in tokens if t.lower() not in _STOP_WORDS)


def _prefilter_files(
    rule: CustomRule,
    files: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Discard files that are obviously irrelevant to the rule.

    A file is kept if its content (case-insensitive) contains at least
    one keyword extracted from the rule. If no keywords can be extracted,
    or if the filter would drop every file, all files are kept — we
    prefer false positives (extra LLM calls) over false negatives (missed
    violations).
    """
    keywords = _extract_keywords(rule)
    if not keywords:
        return files

    kept = [
        (fp, content)
        for fp, content in files
        if any(kw in content.lower() for kw in keywords)
    ]
    return kept if kept else files


# ── Prompt builder ─────────────────────────────────────────────────────────


def _build_files_section(batch: list[tuple[str, str]]) -> str:
    parts = [f"--- file: {fp} ---\n{content.strip()}" for fp, content in batch]
    return "\n\n".join(parts)


def _build_checker_prompt(
    rule: CustomRule,
    batch: list[tuple[str, str]],
    template: PromptTemplate,
) -> str:
    """Assemble the full checker prompt.

    Layout:
        <system>

        <few-shots>

        RULE
        name: …
        description: …
        [example_violation: …]

        FILES
        --- file: path ---
        content
        …

        OUTPUT
    """
    parts: list[str] = [template.system.rstrip()]

    few_shots = template.few_shots.strip()
    if few_shots:
        parts.append(few_shots)

    rule_block = f"RULE\nname: {rule.name}\ndescription: {rule.description}"
    if rule.example_violation:
        rule_block += f"\nexample_violation: {rule.example_violation}"

    files_section = _build_files_section(batch)
    parts.append(f"{rule_block}\n\nFILES\n{files_section}")

    return "\n\n".join(parts) + "\n\nOUTPUT\n"


# ── JSON parser ────────────────────────────────────────────────────────────


def _extract_json_objects(text: str) -> list[dict]:
    """Extract every complete ``{…}`` object from ``text``.

    Used to recover partial results when the model hits max_tokens
    mid-array and the closing ``]`` is missing or the trailing object
    is truncated. A brace-depth scanner collects every syntactically
    complete object and hands them to ``json.loads`` individually.
    """
    objects: list[dict] = []
    depth = 0
    obj_start: int | None = None

    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and obj_start is not None:
                try:
                    obj = json.loads(text[obj_start : i + 1])
                    if isinstance(obj, dict):
                        objects.append(obj)
                except json.JSONDecodeError:
                    pass
                obj_start = None

    return objects


def _build_violations(
    items: list[Any],
    rule_name: str,
    valid_paths: frozenset[str],
) -> list[RuleViolation]:
    """Validate and convert raw dicts to :class:`RuleViolation` objects."""
    violations: list[RuleViolation] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        file_path = str(item.get("file", "")).strip()
        finding = str(item.get("finding", "")).strip()
        if not file_path or not finding:
            continue
        if file_path not in valid_paths:
            continue  # hallucinated path — discard
        raw_line = item.get("line", 0)
        try:
            line = int(raw_line)
        except (TypeError, ValueError):
            line = 0
        violations.append(
            RuleViolation(
                file_path=file_path,
                rule_name=rule_name,
                finding=finding,
                fix_suggestion=str(item.get("fix", "")).strip(),
                line=line,
            )
        )
    return violations


def _parse_violations(
    raw: str,
    rule_name: str,
    batch: list[tuple[str, str]],
) -> list[RuleViolation]:
    """Extract :class:`RuleViolation` objects from raw LLM output.

    Intentionally defensive — never raises. Invalid items are silently
    dropped so a single bad token doesn't discard the whole batch result.

    Strategy:
      1. Try ``json.loads`` on the first ``[…]`` substring (fast path).
      2. If that fails (truncated or malformed), extract every complete
         ``{…}`` object individually and validate them (recovery path).
    """
    array_start = raw.find("[")
    if array_start == -1:
        return []

    valid_paths = frozenset(fp for fp, _ in batch)
    text = raw[array_start:]

    # Fast path — well-formed array.
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return _build_violations(data, rule_name, valid_paths)
    except json.JSONDecodeError:
        pass

    # Recovery path — truncated or partially malformed array.
    objects = _extract_json_objects(text)
    if objects:
        return _build_violations(objects, rule_name, valid_paths)

    return []


# ── Batch runner ───────────────────────────────────────────────────────────


def _check_rule_batch(
    rule: CustomRule,
    batch: list[tuple[str, str]],
    template: PromptTemplate,
    *,
    max_tokens: int,
    temperature: float,
) -> list[RuleViolation]:
    """Run one (rule, file-batch) LLM call and return parsed violations."""
    if not batch:
        return []

    prompt = _build_checker_prompt(rule, batch, template)
    stop = list(template.stop_tokens) if template.stop_tokens else ["\n\n"]

    raw = _llm_generate(
        prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        stop=stop,
    )

    return _parse_violations(raw, rule.name, batch)
