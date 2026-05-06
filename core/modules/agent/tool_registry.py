# core/modules/agent/tool_registry.py
#
# Sprint C — Fase 2.
#
# Defines the contract that every "tool" the LLM agent can invoke must
# follow, plus a small registry that holds those tools by name.
#
# Why a registry (instead of, say, a fixed dict in orchestrator.py):
#   - Adding a new capability is a pure-additive change: write a function,
#     decorate it, done. The orchestrator does not need to be edited.
#   - Tests can build their own isolated ToolRegistry instances and run
#     against a controlled set of tools, with no global-state leakage
#     between test cases.
#   - The on-the-wire shape of `arguments_schema` is JSON Schema, the same
#     format used by OpenAI / Anthropic function-calling APIs. If we ever
#     migrate to a model that supports native function calling, we can
#     forward our schemas verbatim.
#
# The registry intentionally does NOT validate arguments against the
# schema before calling the handler. That validation lives in the
# orchestrator (Fase 3) where we have access to the LLM's raw output
# and can produce useful error messages back to the model.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# ── Result contract ────────────────────────────────────────────────────────
#
# Every tool returns a ToolExecutionResult so the orchestrator never has
# to inspect raw exceptions. A failure is a value, not a control-flow
# event. This keeps the LLM <-> tools loop deterministic.


@dataclass(frozen=True)
class ToolExecutionResult:
    """Outcome of running a tool. Always has either `data` (on success)
    or `error_message` (on failure), never both."""

    success: bool
    data: Optional[Any] = None
    error_message: Optional[str] = None

    @classmethod
    def ok(cls, data: Any) -> "ToolExecutionResult":
        return cls(success=True, data=data, error_message=None)

    @classmethod
    def error(cls, error_message: str) -> "ToolExecutionResult":
        return cls(success=False, data=None, error_message=error_message)


# ── Tool definition ────────────────────────────────────────────────────────


# A tool handler is any callable that takes keyword arguments and returns
# a ToolExecutionResult. Concrete signatures vary per tool; the schema
# describes them.
ToolHandler = Callable[..., ToolExecutionResult]


@dataclass(frozen=True)
class ToolDefinition:
    """Everything the orchestrator needs to advertise a tool to the LLM
    and then invoke it on demand."""

    tool_name: str
    tool_description: str
    arguments_schema: dict[str, Any]  # JSON Schema (Draft 2020-12 subset)
    tool_handler: ToolHandler

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        """Invoke the underlying handler. Any exception the handler
        raises is captured and returned as a failed ToolExecutionResult,
        so the orchestrator can keep looping instead of crashing.
        """
        try:
            return self.tool_handler(**arguments)
        except TypeError as type_error:
            # Almost always: LLM hallucinated wrong / missing kwargs.
            return ToolExecutionResult.error(
                f"Invalid arguments for tool '{self.tool_name}': {type_error}"
            )
        except Exception as unexpected_error:
            return ToolExecutionResult.error(
                f"Tool '{self.tool_name}' raised "
                f"{type(unexpected_error).__name__}: {unexpected_error}"
            )


# ── Registry ───────────────────────────────────────────────────────────────


@dataclass
class ToolRegistry:
    """In-memory map from tool_name -> ToolDefinition. Each tool name
    is unique within a registry; re-registering raises immediately so
    silent overrides never happen in production.

    There is one default registry (`default_tool_registry` below) used
    by all production code. Tests should construct their own isolated
    ToolRegistry instances to avoid coupling test ordering to side
    effects on the default."""

    _registered_tools: dict[str, ToolDefinition] = field(default_factory=dict)

    def register(self, tool_definition: ToolDefinition) -> None:
        if tool_definition.tool_name in self._registered_tools:
            raise ValueError(
                f"Tool '{tool_definition.tool_name}' is already registered. "
                "Tool names must be unique within a registry."
            )
        self._registered_tools[tool_definition.tool_name] = tool_definition

    def get(self, tool_name: str) -> ToolDefinition:
        if tool_name not in self._registered_tools:
            raise KeyError(
                f"Unknown tool '{tool_name}'. "
                f"Available tools: {sorted(self._registered_tools)}"
            )
        return self._registered_tools[tool_name]

    def has(self, tool_name: str) -> bool:
        return tool_name in self._registered_tools

    def list_tools(self) -> list[ToolDefinition]:
        """Return all registered tools, sorted by tool_name for stable
        output (LLM prompts and snapshot tests benefit from this)."""
        return sorted(
            self._registered_tools.values(),
            key=lambda tool_definition: tool_definition.tool_name,
        )

    def __len__(self) -> int:
        return len(self._registered_tools)


# Default registry used by production code. Tool implementations import
# `register_tool` below and decorate themselves at module-import time;
# importing tool_implementations.py is what populates this registry.
default_tool_registry = ToolRegistry()


# ── Decorator ──────────────────────────────────────────────────────────────


def register_tool(
    *,
    tool_name: str,
    tool_description: str,
    arguments_schema: dict[str, Any],
    target_registry: Optional[ToolRegistry] = None,
) -> Callable[[ToolHandler], ToolHandler]:
    """Decorator: turn a function into a ToolDefinition and add it to
    a registry.

    Usage::

        @register_tool(
            tool_name="analyze_cpp_source",
            tool_description="Run static analysis on a C++ source file.",
            arguments_schema={...JSON Schema...},
        )
        def analyze_cpp_source(*, file_path, file_content):
            ...
            return ToolExecutionResult.ok({...})

    By default the tool is added to `default_tool_registry`. Tests that
    need isolation pass a fresh ToolRegistry instance via target_registry.
    """
    # Explicit None check, NOT `target_registry or default_tool_registry`:
    # ToolRegistry defines __len__, so an empty registry is falsy under
    # Python's truthiness rules. `or` would silently route registrations
    # to the default registry whenever the caller passed in a fresh
    # (and therefore empty) one, which is the opposite of what we want.
    registry_to_use = (
        target_registry if target_registry is not None else default_tool_registry
    )

    def decorator(handler_function: ToolHandler) -> ToolHandler:
        registry_to_use.register(
            ToolDefinition(
                tool_name=tool_name,
                tool_description=tool_description,
                arguments_schema=arguments_schema,
                tool_handler=handler_function,
            )
        )
        # Return the handler unchanged so the decorated function can
        # still be called directly (useful in unit tests).
        return handler_function

    return decorator
