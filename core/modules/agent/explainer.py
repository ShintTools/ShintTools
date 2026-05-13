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
from typing import Any, Iterator, Mapping

from .llm_backend import generate as _llm_generate
from .llm_backend import generate_stream as _llm_generate_stream

# Identifier of the LLM weights currently loaded. Goes into the cache
# key so that swapping the GGUF (e.g. upgrading to a different
# quantisation, or a different model entirely) automatically
# invalidates every cached explanation produced by the old weights.
DEFAULT_MODEL_ID = os.environ.get(
    "SHINTTOOLS_MODEL_FILE", "deepseek-coder-1.3b-instruct.Q4_K_M.gguf"
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


_SYSTEM_INSTRUCTION = (
    "You are a senior UE5 engineer reviewing a teammate's code. "
    "ShintTools' deterministic rules already detected the issue below "
    "— your one job is to explain in your own words why it matters and "
    "what they should do next, the way you would say it out loud at a "
    "desk.\n"
    "\n"
    "Style:\n"
    "  - Friendly and conversational, not a compliance report. Speak"
    " in the second person ('your code', 'you call', 'you should').\n"
    "  - 2 to 4 short sentences in English. No headings, no bullet"
    " lists, no code fences.\n"
    "  - Active voice. Avoid 'is made', 'is called', 'the dereferencing"
    " of'. Prefer 'you call', 'you dereference', 'your code does X'.\n"
    "\n"
    "Rules:\n"
    "  - Refer to the rule by its rule_name in **bold markdown**."
    " Never mention the internal rule_id (e.g. CS001).\n"
    "  - Ground every claim in the rule_explanation provided below."
    " Do not invent UE5 APIs, classes, macros, contexts, or behaviours"
    " that the explanation does not mention. If the explanation lists"
    " specific contexts (e.g. 'editor utilities, commandlets, or"
    " shutdown'), use exactly those words — do not add others.\n"
    "  - You may quote tiny code pieces inline with `backticks` (one"
    " expression at most). Do not rewrite the snippet, do not produce"
    " multi-line code blocks.\n"
    "  - Close with a one-line action: if is_auto_fixable is true, say"
    " ShintTools' Auto-Fix can apply it for them; otherwise say it"
    " must be fixed manually (in the UE5 editor for Blueprints, via"
    " an AssetRegistry rename for Naming)."
)

# Two few-shots: one C++ auto-fixable case, one Blueprint manual-fix
# case. Two examples teach the model both endings of the closing line
# (Auto-Fix vs manual fix) and both input shapes (file_content snippet
# vs asset_path/graph). Every claim in each EXPLANATION is rooted in
# its rule_explanation — adding novel context here would teach the
# model to hallucinate, defeating the whole purpose.
#
# The label format is identical to the live issue block ("INPUT" /
# "EXPLANATION") so the small model sees a single consistent pattern
# instead of switching between "EXAMPLE N INPUT" and "INPUT".
_FEW_SHOT_EXAMPLE = (
    "INPUT\n"
    "rule_name: GetWorld without null-check\n"
    "rule_explanation: GetWorld() can return nullptr in editor "
    "utilities, commandlets, or during shutdown. Always guard with "
    "'if (UWorld* W = GetWorld())' before dereferencing.\n"
    "file: MyActor.cpp\n"
    "line: 12\n"
    "is_auto_fixable: true\n"
    "snippet:\n"
    "    UWorld* World = GetWorld();\n"
    "    AActor* Spawned = World->SpawnActor<AActor>(SpawnClass);\n"
    "\n"
    "EXPLANATION\n"
    "Your `BeginPlay` grabs `GetWorld()` and uses the pointer straight "
    "away — that's the **GetWorld without null-check** pattern. The "
    "world can come back null in editor utilities, commandlets, or "
    "during shutdown, so dereferencing it without a guard is unsafe. "
    "Capture and check it first with `if (UWorld* W = GetWorld())`. "
    "ShintTools' Auto-Fix can rewrite this for you when you accept it.\n"
    "\n"
    "INPUT\n"
    "rule_name: Missing authority check before action\n"
    "rule_explanation: flag Blueprints that modify replicated "
    "variables without a HasAuthority or SwitchHasAuthority guard. "
    "In multiplayer, only the server should modify replicated state. "
    "Clients writing replicated variables directly can cause desync, "
    "cheating, or server rejection.\n"
    "file: /Game/Blueprints/BP_PlayerInventory\n"
    "is_auto_fixable: false\n"
    "snippet:\n"
    "    asset: /Game/Blueprints/BP_PlayerInventory\n"
    "    graph: EventGraph\n"
    "\n"
    "EXPLANATION\n"
    "Your `BP_PlayerInventory` modifies a replicated variable in "
    "EventGraph without first checking authority — that's the "
    "**Missing authority check before action** pattern. In multiplayer "
    "only the server should modify replicated state; clients writing "
    "to it directly can cause desync, cheating, or server rejection. "
    "Gate the Set node behind a `HasAuthority` or `SwitchHasAuthority` "
    "branch. There is no Auto-Fix for Blueprint nodes — open the "
    "Blueprint in the UE5 editor and add the guard manually."
)


def build_explainer_prompt(issue_dict: Mapping[str, Any]) -> str:
    """Assemble the prompt for a single explanation request.

    Pure function: no I/O. Tests can call this directly to verify the
    rendered prompt is grounded in the issue without invoking the LLM.
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
    if short_message:
        issue_block_lines.append(f"message: {short_message}")
    if file_path:
        issue_block_lines.append(f"file: {file_path}")
    if isinstance(line, int) and line > 0:
        issue_block_lines.append(f"line: {line}")
    issue_block_lines.append(
        f"is_auto_fixable: {'true' if is_auto_fixable else 'false'}"
    )
    if snippet:
        # Indent each snippet line by 4 spaces so the LLM sees a clear
        # boundary between metadata and code.
        indented_snippet = "\n".join(
            "    " + raw_line for raw_line in snippet.splitlines()
        )
        issue_block_lines.append("snippet:")
        issue_block_lines.append(indented_snippet)

    issue_block_text = "\n".join(issue_block_lines)

    # The prompt ends with "EXPLANATION" on its own line so the model
    # continues from there. Stop tokens cut off any follow-on noise
    # (a second "INPUT" block, markdown headings, code fences).
    return (
        f"{_SYSTEM_INSTRUCTION}\n\n"
        f"{_FEW_SHOT_EXAMPLE}\n\n"
        f"{issue_block_text}\n\n"
        f"EXPLANATION\n"
    )


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


def explain_issue(
    issue_dict: Mapping[str, Any],
    *,
    max_tokens: int = 220,
    temperature: float = 0.2,
) -> str:
    """Generate a short customer-facing explanation for one issue.

    Inputs:
        issue_dict: an enriched issue (must have at minimum `rule_name`
            and `rule_explanation`; everything else is optional and
            improves grounding when present).
        max_tokens: cap on generated tokens. 220 fits ~3-4 sentences
            comfortably; anything larger is the model rambling.
        temperature: low default keeps the output stable and on-topic.

    Returns the trimmed explanation text. Never raises on a bad model
    output — at worst returns an empty string and the caller decides
    how to surface that to the user.
    """
    rendered_prompt = build_explainer_prompt(issue_dict)
    raw_completion = _llm_generate(
        rendered_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        stop=_EXPLAINER_STOPS,
    )
    return raw_completion.strip()


def explain_issue_stream(
    issue_dict: Mapping[str, Any],
    *,
    max_tokens: int = 220,
    temperature: float = 0.2,
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
    rendered_prompt = build_explainer_prompt(issue_dict)
    for chunk in _llm_generate_stream(
        rendered_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        stop=_EXPLAINER_STOPS,
    ):
        yield chunk
