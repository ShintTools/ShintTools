# core/modules/agent/orchestrator.py
#
# Sprint C — Fase 3.
#
# The agent loop. Wires together:
#
#     llm_generate_function   ←─── injected (production: llm_backend.generate)
#     tool_registry           ←─── injected (production: default_tool_registry)
#     prompt_builder          ←─── pure function
#     action_parser           ←─── pure function
#
# The loop:
#
#     for iteration in 1..max_iterations:
#         build prompt from (request, context, history, tools)
#         call LLM -> raw response
#         parse raw response -> action
#         if action is FINISH -> return AgentRunResult
#         else execute tool, append result to history, continue
#
#     if loop exits without FINISH -> return AgentRunResult with
#     halted_reason=MAX_ITERATIONS so the caller can decide what to do.
#
# Design notes:
#   - llm_generate_function is a Callable[[str], str], not the full
#     llm_backend module. Keeps the orchestrator decoupled from the
#     specific backend (llama-cpp-python today, possibly something
#     else later) and trivial to mock in tests.
#   - The orchestrator NEVER raises during a normal run. Tool errors,
#     parser fallbacks, max-iteration cutoffs are all returned as
#     AgentRunResult variants so the FastAPI route layer can render
#     them uniformly.

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from .action_parser import AgentActionKind, ParsedAction, parse_llm_response
from .prompt_builder import AgentHistoryEntry, build_agent_prompt
from .tool_registry import ToolExecutionResult, ToolRegistry

# Type alias for the "give me text given a prompt" callable that the
# orchestrator depends on. Production wires this to llm_backend.generate;
# tests pass a fake.
LlmGenerateFunction = Callable[[str], str]


class AgentHaltReason(str, Enum):
    """Why the agent loop stopped. Each value maps to one return path
    in AgentOrchestrator.run."""

    FINISHED_NORMALLY = "finished_normally"
    REACHED_MAX_ITERATIONS = "reached_max_iterations"


@dataclass(frozen=True)
class AgentStep:
    """A single iteration: what the LLM said, what we did with it."""

    iteration_number: int
    parsed_action: ParsedAction
    tool_execution_result: Optional[ToolExecutionResult]


@dataclass(frozen=True)
class AgentRunResult:
    """The final outcome of one orchestrator run. Always returned;
    never raised."""

    final_answer: str
    halt_reason: AgentHaltReason
    iterations_used: int
    steps: list[AgentStep] = field(default_factory=list)


# ── Orchestrator ───────────────────────────────────────────────────────────


@dataclass
class AgentOrchestrator:
    """Runs one LLM-driven agent task to completion.

    Hold one orchestrator per request. Two concurrent FastAPI requests
    should each create their own orchestrator so their histories stay
    separate; ToolRegistry is shared (it's read-only at runtime).
    """

    tool_registry: ToolRegistry
    llm_generate_function: LlmGenerateFunction
    max_iterations: int = 8

    def run(
        self,
        *,
        user_request: str,
        initial_context: dict[str, Any],
    ) -> AgentRunResult:
        """Execute the agent loop and return the result.

        Arguments:
            user_request: what the developer asked, in their own words.
            initial_context: any per-run data the LLM should see from
                the start (e.g. {"file_path": "MyActor.cpp", "issues":
                [...]}). Kept stable across iterations.
        """

        accumulated_history: list[AgentHistoryEntry] = []
        recorded_steps: list[AgentStep] = []
        registered_tools_snapshot = self.tool_registry.list_tools()

        for current_iteration_number in range(1, self.max_iterations + 1):
            assembled_prompt = build_agent_prompt(
                user_request=user_request,
                initial_context=initial_context,
                registered_tools=registered_tools_snapshot,
                history_entries=accumulated_history,
            )

            raw_llm_response = self.llm_generate_function(assembled_prompt)
            parsed_action = parse_llm_response(raw_llm_response)

            # FINISH path — the loop terminates here.
            if parsed_action.kind == AgentActionKind.FINISH:
                recorded_steps.append(
                    AgentStep(
                        iteration_number=current_iteration_number,
                        parsed_action=parsed_action,
                        tool_execution_result=None,
                    )
                )
                return AgentRunResult(
                    final_answer=parsed_action.final_answer or "",
                    halt_reason=AgentHaltReason.FINISHED_NORMALLY,
                    iterations_used=current_iteration_number,
                    steps=recorded_steps,
                )

            # TOOL_CALL path — execute and continue the loop.
            tool_execution_result = self._execute_tool_call(parsed_action)

            recorded_steps.append(
                AgentStep(
                    iteration_number=current_iteration_number,
                    parsed_action=parsed_action,
                    tool_execution_result=tool_execution_result,
                )
            )

            accumulated_history.append(
                AgentHistoryEntry(
                    iteration_number=current_iteration_number,
                    llm_raw_response=parsed_action.raw_llm_response,
                    tool_name_invoked=parsed_action.tool_name,
                    tool_result_payload=(
                        tool_execution_result.data
                        if tool_execution_result.success
                        else tool_execution_result.error_message
                    ),
                    tool_result_was_successful=tool_execution_result.success,
                )
            )

        # Loop exhausted without a FINISH action.
        return AgentRunResult(
            final_answer=(
                "The agent did not converge to a final answer within "
                f"{self.max_iterations} iterations. The partial history "
                "is available in `steps` for inspection."
            ),
            halt_reason=AgentHaltReason.REACHED_MAX_ITERATIONS,
            iterations_used=self.max_iterations,
            steps=recorded_steps,
        )

    # ── Internals ──────────────────────────────────────────────────────────

    def _execute_tool_call(
        self,
        parsed_action: ParsedAction,
    ) -> ToolExecutionResult:
        """Look up the requested tool in the registry and execute it.
        Unknown tool names and missing/invalid arguments are converted
        into ToolExecutionResult.error so the loop never crashes."""

        if parsed_action.tool_name is None:
            return ToolExecutionResult.error(
                "Parsed action was a tool_call but tool_name was None — "
                "this indicates a parser bug; please report it."
            )

        if not self.tool_registry.has(parsed_action.tool_name):
            available_tool_names = sorted(
                tool_definition.tool_name
                for tool_definition in self.tool_registry.list_tools()
            )
            return ToolExecutionResult.error(
                f"Unknown tool '{parsed_action.tool_name}'. Available: "
                f"{available_tool_names}"
            )

        target_tool_definition = self.tool_registry.get(parsed_action.tool_name)
        return target_tool_definition.execute(
            arguments=parsed_action.tool_arguments or {}
        )
