# core/modules/agent/tests/test_custom_rule_checker.py
#
# Tests for the LLM-based custom rule checker (Fase B).
#
# None of these tests load the GGUF model — _llm_generate is
# monkeypatched so the suite is fast and fully offline.

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from agent import custom_rule_checker as checker
from agent.custom_rule_checker import (
    CustomRule,
    _build_checker_prompt,
    _extract_keywords,
    _parse_violations,
    _prefilter_files,
    check_custom_rules,
)
from agent.prompts import registry


@pytest.fixture(autouse=True)
def _reset_registry_cache():
    registry.reset_cache()
    yield
    registry.reset_cache()


# ── Fixtures ──────────────────────────────────────────────────────────────

RULE_NO_HARDCODED_PASSWORDS = CustomRule(
    name="No hardcoded passwords",
    description=(
        "Passwords and credentials must not appear as string literals "
        "in source code. They must be loaded from environment variables "
        "or a secure config asset at runtime."
    ),
    example_violation='string password = "SuperSecret123";',
)

# Five C# files: 2 violate (DatabaseConfig, SaveManager), 3 are clean.
FILES_5 = [
    (
        "Assets/Scripts/Data/DatabaseConfig.cs",
        "using UnityEngine;\npublic class DatabaseConfig : MonoBehaviour {\n"
        '    private string dbPassword = "prod-db-s3cret!";\n'
        "    void Start() { Connect(dbPassword); }\n}",
    ),
    (
        "Assets/Scripts/Player/PlayerController.cs",
        "using UnityEngine;\npublic class PlayerController : MonoBehaviour {\n"
        "    public float speed = 5f;\n"
        "    void Update() { transform.Translate(Vector3.forward * speed * Time.deltaTime); }\n}",
    ),
    (
        "Assets/Scripts/UI/HealthBar.cs",
        "using UnityEngine;\npublic class HealthBar : MonoBehaviour {\n"
        "    public Slider slider;\n"
        "    public void SetHealth(int hp) { slider.value = hp; }\n}",
    ),
    (
        "Assets/Scripts/Storage/NetworkManager.cs",
        "using UnityEngine;\npublic class NetworkManager : MonoBehaviour {\n"
        '    public string serverUrl = "https://api.example.com";\n'
        "    void Connect() { /* tls connection */ }\n}",
    ),
    (
        "Assets/Scripts/Storage/SaveManager.cs",
        "using UnityEngine;\npublic class SaveManager : MonoBehaviour {\n"
        '    string encryptionPassword = "save-enc-key-2024";\n'
        "    void Save() { Encrypt(data, encryptionPassword); }\n}",
    ),
]


def _make_llm_response(violations: list[dict]) -> str:
    """Build a realistic LLM response string for the given violations."""
    return json.dumps(violations)


# ── _extract_keywords ──────────────────────────────────────────────────────


class TestExtractKeywords:
    def test_extracts_meaningful_words(self):
        rule = CustomRule(
            name="No hardcoded passwords",
            description="Passwords must not appear as literals in source.",
        )
        kws = _extract_keywords(rule)
        assert "passwords" in kws
        assert "hardcoded" in kws
        assert "literals" in kws

    def test_excludes_short_words(self):
        rule = CustomRule(name="No bad code", description="Bad code in the file.")
        kws = _extract_keywords(rule)
        assert "the" not in kws
        assert "bad" not in kws  # 3 chars, excluded by ≥5 rule

    def test_returns_empty_for_trivial_rule(self):
        rule = CustomRule(name="", description="")
        kws = _extract_keywords(rule)
        assert isinstance(kws, frozenset)


# ── _prefilter_files ──────────────────────────────────────────────────────


class TestPrefilterFiles:
    def test_keeps_files_with_matching_keywords(self):
        rule = RULE_NO_HARDCODED_PASSWORDS
        kept = _prefilter_files(rule, FILES_5)
        paths = {fp for fp, _ in kept}
        # Files containing "password" should survive.
        assert "Assets/Scripts/Data/DatabaseConfig.cs" in paths
        assert "Assets/Scripts/Storage/SaveManager.cs" in paths

    def test_drops_clearly_irrelevant_files(self):
        rule = RULE_NO_HARDCODED_PASSWORDS
        kept = _prefilter_files(rule, FILES_5)
        paths = {fp for fp, _ in kept}
        # Pure movement code — no credential keywords.
        assert "Assets/Scripts/Player/PlayerController.cs" not in paths
        assert "Assets/Scripts/UI/HealthBar.cs" not in paths

    def test_returns_all_files_when_no_keywords(self):
        rule = CustomRule(name="", description="")
        kept = _prefilter_files(rule, FILES_5)
        assert len(kept) == len(FILES_5)

    def test_returns_all_files_when_filter_drops_everything(self):
        # A rule whose keywords match nothing in the files.
        rule = CustomRule(
            name="Check quantum entanglement alignment",
            description="Verify quantum entanglement alignment coefficients.",
        )
        kept = _prefilter_files(rule, FILES_5)
        assert len(kept) == len(FILES_5)


# ── _parse_violations ─────────────────────────────────────────────────────


class TestParseViolations:
    def test_parses_valid_json_array(self):
        batch = [("Assets/foo.cs", "content")]
        raw = json.dumps(
            [
                {
                    "file": "Assets/foo.cs",
                    "line": 3,
                    "finding": "Bad thing.",
                    "fix": "Fix it.",
                }
            ]
        )
        violations = _parse_violations(raw, "TestRule", batch)
        assert len(violations) == 1
        v = violations[0]
        assert v.file_path == "Assets/foo.cs"
        assert v.line == 3
        assert v.finding == "Bad thing."
        assert v.fix_suggestion == "Fix it."
        assert v.rule_name == "TestRule"

    def test_empty_array_returns_no_violations(self):
        batch = [("Assets/foo.cs", "content")]
        violations = _parse_violations("[]", "TestRule", batch)
        assert violations == []

    def test_malformed_json_returns_empty(self):
        batch = [("Assets/foo.cs", "content")]
        for bad in [
            "",
            "not json at all",
            "{not a list}",
            '[{"file": "Assets/foo.cs"',  # truncated
            "null",
            "true",
        ]:
            result = _parse_violations(bad, "TestRule", batch)
            assert result == [], f"Expected [] for input {bad!r}, got {result}"

    def test_hallucinated_file_path_discarded(self):
        # Model returns a path not in the batch — must be silently dropped.
        batch = [("Assets/Real.cs", "content")]
        raw = json.dumps(
            [{"file": "Assets/Hallucinated.cs", "line": 1, "finding": "X", "fix": "Y"}]
        )
        violations = _parse_violations(raw, "TestRule", batch)
        assert violations == []

    def test_missing_file_field_discarded(self):
        batch = [("Assets/foo.cs", "content")]
        raw = json.dumps([{"line": 1, "finding": "X", "fix": "Y"}])
        violations = _parse_violations(raw, "TestRule", batch)
        assert violations == []

    def test_missing_finding_field_discarded(self):
        batch = [("Assets/foo.cs", "content")]
        raw = json.dumps([{"file": "Assets/foo.cs", "line": 1, "fix": "Y"}])
        violations = _parse_violations(raw, "TestRule", batch)
        assert violations == []

    def test_non_dict_items_in_array_skipped(self):
        batch = [("Assets/foo.cs", "content")]
        raw = json.dumps(
            [
                "not a dict",
                42,
                {"file": "Assets/foo.cs", "line": 1, "finding": "X", "fix": "Y"},
            ]
        )
        violations = _parse_violations(raw, "TestRule", batch)
        assert len(violations) == 1

    def test_bad_line_number_coerced_to_zero(self):
        batch = [("Assets/foo.cs", "content")]
        raw = json.dumps(
            [
                {
                    "file": "Assets/foo.cs",
                    "line": "not-a-number",
                    "finding": "X",
                    "fix": "Y",
                }
            ]
        )
        violations = _parse_violations(raw, "TestRule", batch)
        assert violations[0].line == 0

    def test_leading_prose_before_array_is_tolerated(self):
        # The model sometimes prepends "Here are the violations:" before the JSON.
        batch = [("Assets/foo.cs", "content")]
        raw = 'Sure, here are the results:\n[{"file": "Assets/foo.cs", "line": 5, "finding": "X", "fix": "Y"}]'
        violations = _parse_violations(raw, "TestRule", batch)
        assert len(violations) == 1

    def test_truncated_json_array_parsed_best_effort(self):
        # Simulates hitting max_tokens mid-response.
        batch = [
            ("Assets/foo.cs", "content"),
            ("Assets/bar.cs", "content"),
        ]
        # Only the first item is complete; second is cut off.
        raw = '[{"file": "Assets/foo.cs", "line": 2, "finding": "X", "fix": "Y"}, {"file":'
        violations = _parse_violations(raw, "TestRule", batch)
        # Should recover the first complete item.
        assert len(violations) == 1
        assert violations[0].file_path == "Assets/foo.cs"


# ── check_custom_rules — acceptance criterion ─────────────────────────────


class TestCheckCustomRules:
    """Acceptance criterion: 1 rule × 5 C# files (3 OK, 2 violate)
    → returns exactly 2 violations without hallucinating.
    """

    def _make_mock_generate(self, violations_by_batch: list[list[dict]]):
        """Return a mock generate() that cycles through pre-built responses."""
        call_count = {"n": 0}

        def _mock(prompt, *, max_tokens, temperature, stop):
            idx = min(call_count["n"], len(violations_by_batch) - 1)
            call_count["n"] += 1
            return json.dumps(violations_by_batch[idx])

        return _mock

    def test_returns_two_violations_from_five_files(self, monkeypatch):
        # Pre-filter keeps files that contain "password" (5-char keyword):
        #   - DatabaseConfig.cs  → has "password"  → kept  (VIOLATES)
        #   - SaveManager.cs     → has "password"  → kept  (VIOLATES)
        #   - PlayerController.cs / HealthBar.cs / NetworkManager.cs → filtered
        # Both surviving files fit in one batch (batch_size=3 default), so
        # the mock must return BOTH violations in a single response.
        violations_one_batch = [
            {
                "file": "Assets/Scripts/Data/DatabaseConfig.cs",
                "line": 3,
                "finding": "Hardcoded password literal 'prod-db-s3cret!'.",
                "fix": 'Load from Environment.GetEnvironmentVariable("DB_PASS").',
            },
            {
                "file": "Assets/Scripts/Storage/SaveManager.cs",
                "line": 3,
                "finding": "Hardcoded encryption password 'save-enc-key-2024'.",
                "fix": "Load from a SecurePlayerPrefs or env var at runtime.",
            },
        ]

        monkeypatch.setattr(
            checker,
            "_llm_generate",
            self._make_mock_generate([violations_one_batch]),
        )

        results = check_custom_rules([RULE_NO_HARDCODED_PASSWORDS], FILES_5)

        assert len(results) == 2
        paths = {v.file_path for v in results}
        assert "Assets/Scripts/Data/DatabaseConfig.cs" in paths
        assert "Assets/Scripts/Storage/SaveManager.cs" in paths
        for v in results:
            assert v.rule_name == RULE_NO_HARDCODED_PASSWORDS.name
            assert v.finding
            assert v.fix_suggestion

    def test_no_violations_when_llm_returns_empty_arrays(self, monkeypatch):
        monkeypatch.setattr(checker, "_llm_generate", lambda *a, **kw: "[]")
        results = check_custom_rules([RULE_NO_HARDCODED_PASSWORDS], FILES_5)
        assert results == []

    def test_malformed_json_discarded_without_exception(self, monkeypatch):
        # Even if every LLM call returns garbage, check_custom_rules must
        # complete and return an empty list — never raise.
        monkeypatch.setattr(
            checker,
            "_llm_generate",
            lambda *a, **kw: "not valid json {{ broken",
        )
        results = check_custom_rules([RULE_NO_HARDCODED_PASSWORDS], FILES_5)
        assert results == []

    def test_multiple_rules_aggregated(self, monkeypatch):
        rule2 = CustomRule(
            name="No TODO comments",
            description="TODO comments must not remain in production code.",
        )
        files = [
            (
                "Assets/Todo.cs",
                "// TODO: remove this before shipping\npublic class Todo {}",
            ),
            ("Assets/Clean.cs", "public class Clean {}"),
        ]

        call_log: list[str] = []

        def _mock(prompt, *, max_tokens, temperature, stop):
            call_log.append(prompt)
            # Return a violation only if the rule name appears in the prompt.
            if "No hardcoded passwords" in prompt:
                return "[]"
            if "No TODO comments" in prompt:
                return json.dumps(
                    [
                        {
                            "file": "Assets/Todo.cs",
                            "line": 1,
                            "finding": "TODO comment present.",
                            "fix": "Remove it.",
                        }
                    ]
                )
            return "[]"

        monkeypatch.setattr(checker, "_llm_generate", _mock)

        results = check_custom_rules(
            [RULE_NO_HARDCODED_PASSWORDS, rule2],
            files,
        )

        # Only the TODO rule should produce a finding.
        assert len(results) == 1
        assert results[0].rule_name == "No TODO comments"
        assert results[0].file_path == "Assets/Todo.cs"

    def test_empty_files_list_returns_empty(self, monkeypatch):
        monkeypatch.setattr(checker, "_llm_generate", MagicMock())
        results = check_custom_rules([RULE_NO_HARDCODED_PASSWORDS], [])
        assert results == []
        checker._llm_generate.assert_not_called()

    def test_batch_size_respected(self, monkeypatch):
        # With 5 files and batch_size=2, expect ceil(n_relevant/2) LLM calls.
        call_count = {"n": 0}

        def _mock(*a, **kw):
            call_count["n"] += 1
            return "[]"

        monkeypatch.setattr(checker, "_llm_generate", _mock)

        check_custom_rules(
            [RULE_NO_HARDCODED_PASSWORDS],
            FILES_5,
            batch_size=2,
        )

        # Pre-filter keeps files with "password" keyword (2-3 files).
        # With batch_size=2 that's 1-2 LLM calls.
        assert 1 <= call_count["n"] <= 3


# ── _build_checker_prompt ─────────────────────────────────────────────────


class TestBuildCheckerPrompt:
    def test_prompt_ends_with_output_cue(self):
        template = registry.load_template("custom_rule_checker", "generic")
        batch = [("foo.cs", "public class Foo {}")]
        rule = CustomRule(name="Test rule", description="Test description.")
        prompt = _build_checker_prompt(rule, batch, template)
        assert prompt.endswith("\n\nOUTPUT\n")

    def test_prompt_contains_rule_and_file(self):
        template = registry.load_template("custom_rule_checker", "generic")
        batch = [("Assets/Foo.cs", 'string secret = "abc";')]
        rule = CustomRule(
            name="No secrets",
            description="No secrets in source.",
            example_violation='string x = "secret";',
        )
        prompt = _build_checker_prompt(rule, batch, template)
        assert "No secrets" in prompt
        assert "No secrets in source." in prompt
        assert 'string x = "secret";' in prompt
        assert "--- file: Assets/Foo.cs ---" in prompt
        assert 'string secret = "abc";' in prompt

    def test_few_shots_included_from_yaml(self):
        template = registry.load_template("custom_rule_checker", "generic")
        batch = [("foo.cs", "content")]
        rule = CustomRule(name="R", description="D.")
        prompt = _build_checker_prompt(rule, batch, template)
        # The YAML few-shots include these labels.
        assert "No hardcoded database connection strings" in prompt
        assert "No Debug.Log calls in non-debug scripts" in prompt
