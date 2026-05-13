# core/modules/agent/__init__.py
#
# Local LLM explainer for ShintTools.
#
# The deterministic rules under code_validator/ and naming/ already
# detect issues and (for C++) apply Tree-sitter fixes. This package's
# only role is to take a single enriched issue and turn it into a
# short, customer-facing explanation via a local GGUF model — no
# tools, no JSON protocol, no orchestrator loop.
#
# Public surface re-exported here for callers (api/routes/agent.py,
# scripts/smoke_llm_explainer.py, future tests):
#
#     from modules.agent import explain_issue, build_explainer_prompt
#     from modules.agent import generate, is_loaded, load_model
#
# Earlier sprints prototyped a tool-calling agent (orchestrator, tool
# registry, action parser, multi-domain prompt builder). That layer
# was removed when we confirmed a 1.3B-class model cannot reliably
# follow a JSON tool-calling protocol AND there was nothing for the
# agent to investigate — the rules had already done the detection.
# If we ever need an agentic flow again (multi-file analysis, fix
# orchestration), build it from scratch with the right model size
# and contract for that specific task.

from .explainer import (
    DEFAULT_MODEL_ID,
    build_explainer_prompt,
    compute_cache_key,
    explain_issue,
    explain_issue_stream,
)
from .llm_backend import generate, generate_stream, is_loaded, load_model, unload_model
from .prefab_explanations import get_stats as prefab_stats
from .prefab_explanations import is_loaded as prefab_is_loaded
from .prefab_explanations import lookup_prefab

__all__ = [
    # Direct explainer (production path for /agent/explain)
    "build_explainer_prompt",
    "compute_cache_key",
    "DEFAULT_MODEL_ID",
    "explain_issue",
    "explain_issue_stream",
    # Local model lifecycle
    "generate",
    "generate_stream",
    "is_loaded",
    "load_model",
    "unload_model",
    # Prefab cache (resolved before MongoDB cache / live LLM)
    "lookup_prefab",
    "prefab_is_loaded",
    "prefab_stats",
]
