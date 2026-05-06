# core/modules/agent/tests/test_tool_registry.py
#
# Tests for the registry mechanism itself (no concrete tools involved).
# Each test builds its own ToolRegistry to avoid coupling to whatever
# tools production code has registered on default_tool_registry.

from __future__ import annotations

from typing import Callable

import pytest
from agent.tool_registry import (
    ToolDefinition,
    ToolExecutionResult,
    ToolRegistry,
    register_tool,
)

# Type alias for the tiny test-only handler signature: takes any kwargs,
# returns a ToolExecutionResult. Spelled out so the helper signature
# below is self-documenting for someone reading just this file.
TestToolHandler = Callable[..., ToolExecutionResult]


def _make_minimal_handler(returned_data: dict) -> TestToolHandler:
    """Helper: a handler that ignores its arguments and returns the
    given data wrapped in a successful result."""

    def handler_function(**_arguments_ignored) -> ToolExecutionResult:
        return ToolExecutionResult.ok(returned_data)

    return handler_function


class TestToolExecutionResult:
    def test_ok_factory_marks_success(self):
        result = ToolExecutionResult.ok({"value": 42})

        assert result.success is True
        assert result.data == {"value": 42}
        assert result.error_message is None

    def test_error_factory_marks_failure(self):
        result = ToolExecutionResult.error("something went wrong")

        assert result.success is False
        assert result.data is None
        assert result.error_message == "something went wrong"

    def test_result_is_immutable(self):
        result = ToolExecutionResult.ok({"x": 1})
        with pytest.raises(Exception):
            result.success = False  # frozen dataclass


class TestToolDefinitionExecute:
    def test_returns_handler_result_on_success(self):
        tool = ToolDefinition(
            tool_name="echo",
            tool_description="Returns its input unchanged.",
            arguments_schema={"type": "object", "properties": {}},
            tool_handler=_make_minimal_handler({"echoed": True}),
        )

        result = tool.execute(arguments={})

        assert result.success is True
        assert result.data == {"echoed": True}

    def test_wraps_typeerror_as_error_result(self):
        # Handler that requires a kwarg 'required_arg' — caller forgets it.
        def picky_handler(*, required_arg: str) -> ToolExecutionResult:
            return ToolExecutionResult.ok({"got": required_arg})

        tool = ToolDefinition(
            tool_name="picky",
            tool_description="Requires a specific argument.",
            arguments_schema={
                "type": "object",
                "properties": {"required_arg": {"type": "string"}},
                "required": ["required_arg"],
            },
            tool_handler=picky_handler,
        )

        result = tool.execute(arguments={})

        assert result.success is False
        assert "Invalid arguments for tool 'picky'" in result.error_message

    def test_wraps_handler_exception_as_error_result(self):
        def crashing_handler(**_kw) -> ToolExecutionResult:
            raise RuntimeError("deliberate boom")

        tool = ToolDefinition(
            tool_name="crasher",
            tool_description="Always raises.",
            arguments_schema={"type": "object", "properties": {}},
            tool_handler=crashing_handler,
        )

        result = tool.execute(arguments={})

        assert result.success is False
        assert "Tool 'crasher' raised RuntimeError" in result.error_message
        assert "deliberate boom" in result.error_message


class TestToolRegistry:
    def test_empty_registry_has_no_tools(self):
        registry = ToolRegistry()
        assert len(registry) == 0
        assert registry.list_tools() == []

    def test_register_then_retrieve_by_name(self):
        registry = ToolRegistry()
        tool = ToolDefinition(
            tool_name="alpha",
            tool_description="First tool.",
            arguments_schema={"type": "object", "properties": {}},
            tool_handler=_make_minimal_handler({"ok": True}),
        )

        registry.register(tool)

        assert registry.has("alpha")
        assert registry.get("alpha") is tool
        assert len(registry) == 1

    def test_get_unknown_tool_raises_with_helpful_message(self):
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                tool_name="alpha",
                tool_description="t",
                arguments_schema={"type": "object", "properties": {}},
                tool_handler=_make_minimal_handler({}),
            )
        )

        with pytest.raises(KeyError) as caught:
            registry.get("does_not_exist")

        # The error should help the LLM (or a developer) recover by
        # listing what IS available.
        assert "does_not_exist" in str(caught.value)
        assert "alpha" in str(caught.value)

    def test_duplicate_registration_raises(self):
        registry = ToolRegistry()
        first_tool = ToolDefinition(
            tool_name="dup",
            tool_description="first",
            arguments_schema={"type": "object", "properties": {}},
            tool_handler=_make_minimal_handler({}),
        )
        second_tool_same_name = ToolDefinition(
            tool_name="dup",
            tool_description="second",
            arguments_schema={"type": "object", "properties": {}},
            tool_handler=_make_minimal_handler({}),
        )

        registry.register(first_tool)
        with pytest.raises(ValueError, match="already registered"):
            registry.register(second_tool_same_name)

    def test_list_tools_is_sorted_by_name(self):
        registry = ToolRegistry()
        for tool_name in ["zeta", "alpha", "mu"]:
            registry.register(
                ToolDefinition(
                    tool_name=tool_name,
                    tool_description="",
                    arguments_schema={"type": "object", "properties": {}},
                    tool_handler=_make_minimal_handler({}),
                )
            )

        listed_names = [tool.tool_name for tool in registry.list_tools()]

        assert listed_names == ["alpha", "mu", "zeta"]


class TestRegisterToolDecorator:
    def test_decorator_adds_to_target_registry(self):
        isolated_registry = ToolRegistry()

        @register_tool(
            tool_name="decorated",
            tool_description="A decorated handler.",
            arguments_schema={"type": "object", "properties": {}},
            target_registry=isolated_registry,
        )
        def some_handler(**_kw) -> ToolExecutionResult:
            return ToolExecutionResult.ok({"flag": True})

        assert isolated_registry.has("decorated")
        retrieved = isolated_registry.get("decorated")
        assert retrieved.tool_description == "A decorated handler."

    def test_decorator_returns_original_function_callable(self):
        isolated_registry = ToolRegistry()

        @register_tool(
            tool_name="callable_after_decoration",
            tool_description="",
            arguments_schema={"type": "object", "properties": {}},
            target_registry=isolated_registry,
        )
        def some_handler(*, value: int) -> ToolExecutionResult:
            return ToolExecutionResult.ok({"doubled": value * 2})

        # Direct call still works (useful for unit tests that want to
        # exercise the underlying function without going through the
        # registry).
        direct_result = some_handler(value=5)

        assert direct_result.success is True
        assert direct_result.data == {"doubled": 10}

    def test_decorated_tool_executes_via_registry(self):
        isolated_registry = ToolRegistry()

        @register_tool(
            tool_name="adder",
            tool_description="",
            arguments_schema={
                "type": "object",
                "properties": {
                    "left": {"type": "integer"},
                    "right": {"type": "integer"},
                },
                "required": ["left", "right"],
            },
            target_registry=isolated_registry,
        )
        def adder(*, left: int, right: int) -> ToolExecutionResult:
            return ToolExecutionResult.ok({"sum": left + right})

        result = isolated_registry.get("adder").execute(
            arguments={"left": 3, "right": 4}
        )

        assert result.success is True
        assert result.data == {"sum": 7}
