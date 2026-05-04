# core/modules/agent/tests/test_prompt_builder.py
#
# Tests for prompt_builder.build_agent_prompt. Pure-function tests:
# given inputs, the assembled string contains the expected sections
# and tool descriptions in the expected order.

from __future__ import annotations

import pytest
from agent.prompt_builder import AgentHistoryEntry, build_agent_prompt
from agent.tool_registry import ToolDefinition, ToolExecutionResult


def _make_dummy_tool(
    *,
    tool_name: str,
    tool_description: str = "A dummy tool for tests.",
) -> ToolDefinition:
    return ToolDefinition(
        tool_name=tool_name,
        tool_description=tool_description,
        arguments_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
        tool_handler=lambda **_kwargs: ToolExecutionResult.ok({}),
    )


@pytest.fixture
def minimal_tools_list() -> list[ToolDefinition]:
    return [
        _make_dummy_tool(tool_name="alpha", tool_description="Alpha does A."),
        _make_dummy_tool(tool_name="beta", tool_description="Beta does B."),
    ]


class TestEmptyHistory:
    def test_contains_system_header_protocol_and_request(self, minimal_tools_list):
        assembled_prompt = build_agent_prompt(
            user_request="Revisa main.cpp",
            initial_context={"file_path": "main.cpp"},
            registered_tools=minimal_tools_list,
            history_entries=[],
        )

        assert "ShintTools' UE5 code-review agent" in assembled_prompt
        assert "PROTOCOL" in assembled_prompt
        assert "Revisa main.cpp" in assembled_prompt
        assert "main.cpp" in assembled_prompt  # from initial_context

    def test_includes_every_tool_name_and_description(self, minimal_tools_list):
        assembled_prompt = build_agent_prompt(
            user_request="r",
            initial_context={},
            registered_tools=minimal_tools_list,
            history_entries=[],
        )

        for tool_definition in minimal_tools_list:
            assert tool_definition.tool_name in assembled_prompt
            assert tool_definition.tool_description in assembled_prompt

    def test_does_not_include_history_section_when_history_is_empty(
        self, minimal_tools_list
    ):
        assembled_prompt = build_agent_prompt(
            user_request="r",
            initial_context={},
            registered_tools=minimal_tools_list,
            history_entries=[],
        )

        assert "History so far" not in assembled_prompt

    def test_ends_with_next_action_cue(self, minimal_tools_list):
        assembled_prompt = build_agent_prompt(
            user_request="r",
            initial_context={},
            registered_tools=minimal_tools_list,
            history_entries=[],
        )

        # The cue must be the LAST section so the LLM continues from it.
        assert assembled_prompt.rstrip().endswith(
            "respond with the single JSON object now):"
        )


class TestWithHistory:
    # Pre-built JSON payloads kept short to fit the 88-col line limit
    # while staying readable inside the AgentHistoryEntry calls below.
    _ALPHA_TOOL_CALL = '{"action": "tool_call", "tool": "alpha", "arguments": {}}'
    _BETA_TOOL_CALL = '{"action": "tool_call", "tool": "beta", "arguments": {}}'

    def test_history_section_renders_each_entry(self, minimal_tools_list):
        history_entries = [
            AgentHistoryEntry(
                iteration_number=1,
                llm_raw_response=self._ALPHA_TOOL_CALL,
                tool_name_invoked="alpha",
                tool_result_payload={"items": [1, 2, 3]},
                tool_result_was_successful=True,
            ),
            AgentHistoryEntry(
                iteration_number=2,
                llm_raw_response=self._BETA_TOOL_CALL,
                tool_name_invoked="beta",
                tool_result_payload="something failed",
                tool_result_was_successful=False,
            ),
        ]

        assembled_prompt = build_agent_prompt(
            user_request="r",
            initial_context={},
            registered_tools=minimal_tools_list,
            history_entries=history_entries,
        )

        assert "History so far" in assembled_prompt
        assert "Iteration 1" in assembled_prompt
        assert "Iteration 2" in assembled_prompt
        # Successful result encodes data:
        assert '"data"' in assembled_prompt
        # Failed result encodes error:
        assert '"error"' in assembled_prompt
        assert "something failed" in assembled_prompt

    def test_initial_context_is_serialised_as_json(self, minimal_tools_list):
        rich_context = {
            "file_path": "Source/MyActor.cpp",
            "issues": [
                {"rule_id": "CS001", "line": 42},
                {"rule_id": "CB006", "line": 88},
            ],
        }

        assembled_prompt = build_agent_prompt(
            user_request="r",
            initial_context=rich_context,
            registered_tools=minimal_tools_list,
            history_entries=[],
        )

        # The dict's keys must be addressable by the LLM, so they all
        # have to appear in the prompt.
        assert "file_path" in assembled_prompt
        assert "Source/MyActor.cpp" in assembled_prompt
        assert "CS001" in assembled_prompt
        assert "CB006" in assembled_prompt

    def test_unicode_safe(self, minimal_tools_list):
        # ensure_ascii=False is set so Spanish characters survive.
        assembled_prompt = build_agent_prompt(
            user_request="¿Qué pasa con la función Niño?",
            initial_context={"comment": "código con tildes"},
            registered_tools=minimal_tools_list,
            history_entries=[],
        )

        assert "¿Qué" in assembled_prompt
        assert "función" in assembled_prompt
        assert "Niño" in assembled_prompt
        assert "código" in assembled_prompt
