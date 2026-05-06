# core/modules/agent/tests/test_tool_implementations.py
#
# Tests for the concrete tools defined in tool_implementations.py.
# These tests exercise the tools both directly (calling the decorated
# function) and via the default_tool_registry (going through
# ToolDefinition.execute), so we know both paths work.

from __future__ import annotations

import pytest
from agent import tool_implementations  # noqa: F401 — populates the registry
from agent.tool_implementations import (
    analyze_cpp_source,
    apply_auto_fix_for_issue,
    extract_source_excerpt,
)
from agent.tool_registry import default_tool_registry

# ── analyze_cpp_source ─────────────────────────────────────────────────────


class TestAnalyzeCppSource:
    def test_clean_code_produces_no_issues(self):
        clean_cpp_source = (
            "// Trivial header that contains no UE5 anti-patterns.\n"
            "int Add(int a, int b) { return a + b; }\n"
        )

        result = analyze_cpp_source(
            file_path="Source/Clean.cpp",
            file_content=clean_cpp_source,
        )

        assert result.success is True
        assert result.data["file_path"] == "Source/Clean.cpp"
        assert result.data["issue_count"] == 0
        assert result.data["issues"] == []

    def test_passes_through_validator_issues(self, monkeypatch):
        # Unit test: we verify the wrapper forwards whatever the
        # validator returns and packages it correctly. Whether a given
        # pattern triggers a specific rule is the validator's
        # responsibility, exercised by code_validator's own test suite.
        fabricated_issues = [
            {
                "rule_id": "CP004",
                "severity": "warning",
                "file_path": "Source/MyActor.cpp",
                "line": 3,
                "message": "UE_LOG inside Tick is a perf hit.",
            },
            {
                "rule_id": "CB006",
                "severity": "info",
                "file_path": "Source/MyActor.cpp",
                "line": 4,
                "message": "Use UE_LOG instead of printf.",
            },
        ]

        def fake_analyse(_file_path, _file_content):
            return fabricated_issues

        monkeypatch.setattr("code_validator.analyse", fake_analyse)

        result = analyze_cpp_source(
            file_path="Source/MyActor.cpp",
            file_content="// any content — the validator is mocked.",
        )

        assert result.success is True
        assert result.data["file_path"] == "Source/MyActor.cpp"
        assert result.data["issue_count"] == 2
        assert result.data["issues"] == fabricated_issues

    def test_returns_failure_when_handler_raises(self, monkeypatch):
        # Force the underlying validator to blow up; the registry layer
        # should turn that into a clean error result.
        def fake_analyse(*_args, **_kwargs):
            raise RuntimeError("simulated validator failure")

        # The function imports `analyse` lazily, so patch the module
        # the function will actually pull from.
        monkeypatch.setattr(
            "code_validator.analyse",
            fake_analyse,
        )

        registered_tool = default_tool_registry.get("analyze_cpp_source")
        result = registered_tool.execute(
            arguments={"file_path": "x.cpp", "file_content": "int x;"}
        )

        assert result.success is False
        assert "simulated validator failure" in result.error_message


# ── extract_source_excerpt ─────────────────────────────────────────────────


class TestExtractSourceExcerpt:
    @pytest.fixture
    def four_line_source(self) -> str:
        return "line one\nline two\nline three\nline four"

    def test_extracts_inclusive_range(self, four_line_source):
        result = extract_source_excerpt(
            file_content=four_line_source,
            start_line=2,
            end_line=3,
        )

        assert result.success is True
        assert result.data["excerpt"] == "line two\nline three"
        assert result.data["start_line"] == 2
        assert result.data["end_line"] == 3
        assert result.data["line_count"] == 2

    def test_clamps_end_line_past_eof(self, four_line_source):
        # File has 4 lines; ask for up to 99.
        result = extract_source_excerpt(
            file_content=four_line_source,
            start_line=3,
            end_line=99,
        )

        assert result.success is True
        # end_line is reported as the clamped value, not the requested 99.
        assert result.data["end_line"] == 4
        assert result.data["line_count"] == 2
        assert result.data["excerpt"].endswith("line four")

    def test_rejects_inverted_range(self, four_line_source):
        result = extract_source_excerpt(
            file_content=four_line_source,
            start_line=4,
            end_line=2,
        )

        assert result.success is False
        assert "must be <=" in result.error_message

    def test_rejects_start_past_eof(self, four_line_source):
        result = extract_source_excerpt(
            file_content=four_line_source,
            start_line=10,
            end_line=11,
        )

        assert result.success is False
        assert "past the end of the file" in result.error_message

    def test_single_line_extraction(self, four_line_source):
        result = extract_source_excerpt(
            file_content=four_line_source,
            start_line=1,
            end_line=1,
        )

        assert result.success is True
        assert result.data["excerpt"] == "line one"
        assert result.data["line_count"] == 1


# ── apply_auto_fix_for_issue ───────────────────────────────────────────────


class TestApplyAutoFixForIssue:
    def test_known_fixable_rule_reports_fix_applied(self):
        # CB006 is in code_validator's `fixable` set today.
        fixable_issue = {
            "rule_id": "CB006",
            "severity": "warning",
            "file_path": "x.cpp",
            "line": 1,
        }

        result = apply_auto_fix_for_issue(issue=fixable_issue)

        assert result.success is True
        assert result.data["rule_id"] == "CB006"
        assert result.data["fix_was_applied"] is True

    def test_rule_without_auto_fix_reports_not_applied(self):
        unfixable_issue = {"rule_id": "CS001"}  # security, no auto-fix

        result = apply_auto_fix_for_issue(issue=unfixable_issue)

        assert result.success is True
        assert result.data["rule_id"] == "CS001"
        assert result.data["fix_was_applied"] is False

    def test_missing_rule_id_returns_clean_error(self):
        # The LLM might hand us a malformed issue; we must not crash.
        malformed_issue = {"severity": "error"}

        result = apply_auto_fix_for_issue(issue=malformed_issue)

        assert result.success is False
        assert "rule_id" in result.error_message


# ── Registry-level smoke test ──────────────────────────────────────────────


class TestDefaultRegistryPopulation:
    """Importing tool_implementations registers the tools on the
    default registry; here we verify the public surface is what the
    orchestrator (Fase 3) is going to assume."""

    def test_all_three_tools_are_registered(self):
        expected_tool_names = {
            "analyze_cpp_source",
            "extract_source_excerpt",
            "apply_auto_fix_for_issue",
        }
        registered_tool_names = {
            tool.tool_name for tool in default_tool_registry.list_tools()
        }
        assert expected_tool_names.issubset(registered_tool_names)

    def test_every_registered_tool_has_a_non_empty_description(self):
        for tool_definition in default_tool_registry.list_tools():
            assert tool_definition.tool_description.strip(), (
                f"Tool '{tool_definition.tool_name}' has an empty "
                "description; the LLM cannot decide when to use it."
            )

    def test_every_registered_tool_has_object_schema(self):
        for tool_definition in default_tool_registry.list_tools():
            schema = tool_definition.arguments_schema
            assert schema.get("type") == "object", (
                f"Tool '{tool_definition.tool_name}' arguments_schema "
                "must be a JSON Schema 'object' at the top level."
            )
