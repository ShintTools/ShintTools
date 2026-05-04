# core/modules/agent/tests/test_orchestrator.py
#
# Tests for AgentOrchestrator.run. The LLM is replaced with a scripted
# fake that returns pre-canned responses, one per iteration. Each test
# asserts the orchestrator drove the loop the right way given those
# responses.

from __future__ import annotations

import json
from typing import Iterator

from agent.action_parser import AgentActionKind
from agent.orchestrator import AgentHaltReason, AgentOrchestrator
from agent.tool_registry import ToolDefinition, ToolExecutionResult, ToolRegistry

# ── Fake LLM helpers ───────────────────────────────────────────────────────


class ScriptedLlm:
    """Returns scripted_responses one per call. Records every prompt
    it received so tests can assert what the orchestrator actually
    asked the model."""

    def __init__(self, scripted_responses: list[str]):
        self._responses_iterator: Iterator[str] = iter(scripted_responses)
        self.received_prompts: list[str] = []

    def __call__(self, prompt_text: str) -> str:
        self.received_prompts.append(prompt_text)
        try:
            return next(self._responses_iterator)
        except StopIteration as exhausted:
            raise AssertionError(
                "ScriptedLlm ran out of canned responses — the "
                "orchestrator iterated more times than the test "
                "expected."
            ) from exhausted


def _build_registry_with_capture_tool(
    *,
    handler_returns: ToolExecutionResult,
) -> tuple[ToolRegistry, list[dict]]:
    """Create a ToolRegistry containing a single 'capture' tool that
    records every invocation and returns a fixed result. The returned
    list grows as the tool is called, letting tests assert call order
    and arguments."""

    captured_invocations: list[dict] = []

    def capture_handler(**received_kwargs) -> ToolExecutionResult:
        captured_invocations.append(received_kwargs)
        return handler_returns

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            tool_name="capture",
            tool_description="Records its arguments. For tests only.",
            arguments_schema={
                "type": "object",
                "properties": {
                    "anything": {"type": "string"},
                },
                "required": [],
            },
            tool_handler=capture_handler,
        )
    )
    return registry, captured_invocations


# ── Tests ──────────────────────────────────────────────────────────────────


class TestImmediateFinish:
    def test_llm_finishes_on_first_turn(self):
        registry = ToolRegistry()
        scripted_llm = ScriptedLlm(
            [json.dumps({"action": "finish", "answer": "all good"})]
        )
        orchestrator = AgentOrchestrator(
            tool_registry=registry,
            llm_generate_function=scripted_llm,
        )

        run_result = orchestrator.run(
            user_request="hi",
            initial_context={},
        )

        assert run_result.halt_reason == AgentHaltReason.FINISHED_NORMALLY
        assert run_result.final_answer == "all good"
        assert run_result.iterations_used == 1
        assert len(run_result.steps) == 1
        assert run_result.steps[0].parsed_action.kind == AgentActionKind.FINISH


class TestSingleToolCallThenFinish:
    def test_executes_tool_with_arguments_and_then_finishes(self):
        registry, captured_invocations = _build_registry_with_capture_tool(
            handler_returns=ToolExecutionResult.ok({"echo": "ok"}),
        )
        scripted_llm = ScriptedLlm(
            [
                json.dumps(
                    {
                        "action": "tool_call",
                        "tool": "capture",
                        "arguments": {"anything": "hello"},
                    }
                ),
                json.dumps({"action": "finish", "answer": "tool returned ok"}),
            ]
        )
        orchestrator = AgentOrchestrator(
            tool_registry=registry,
            llm_generate_function=scripted_llm,
        )

        run_result = orchestrator.run(
            user_request="please use the tool",
            initial_context={"context_key": "context_value"},
        )

        # Tool was invoked exactly once with the LLM's arguments.
        assert captured_invocations == [{"anything": "hello"}]

        # Run state is correct.
        assert run_result.halt_reason == AgentHaltReason.FINISHED_NORMALLY
        assert run_result.iterations_used == 2
        assert run_result.final_answer == "tool returned ok"
        assert len(run_result.steps) == 2
        assert run_result.steps[0].parsed_action.kind == AgentActionKind.TOOL_CALL
        assert run_result.steps[0].tool_execution_result.success is True
        assert run_result.steps[1].parsed_action.kind == AgentActionKind.FINISH

    def test_history_is_passed_to_subsequent_llm_calls(self):
        registry, _ignored_captures = _build_registry_with_capture_tool(
            handler_returns=ToolExecutionResult.ok({"detail": "abc-123"}),
        )
        scripted_llm = ScriptedLlm(
            [
                json.dumps({"action": "tool_call", "tool": "capture", "arguments": {}}),
                json.dumps({"action": "finish", "answer": "done"}),
            ]
        )
        orchestrator = AgentOrchestrator(
            tool_registry=registry,
            llm_generate_function=scripted_llm,
        )

        orchestrator.run(user_request="r", initial_context={})

        # The second prompt sent to the LLM must contain history of
        # the first iteration, including the tool result payload.
        first_prompt_text, second_prompt_text = scripted_llm.received_prompts
        assert "History so far" not in first_prompt_text
        assert "History so far" in second_prompt_text
        assert "abc-123" in second_prompt_text


class TestUnknownToolHandling:
    def test_unknown_tool_call_results_in_error_step_then_loop_continues(self):
        registry = ToolRegistry()  # empty — no tools at all
        scripted_llm = ScriptedLlm(
            [
                json.dumps(
                    {
                        "action": "tool_call",
                        "tool": "tool_that_does_not_exist",
                        "arguments": {},
                    }
                ),
                json.dumps({"action": "finish", "answer": "recovered"}),
            ]
        )
        orchestrator = AgentOrchestrator(
            tool_registry=registry,
            llm_generate_function=scripted_llm,
        )

        run_result = orchestrator.run(user_request="r", initial_context={})

        # The agent did not crash; it surfaced the unknown tool as a
        # tool error, the LLM saw it and finished normally.
        assert run_result.halt_reason == AgentHaltReason.FINISHED_NORMALLY
        assert run_result.iterations_used == 2

        first_step = run_result.steps[0]
        assert first_step.tool_execution_result is not None
        assert first_step.tool_execution_result.success is False
        assert (
            "tool_that_does_not_exist" in first_step.tool_execution_result.error_message
        )


class TestMaxIterations:
    def test_loop_halts_when_llm_never_finishes(self):
        # Build a registry with the capture tool — handler returns ok
        # every time but the LLM keeps requesting more calls.
        registry, _ignored_captures = _build_registry_with_capture_tool(
            handler_returns=ToolExecutionResult.ok({}),
        )

        # 5 tool_call responses, no finish. With max_iterations=3 the
        # loop must halt before consuming the 4th.
        infinite_tool_calls = [
            json.dumps({"action": "tool_call", "tool": "capture", "arguments": {}})
        ] * 5
        scripted_llm = ScriptedLlm(infinite_tool_calls)

        orchestrator = AgentOrchestrator(
            tool_registry=registry,
            llm_generate_function=scripted_llm,
            max_iterations=3,
        )

        run_result = orchestrator.run(user_request="r", initial_context={})

        assert run_result.halt_reason == AgentHaltReason.REACHED_MAX_ITERATIONS
        assert run_result.iterations_used == 3
        assert len(run_result.steps) == 3
        # The orchestrator must NOT have called the LLM a 4th time.
        assert len(scripted_llm.received_prompts) == 3


class TestToolHandlerError:
    def test_handler_failure_is_recorded_and_loop_continues(self):
        registry, _ignored_captures = _build_registry_with_capture_tool(
            handler_returns=ToolExecutionResult.error("disk on fire"),
        )
        scripted_llm = ScriptedLlm(
            [
                json.dumps({"action": "tool_call", "tool": "capture", "arguments": {}}),
                json.dumps({"action": "finish", "answer": "ack the failure"}),
            ]
        )
        orchestrator = AgentOrchestrator(
            tool_registry=registry,
            llm_generate_function=scripted_llm,
        )

        run_result = orchestrator.run(user_request="r", initial_context={})

        assert run_result.halt_reason == AgentHaltReason.FINISHED_NORMALLY
        first_step = run_result.steps[0]
        assert first_step.tool_execution_result.success is False
        assert "disk on fire" in first_step.tool_execution_result.error_message
        # And the error appears in the prompt the LLM saw next:
        second_prompt = scripted_llm.received_prompts[1]
        assert "disk on fire" in second_prompt


class TestRawTextFallbackTreatedAsFinish:
    def test_when_llm_returns_plain_text_the_run_ends_with_that_text(self):
        registry = ToolRegistry()
        scripted_llm = ScriptedLlm(
            ["No estoy seguro de qué hacer aquí, dame más contexto."]
        )
        orchestrator = AgentOrchestrator(
            tool_registry=registry,
            llm_generate_function=scripted_llm,
        )

        run_result = orchestrator.run(user_request="r", initial_context={})

        assert run_result.halt_reason == AgentHaltReason.FINISHED_NORMALLY
        assert "más contexto" in run_result.final_answer
