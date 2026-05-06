# core/modules/agent/__init__.py
#
# Sprint C — Local LLM agent for ShintTools.
#
# Three-layer architecture, built one Fase at a time:
#   Fase 1  llm_backend                 local inference via llama-cpp-python
#   Fase 2  tool_registry / tool_…      existing rules wrapped as agent tools
#   Fase 3  prompt_builder / parser /   the agent loop (LLM <-> tools)
#           orchestrator
#   Fase 4  (pending)                   FastAPI SSE endpoint
#   Fase 5  (pending)                   Docker integration
#
# This package's __init__ re-exports the small public surface that other
# modules (api/routes/agent.py in Fase 4, the FastAPI lifespan, tests)
# need. Everything not re-exported here is internal — feel free to
# refactor without crossing module boundaries.
#
# IMPORTANT: importing this package eagerly imports tool_implementations,
# which has the side-effect of registering each concrete tool on
# default_tool_registry. This means production code can simply do
#
#     from modules.agent import default_tool_registry, AgentOrchestrator
#
# and trust that all built-in tools are already available.

# Side-effect import: populates default_tool_registry. Keep last so the
# names above are bound first (avoids subtle circular-import surprises
# if a future tool wants to import from this package).
from . import tool_implementations  # noqa: F401
from .action_parser import AgentActionKind, ParsedAction
from .orchestrator import AgentHaltReason, AgentOrchestrator, AgentRunResult, AgentStep
from .tool_registry import (
    ToolDefinition,
    ToolExecutionResult,
    ToolHandler,
    ToolRegistry,
    default_tool_registry,
    register_tool,
)

__all__ = [
    # Action / parser layer
    "AgentActionKind",
    "ParsedAction",
    # Orchestrator layer
    "AgentHaltReason",
    "AgentOrchestrator",
    "AgentRunResult",
    "AgentStep",
    # Tool registry
    "ToolDefinition",
    "ToolExecutionResult",
    "ToolHandler",
    "ToolRegistry",
    "default_tool_registry",
    "register_tool",
]
