# core/modules/agent/tests/test_action_parser.py
#
# Tests for action_parser.parse_llm_response. These exercise the
# tolerant-parsing strategy: well-formed JSON, fenced JSON, JSON inside
# prose, and the no-JSON fallback all produce a sensible ParsedAction.

from __future__ import annotations

from agent.action_parser import AgentActionKind, parse_llm_response


class TestStrictJsonInputs:
    def test_pure_tool_call_json(self):
        raw_llm_response = (
            '{"action": "tool_call", "tool": "analyze_cpp_source", '
            '"arguments": {"file_path": "x.cpp", "file_content": "int x;"}}'
        )

        parsed = parse_llm_response(raw_llm_response)

        assert parsed.kind == AgentActionKind.TOOL_CALL
        assert parsed.tool_name == "analyze_cpp_source"
        assert parsed.tool_arguments == {
            "file_path": "x.cpp",
            "file_content": "int x;",
        }
        assert parsed.raw_llm_response == raw_llm_response

    def test_pure_finish_json(self):
        raw_llm_response = '{"action": "finish", "answer": "Listo, encontré 2 issues."}'

        parsed = parse_llm_response(raw_llm_response)

        assert parsed.kind == AgentActionKind.FINISH
        assert parsed.final_answer == "Listo, encontré 2 issues."

    def test_tool_call_with_empty_arguments(self):
        raw_llm_response = (
            '{"action": "tool_call", "tool": "no_arg_tool", "arguments": {}}'
        )

        parsed = parse_llm_response(raw_llm_response)

        assert parsed.kind == AgentActionKind.TOOL_CALL
        assert parsed.tool_arguments == {}


class TestCodeFencedInputs:
    def test_strips_json_code_fence(self):
        raw_llm_response = "```json\n" '{"action": "finish", "answer": "ok"}\n' "```"

        parsed = parse_llm_response(raw_llm_response)

        assert parsed.kind == AgentActionKind.FINISH
        assert parsed.final_answer == "ok"

    def test_strips_plain_triple_backtick_fence(self):
        raw_llm_response = (
            "```\n" '{"action": "tool_call", "tool": "t", "arguments": {}}\n' "```"
        )

        parsed = parse_llm_response(raw_llm_response)

        assert parsed.kind == AgentActionKind.TOOL_CALL
        assert parsed.tool_name == "t"


class TestProseAroundJson:
    def test_picks_json_at_end_of_prose(self):
        raw_llm_response = (
            "Voy a llamar al analizador para ver qué tiene este archivo.\n"
            'Aquí va: {"action": "tool_call", "tool": "analyze_cpp_source", '
            '"arguments": {"file_path": "X.cpp", "file_content": ""}}'
        )

        parsed = parse_llm_response(raw_llm_response)

        assert parsed.kind == AgentActionKind.TOOL_CALL
        assert parsed.tool_name == "analyze_cpp_source"

    def test_picks_last_json_when_multiple_present(self):
        # Mirrors a real failure mode where the LLM "thinks out loud"
        # by writing one JSON, then corrects itself with another.
        raw_llm_response = (
            '{"action": "tool_call", "tool": "wrong", "arguments": {}}\n'
            "Wait, on second thought:\n"
            '{"action": "finish", "answer": "done"}'
        )

        parsed = parse_llm_response(raw_llm_response)

        assert parsed.kind == AgentActionKind.FINISH
        assert parsed.final_answer == "done"

    def test_handles_braces_inside_string_values(self):
        # The greedy scanner must not get confused by { or } that
        # appear inside string literals.
        raw_llm_response = '{"action": "finish", "answer": "you wrote `if (x) {}`"}'

        parsed = parse_llm_response(raw_llm_response)

        assert parsed.kind == AgentActionKind.FINISH
        assert "if (x) {}" in parsed.final_answer


class TestFallbackToFinish:
    def test_no_json_at_all_falls_back_to_finish_with_raw_text(self):
        raw_llm_response = "Sorry, I don't know how to do that — please clarify."

        parsed = parse_llm_response(raw_llm_response)

        assert parsed.kind == AgentActionKind.FINISH
        assert parsed.final_answer == raw_llm_response.strip()

    def test_action_field_missing_falls_back_to_finish(self):
        raw_llm_response = '{"foo": "bar"}'

        parsed = parse_llm_response(raw_llm_response)

        # The JSON parsed but didn't match either expected schema; we
        # should fall back to FINISH with the raw text as the answer
        # (rather than crash).
        assert parsed.kind == AgentActionKind.FINISH

    def test_tool_call_missing_tool_field_falls_back(self):
        raw_llm_response = '{"action": "tool_call", "arguments": {}}'

        parsed = parse_llm_response(raw_llm_response)

        assert parsed.kind == AgentActionKind.FINISH

    def test_tool_call_with_non_string_tool_field_falls_back(self):
        raw_llm_response = '{"action": "tool_call", "tool": 123, "arguments": {}}'

        parsed = parse_llm_response(raw_llm_response)

        assert parsed.kind == AgentActionKind.FINISH

    def test_tool_call_with_non_object_arguments_falls_back(self):
        raw_llm_response = (
            '{"action": "tool_call", "tool": "t", "arguments": "not a dict"}'
        )

        parsed = parse_llm_response(raw_llm_response)

        assert parsed.kind == AgentActionKind.FINISH

    def test_finish_with_non_string_answer_falls_back(self):
        raw_llm_response = '{"action": "finish", "answer": 42}'

        parsed = parse_llm_response(raw_llm_response)

        # The whole-text decode produces a dict that fails our schema
        # (answer must be str). The fallback then treats raw text as
        # the answer.
        assert parsed.kind == AgentActionKind.FINISH
        # The raw response is preserved for debugging.
        assert parsed.raw_llm_response == raw_llm_response
