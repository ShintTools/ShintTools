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
import time
from typing import Any, Iterator, Mapping

from .llm_backend import generate as _llm_generate
from .llm_backend import generate_stream as _llm_generate_stream
from .model_config import detect_config_from_env

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


def _get_system_instruction() -> str:
    """Get the system instruction for the currently configured model.

    This allows future model swaps to use prompts tuned for their
    instruction style without code duplication.
    """
    config = detect_config_from_env()
    return config.system_prompt


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
    "is_auto_fixable: true\n"
    "file: MyActor.cpp\n"
    "line: 12\n"
    "snippet:\n"
    "    UWorld* World = GetWorld();\n"
    "    AActor* Spawned = World->SpawnActor<AActor>(SpawnClass);\n"
    "\n"
    "EXPLANATION\n"
    "Your `BeginPlay` grabs `GetWorld()` and uses the pointer straight "
    "away without a null check. The world can come back null in editor "
    "utilities, commandlets, or during shutdown, so dereferencing it "
    "without a guard is unsafe. Capture and check it first with "
    "`if (UWorld* W = GetWorld())`. "
    "ShintTools' Auto-Fix can apply it for you.\n"
    "\n"
    "INPUT\n"
    "rule_name: Missing authority check before action\n"
    "rule_explanation: flag Blueprints that modify replicated "
    "variables without a HasAuthority or SwitchHasAuthority guard. "
    "In multiplayer, only the server should modify replicated state. "
    "Clients writing replicated variables directly can cause desync, "
    "cheating, or server rejection.\n"
    "is_auto_fixable: false\n"
    "file: /Game/Blueprints/BP_PlayerInventory\n"
    "snippet:\n"
    "    asset: /Game/Blueprints/BP_PlayerInventory\n"
    "    graph: EventGraph\n"
    "\n"
    "EXPLANATION\n"
    "Your `BP_PlayerInventory` modifies a replicated variable in "
    "EventGraph without first checking authority. In multiplayer "
    "only the server should modify replicated state; clients writing "
    "to it directly can cause desync, cheating, or server rejection. "
    "Gate the Set node behind a `HasAuthority` or `SwitchHasAuthority` "
    "branch. You must fix this manually.\n"
    "\n"
    "INPUT\n"
    "rule_name: Hard-coded secret in source\n"
    "rule_explanation: Hard-coded secret literal found in source code. "
    "Secrets committed to version control can be leaked via git history "
    "even after deletion. Move them to environment variables or a "
    "secrets manager.\n"
    "is_auto_fixable: false\n"
    "file: Assets/Scripts/Analytics/AnalyticsService.cs\n"
    "line: 12\n"
    "snippet:\n"
    '    private const string api_key = "sk-prod-4f8a2c91b";\n'
    "\n"
    "EXPLANATION\n"
    "Your `AnalyticsService.cs` stores the API key as a plain string "
    "literal in source. Anyone who can read the git history can recover "
    "that value even if you delete the line later, so it needs to leave "
    "the source file entirely. Move it to an environment variable or a "
    "secrets manager and read it at runtime. You must fix this manually.\n"
    "\n"
    "INPUT\n"
    "rule_name: Asset missing type prefix\n"
    "rule_explanation: UE5 conventions require every asset to start "
    "with a short prefix identifying its class: SM_ for Static Meshes, "
    "T_ for Textures, M_ for Materials, BP_ for Blueprints. Without a "
    "prefix, assets are hard to find by type in the Content Browser "
    "and risk colliding with other assets when referenced by name.\n"
    "is_auto_fixable: true\n"
    "snippet:\n"
    "    asset: /Game/Characters/HeroSword\n"
    "\n"
    "EXPLANATION\n"
    "Your `HeroSword` asset has no type prefix. UE5 conventions require "
    "every asset to start with a short prefix so the Content Browser "
    "stays navigable and assets don't collide when referenced by name "
    "in code. Add `SM_` before the name to match its Static Mesh type. "
    "ShintTools' Auto-Fix can apply it for you."
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

    issue_block_text = "\n".join(issue_block_lines)

    # The prompt ends with "EXPLANATION" on its own line so the model
    # continues from there. Stop tokens cut off any follow-on noise
    # (a second "INPUT" block, markdown headings, code fences).
    return (
        f"{_get_system_instruction()}\n\n"
        f"{_FEW_SHOT_EXAMPLE}\n\n"
        f"{issue_block_text}\n\n"
        f"EXPLANATION\n"
    )


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
    prefix (system instruction + 4 few-shots) is identical for every
    real request, so this single call amortises the cold-start cost:
    subsequent calls only process the short per-issue suffix (~50-100
    tokens) instead of the full ~950-token prompt.

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
