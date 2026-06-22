# core/modules/agent/explainer.py
#
# Direct LLM explainer — single call, plain text in / plain text out.
#
# This is the production path for the customer-facing "explain this
# issue" feature. It deliberately does NOT use AgentOrchestrator,
# tools, or JSON protocol: with a 1.3B-class model the cost of those
# abstractions outweighs their value, since the deterministic rules
# have already detected the issue and there is nothing to investigate.
#
# Flow:
#   1. Take an enriched issue dict (rule_name, rule_explanation,
#      message, snippet, line, severity, is_auto_fixable, ...).
#   2. Build a small focused prompt that grounds the model in the
#      rule_explanation and the actual snippet.
#   3. Call llm_backend.generate() with stop tokens that prevent the
#      model from elaborating beyond a tight 2-4 sentence response.
#   4. Return the text. The orchestrator + tool path is preserved in
#      this module's siblings for future use cases that genuinely
#      need agentic behaviour.

from __future__ import annotations

import hashlib
import os
import re
import time
from typing import Any, Iterator, Mapping

from .llm_backend import generate as _llm_generate
from .llm_backend import generate_stream as _llm_generate_stream
from .prompts import PromptTemplate, assemble, load_template, resolve_module_engine

# Identifier of the LLM weights currently loaded. Goes into the cache
# key so that swapping the GGUF (e.g. upgrading to a different
# quantisation, or a different model entirely) automatically
# invalidates every cached explanation produced by the old weights.
DEFAULT_MODEL_ID = os.environ.get(
    "SHINTTOOLS_MODEL_FILE", "Qwen2.5-Coder-1.5B-Instruct-Q4_K_M.gguf"
)


def compute_cache_key(prompt: str, model_id: str = DEFAULT_MODEL_ID) -> str:
    """Hash (model_id, prompt) to a stable cache key.

    Including both means a prompt-template change, a docstring update,
    OR a model file change all invalidate cached entries automatically
    — there is no separate "cache version" we have to remember to
    bump.
    """
    digest = hashlib.sha1()
    digest.update(model_id.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(prompt.encode("utf-8"))
    return digest.hexdigest()


# ── Snippet helpers ────────────────────────────────────────────────────────


def _coerce_snippet(issue_dict: Mapping[str, Any]) -> str:
    """Pull the most useful code/context excerpt out of an enriched
    issue dict. Different domains carry different fields:

      - C++ issues (CP/CB/CS/CM): cpp_orchestrator already populates
        `context_before` (a 5-line window around the issue line).
      - Blueprint issues (BP*): no source text exists; the closest
        thing is the `graph` field plus the issue `message` itself.
      - Naming issues (NM*): there is no code at all — just the
        asset_path. We surface that as the "snippet" so the LLM can
        anchor its answer to a concrete asset.

    Returns an empty string when there is nothing useful to show; the
    prompt builder handles that case gracefully.
    """
    cpp_context = issue_dict.get("context_before")
    if isinstance(cpp_context, str) and cpp_context.strip():
        return cpp_context.strip()

    snippet_field = issue_dict.get("snippet")
    if isinstance(snippet_field, str) and snippet_field.strip():
        return snippet_field.strip()

    asset_path = issue_dict.get("asset_path")
    if isinstance(asset_path, str) and asset_path.strip():
        graph_name = issue_dict.get("graph", "")
        if isinstance(graph_name, str) and graph_name and graph_name != "N/A":
            return f"asset: {asset_path}\ngraph: {graph_name}"
        return f"asset: {asset_path}"

    return ""


# ── Prompt builder ─────────────────────────────────────────────────────────


def _build_issue_block(issue_dict: Mapping[str, Any]) -> str:
    """Render the per-issue INPUT block (no system / few-shots).

    Pure function: no I/O. Kept separate from the registry so the
    block layout (field order, snippet indent, label format) stays
    versioned with the code that detects/enriches the issue, while
    the surrounding system + few-shots travel via the YAML registry.
    """
    rule_name = str(issue_dict.get("rule_name") or "Unknown rule").strip()
    rule_explanation = str(issue_dict.get("rule_explanation") or "").strip()
    file_path = str(issue_dict.get("file_path") or "").strip()
    line = issue_dict.get("line", 0)
    is_auto_fixable = bool(issue_dict.get("is_auto_fixable", False))
    short_message = str(issue_dict.get("message") or "").strip()
    snippet = _coerce_snippet(issue_dict)

    issue_block_lines: list[str] = ["INPUT", f"rule_name: {rule_name}"]
    if rule_explanation:
        issue_block_lines.append(f"rule_explanation: {rule_explanation}")
    # is_auto_fixable comes right after rule context so the model reads it
    # before any code snippet and uses it for the closing line.
    issue_block_lines.append(
        f"is_auto_fixable: {'true' if is_auto_fixable else 'false'}"
    )
    if short_message:
        issue_block_lines.append(f"message: {short_message}")
    if file_path:
        issue_block_lines.append(f"file: {file_path}")
    if isinstance(line, int) and line > 0:
        issue_block_lines.append(f"line: {line}")
    if snippet:
        # Indent each snippet line by 4 spaces so the LLM sees a clear
        # boundary between metadata and code.
        indented_snippet = "\n".join(
            "    " + raw_line for raw_line in snippet.splitlines()
        )
        issue_block_lines.append("snippet:")
        issue_block_lines.append(indented_snippet)

    return "\n".join(issue_block_lines)


def _resolve_template(issue_dict: Mapping[str, Any]) -> PromptTemplate:
    """Pick the registry template that applies to this issue.

    Wrapped here so callers (build_explainer_prompt, explain_issue,
    warmup) all go through the same resolution rule.
    """
    module, engine = resolve_module_engine(issue_dict)
    return load_template(module, engine)


def build_explainer_prompt(issue_dict: Mapping[str, Any]) -> str:
    """Assemble the full prompt for a single explanation request.

    Reads the (module, engine) template from the prompt registry,
    renders the per-issue INPUT block, and glues them together. The
    function stays pure modulo registry I/O — tests can call it
    directly to verify a YAML edit changes the rendered output
    without invoking the LLM.
    """
    template = _resolve_template(issue_dict)
    issue_block_text = _build_issue_block(issue_dict)
    return assemble(template, issue_block_text)


# ── Warm-up ───────────────────────────────────────────────────────────────


# Minimal issue used only to build the KV cache for the shared prompt
# prefix (system instruction + few-shots ≈ 900 tokens). The content
# does not matter; what matters is that the prefix is identical to
# every real request so llama.cpp can reuse it.
_WARMUP_ISSUE: dict[str, Any] = {
    "rule_name": "warmup",
    "rule_explanation": "warmup",
    "is_auto_fixable": False,
}


def warmup() -> float:
    """Prime the KV cache by running one dummy inference.

    Call once after load_model() at server startup. The shared prompt
    prefix (system instruction + few-shots) is identical for every
    real request, so this single call amortises the cold-start cost:
    subsequent calls only process the short per-issue suffix (~50-100
    tokens) instead of the full ~1 100-token prompt.

    The prompt is assembled from the registry — same code path
    /agent/explain takes, so a YAML edit warms up the actual prefix
    requests will hit. If a future change makes one engine's template
    a hot-path, warm-up will pick it up automatically the next time
    the server restarts.

    Returns elapsed seconds so the caller can log the warm-up time.
    """
    prompt = build_explainer_prompt(_WARMUP_ISSUE)
    t0 = time.perf_counter()
    _llm_generate(prompt, max_tokens=1, temperature=0.0, stop=[])
    return time.perf_counter() - t0


# ── Public API ─────────────────────────────────────────────────────────────


# Stops tuned for single-paragraph plain-text explanations. The model
# should write 2-4 sentences in ONE paragraph and stop. The defining
# stop is `\n\n` (a blank line) — empirically the model writes a clean
# closing sentence and then either:
#   (a) starts another paragraph of chatty filler ("I hope this helps…")
#   (b) starts a new INPUT/EXPLANATION block mimicking the few-shots.
# Both manifest as `\n\n` first, so cutting there gives us the clean
# first paragraph with no follow-on noise.
#
# `\n\n` is safe in this prompt because the model emits substantive
# text BEFORE any newline — the EXPLANATION cue ends with a single
# `\n`, not a blank line, so the first generated tokens are content,
# not whitespace.
_EXPLAINER_STOPS: list[str] = [
    "\n\n",
    "\n```",
]

# Prose anti-repetition. The 1.5B model, left at llama-cpp's mild 1.1 default,
# loops into long repetitive paragraphs ("largo y repetitivo" bug). 1.3 keeps a
# tight 2-4 sentence answer without the model echoing itself. Only the explainer
# uses this — the JSON-structured custom_rule_checker keeps the gentle default
# so its legitimate punctuation repetition isn't penalised.
_EXPLAINER_REPEAT_PENALTY: float = 1.3

# The mandated closing line for non-auto-fixable issues (see the few-shots in
# prompts/templates/**/v1.yaml). When the model runs away it tends to repeat
# this; we cut everything after its first occurrence.
_MANDATED_CLOSING: str = "You must fix this manually."


def _resolve_generation_params(
    issue_dict: Mapping[str, Any],
    max_tokens: int | None,
    temperature: float | None,
) -> tuple[str, int, float, list[str]]:
    """Render the prompt and pick max_tokens/temperature/stop_tokens.

    Explicit overrides (when not None) win over the template; the
    template values win over the legacy fallback. This is what lets a
    YAML edit change generation behaviour with no Python change while
    still letting callers (warm-up, tests) pin a value.
    """
    template = _resolve_template(issue_dict)
    issue_block_text = _build_issue_block(issue_dict)
    rendered_prompt = assemble(template, issue_block_text)
    effective_max = max_tokens if max_tokens is not None else template.max_tokens
    effective_temp = temperature if temperature is not None else template.temperature
    effective_stop: list[str] = (
        list(template.stop_tokens) if template.stop_tokens else list(_EXPLAINER_STOPS)
    )
    return rendered_prompt, effective_max, effective_temp, effective_stop


def _dedupe_sentences(text: str) -> str:
    """Collapse immediately-repeated sentences a small model emits when it
    loops. Preserves order; drops a sentence only when it is identical
    (case-insensitive, whitespace-folded) to the one just kept, so distinct
    advice is never lost.
    """
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    kept: list[str] = []
    last_norm = ""
    for part in parts:
        norm = " ".join(part.lower().split())
        if norm and norm != last_norm:
            kept.append(part)
            last_norm = norm
    return " ".join(kept)


def _trim_to_last_sentence(text: str) -> str:
    """Clean up a raw completion: cut runaway repetition, then truncate to the
    last complete sentence.

    Three guards, in order:
      1. If the mandated closing line appears, drop everything after its first
         occurrence — a second copy (or trailing ramble) means the model ran
         away past the point it was told to stop.
      2. Collapse immediately-repeated sentences (`_dedupe_sentences`).
      3. If the result still ends mid-sentence (the model hit max_tokens), cut
         back to the last '.', '!' or '?' so the caller never gets a dangling
         fragment. If no boundary is found, return the stripped text as-is —
         better a fragment than an empty string.
    """
    text = text.strip()
    if not text:
        return text

    closing_at = text.find(_MANDATED_CLOSING)
    if closing_at != -1:
        text = text[: closing_at + len(_MANDATED_CLOSING)]

    text = _dedupe_sentences(text).strip()
    if not text:
        return text

    # Already ends with sentence-closing punctuation — nothing to trim.
    if text[-1] in ".!?":
        return text
    # Find the rightmost sentence boundary.
    last = max(text.rfind("."), text.rfind("!"), text.rfind("?"))
    if last > 0:
        return text[: last + 1]
    return text


def explain_issue(
    issue_dict: Mapping[str, Any],
    *,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> str:
    """Generate a short customer-facing explanation for one issue.

    Inputs:
        issue_dict: an enriched issue (must have at minimum `rule_name`
            and `rule_explanation`; everything else is optional and
            improves grounding when present).
        max_tokens: cap on generated tokens. ``None`` (default) reads
            the value from the registry template. Pass an int to
            override for one call.
        temperature: sampling temperature. ``None`` (default) reads
            the value from the registry template.

    Returns the trimmed explanation text. Never raises on a bad model
    output — at worst returns an empty string and the caller decides
    how to surface that to the user.
    """
    rendered_prompt, effective_max, effective_temp, effective_stop = (
        _resolve_generation_params(issue_dict, max_tokens, temperature)
    )
    raw_completion = _llm_generate(
        rendered_prompt,
        max_tokens=effective_max,
        temperature=effective_temp,
        stop=effective_stop,
        repeat_penalty=_EXPLAINER_REPEAT_PENALTY,
    )
    return _trim_to_last_sentence(raw_completion)


def explain_issue_stream(
    issue_dict: Mapping[str, Any],
    *,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> Iterator[str]:
    """Stream a customer-facing explanation token-by-token.

    Same inputs and stop semantics as ``explain_issue``, but yields
    text chunks as they come off the model instead of waiting for the
    full response. Used by the /agent/explain/stream SSE endpoint so
    the plugin can show the explanation flowing into the UI rather
    than spinning for 20-40 s with nothing on screen.

    The caller is responsible for concatenating the chunks if it
    needs the full text (e.g. to write to the MongoDB cache once the
    stream has finished).
    """
    rendered_prompt, effective_max, effective_temp, effective_stop = (
        _resolve_generation_params(issue_dict, max_tokens, temperature)
    )
    for chunk in _llm_generate_stream(
        rendered_prompt,
        max_tokens=effective_max,
        temperature=effective_temp,
        stop=effective_stop,
        repeat_penalty=_EXPLAINER_REPEAT_PENALTY,
    ):
        yield chunk
