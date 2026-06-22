# core/modules/agent/tests/test_prompt_registry.py
#
# Tests for the server-side prompt registry (Fase A).
#
# These tests do NOT load the GGUF model — they exercise the YAML
# loader, the (module, engine) resolution, prompt assembly, and the
# explainer's integration with the registry. The acceptance criterion
# "edit YAML on disk and restart → output changes" is enforced by
# `test_yaml_edit_changes_rendered_prompt`: it writes a YAML, builds
# a prompt, edits the YAML, resets the cache (simulating a restart),
# rebuilds, and asserts the prompt changed.

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Generator

import pytest
from agent import explainer
from agent.prompts import registry


@pytest.fixture
def isolated_registry(monkeypatch, tmp_path: Path) -> Generator[Path, None, None]:
    """Point the registry at an empty tmp dir and clear the cache.

    Each test gets a clean slate so a leftover YAML from one case
    can't leak into another via the in-memory cache.
    """
    templates_root = tmp_path / "templates"
    templates_root.mkdir()
    monkeypatch.setenv("SHINTTOOLS_PROMPT_REGISTRY_DIR", str(templates_root))
    registry.reset_cache()
    yield templates_root
    registry.reset_cache()


def _write_yaml(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")


_MINIMAL_YAML = """
    version: 1
    model: "test-model"
    system: "You are a test reviewer."
    few_shots: "INPUT\\nrule_name: demo\\nEXPLANATION\\nDemo answer."
    stop_tokens:
      - "\\n\\n"
    generation:
      max_tokens: 42
      temperature: 0.5
"""


# ── Loader ─────────────────────────────────────────────────────────────────


class TestLoadTemplate:
    def test_loads_shared_fallback_when_module_dir_missing(
        self, isolated_registry: Path
    ):
        _write_yaml(isolated_registry / "_shared" / "v1.yaml", _MINIMAL_YAML)

        template = registry.load_template("unreal_cpp", "ue5")

        assert template.system == "You are a test reviewer."
        assert template.max_tokens == 42
        assert template.temperature == 0.5
        assert template.stop_tokens == ("\n\n",)
        assert template.source_path == isolated_registry / "_shared" / "v1.yaml"

    def test_module_override_wins_over_shared(self, isolated_registry: Path):
        _write_yaml(isolated_registry / "_shared" / "v1.yaml", _MINIMAL_YAML)
        _write_yaml(
            isolated_registry / "unreal_cpp" / "ue5" / "v1.yaml",
            """
                version: 1
                system: "Override system."
                generation:
                  max_tokens: 100
                  temperature: 0.1
            """,
        )

        template = registry.load_template("unreal_cpp", "ue5")

        assert template.system == "Override system."
        assert template.max_tokens == 100
        # When the override omits an optional field (stop_tokens here),
        # we get the default — we deliberately don't merge with shared
        # so the override is a complete declarative replacement.
        assert template.stop_tokens == ()

    def test_latest_picks_highest_version_in_chosen_dir(self, isolated_registry: Path):
        shared_dir = isolated_registry / "_shared"
        _write_yaml(
            shared_dir / "v1.yaml",
            """
                version: 1
                system: "v1 system"
            """,
        )
        _write_yaml(
            shared_dir / "v3.yaml",
            """
                version: 3
                system: "v3 system"
            """,
        )
        _write_yaml(
            shared_dir / "v2.yaml",
            """
                version: 2
                system: "v2 system"
            """,
        )

        template = registry.load_template("_shared", "_shared", version="latest")

        assert template.version == 3
        assert template.system == "v3 system"

    def test_explicit_version_loads_that_file(self, isolated_registry: Path):
        _write_yaml(
            isolated_registry / "_shared" / "v1.yaml",
            """
                version: 1
                system: "v1 system"
            """,
        )
        _write_yaml(
            isolated_registry / "_shared" / "v2.yaml",
            """
                version: 2
                system: "v2 system"
            """,
        )

        template = registry.load_template("_shared", "_shared", version="1")

        assert template.version == 1
        assert template.system == "v1 system"

    def test_missing_template_raises_with_searched_paths(self, isolated_registry: Path):
        # No YAMLs written. The error should name what we looked at.
        with pytest.raises(FileNotFoundError) as excinfo:
            registry.load_template("unreal_cpp", "ue5")
        message = str(excinfo.value)
        assert "unreal_cpp" in message
        assert "ue5" in message
        assert "_shared" in message

    def test_missing_system_field_raises(self, isolated_registry: Path):
        _write_yaml(
            isolated_registry / "_shared" / "v1.yaml",
            """
                version: 1
                model: "x"
            """,
        )
        with pytest.raises(ValueError, match="system"):
            registry.load_template("_shared", "_shared")

    def test_cache_returns_same_object(self, isolated_registry: Path):
        _write_yaml(isolated_registry / "_shared" / "v1.yaml", _MINIMAL_YAML)

        first = registry.load_template("unreal_cpp", "ue5")
        second = registry.load_template("unreal_cpp", "ue5")

        assert first is second


# ── Module/engine resolution ───────────────────────────────────────────────


class TestResolveModuleEngine:
    def test_explicit_module_engine_win(self):
        module, engine = registry.resolve_module_engine(
            {"module": "custom_mod", "engine": "custom_eng", "rule_id": "CS001"}
        )
        assert (module, engine) == ("custom_mod", "custom_eng")

    def test_cpp_prefix_routes_to_unreal_cpp(self):
        for rule_id in ("CS001", "CP004", "CB010", "CM002"):
            module, engine = registry.resolve_module_engine({"rule_id": rule_id})
            assert (module, engine) == ("unreal_cpp", "ue5"), rule_id

    def test_blueprint_prefix_routes_to_unreal_blueprint(self):
        for rule_id in ("BPB001", "BPP003", "BPM004", "BPS002"):
            module, engine = registry.resolve_module_engine({"rule_id": rule_id})
            assert (module, engine) == ("unreal_blueprint", "ue5"), rule_id

    def test_naming_prefix_defaults_to_ue5(self):
        module, engine = registry.resolve_module_engine({"rule_id": "NM003"})
        assert (module, engine) == ("naming", "ue5")

    def test_unknown_prefix_falls_back_to_shared(self):
        module, engine = registry.resolve_module_engine({"rule_id": "XYZ999"})
        assert (module, engine) == ("_shared", "_shared")

    def test_missing_rule_id_falls_back_to_shared(self):
        module, engine = registry.resolve_module_engine({})
        assert (module, engine) == ("_shared", "_shared")


# ── Assembly ───────────────────────────────────────────────────────────────


class TestAssemble:
    def test_glues_system_few_shots_issue_and_trailing_cue(
        self, isolated_registry: Path
    ):
        _write_yaml(isolated_registry / "_shared" / "v1.yaml", _MINIMAL_YAML)
        template = registry.load_template("_shared", "_shared")

        prompt = registry.assemble(template, "INPUT\nrule_name: foo")

        assert prompt.startswith("You are a test reviewer.")
        assert "INPUT\nrule_name: foo" in prompt
        # Few-shots sit between system and the live issue block.
        assert prompt.index("Demo answer.") < prompt.index("rule_name: foo")
        assert prompt.endswith("\n\nEXPLANATION\n")

    def test_empty_few_shots_drops_the_section_without_double_gap(
        self, isolated_registry: Path
    ):
        _write_yaml(
            isolated_registry / "_shared" / "v1.yaml",
            """
                version: 1
                system: "Sys."
                few_shots: ""
            """,
        )
        template = registry.load_template("_shared", "_shared")

        prompt = registry.assemble(template, "INPUT\nrule_name: foo")

        # Only one "\n\n" between system and issue, then "EXPLANATION".
        assert prompt == "Sys.\n\nINPUT\nrule_name: foo\n\nEXPLANATION\n"


# ── Explainer integration ──────────────────────────────────────────────────


_SAMPLE_ISSUE = {
    "rule_id": "CS001",
    "rule_name": "GetWorld without null-check",
    "rule_explanation": (
        "GetWorld() can return nullptr in editor utilities, "
        "commandlets, or during shutdown."
    ),
    "is_auto_fixable": True,
    "file_path": "Source/MyActor.cpp",
    "line": 12,
    "message": "GetWorld() may return nullptr; dereferencing it crashes.",
    "context_before": (
        "UWorld* World = GetWorld();\n"
        "AActor* Spawned = World->SpawnActor<AActor>(SpawnClass);"
    ),
}


class TestExplainerUsesRegistry:
    def test_build_explainer_prompt_contains_template_and_issue(
        self, isolated_registry: Path
    ):
        _write_yaml(
            isolated_registry / "_shared" / "v1.yaml",
            """
                version: 1
                system: "REGISTRY_SYSTEM_MARKER"
                few_shots: "REGISTRY_FEWSHOT_MARKER"
            """,
        )

        prompt = explainer.build_explainer_prompt(_SAMPLE_ISSUE)

        assert "REGISTRY_SYSTEM_MARKER" in prompt
        assert "REGISTRY_FEWSHOT_MARKER" in prompt
        # Issue fields render in the live INPUT block.
        assert "rule_name: GetWorld without null-check" in prompt
        assert "is_auto_fixable: true" in prompt
        assert "Source/MyActor.cpp" in prompt
        assert "World->SpawnActor" in prompt
        assert prompt.endswith("\n\nEXPLANATION\n")

    def test_module_specific_yaml_takes_precedence(self, isolated_registry: Path):
        _write_yaml(
            isolated_registry / "_shared" / "v1.yaml",
            """
                version: 1
                system: "SHARED_SYSTEM"
            """,
        )
        _write_yaml(
            isolated_registry / "unreal_cpp" / "ue5" / "v1.yaml",
            """
                version: 1
                system: "UNREAL_CPP_SYSTEM"
            """,
        )

        # rule_id CS001 → unreal_cpp / ue5
        prompt = explainer.build_explainer_prompt(_SAMPLE_ISSUE)

        assert "UNREAL_CPP_SYSTEM" in prompt
        assert "SHARED_SYSTEM" not in prompt

    def test_explain_issue_uses_template_max_tokens(
        self, isolated_registry: Path, monkeypatch
    ):
        # YAML pins max_tokens=7 / temperature=0.9 — the explainer
        # must pass those through to the LLM unless the caller
        # explicitly overrides.
        _write_yaml(
            isolated_registry / "_shared" / "v1.yaml",
            """
                version: 1
                system: "Sys."
                stop_tokens: ["\\n\\n"]
                generation:
                  max_tokens: 7
                  temperature: 0.9
            """,
        )
        seen: dict[str, object] = {}

        def fake_generate(prompt, *, max_tokens, temperature, stop, repeat_penalty=1.1):
            seen["max_tokens"] = max_tokens
            seen["temperature"] = temperature
            seen["stop"] = list(stop)
            return "ok"

        monkeypatch.setattr(explainer, "_llm_generate", fake_generate)

        result = explainer.explain_issue(_SAMPLE_ISSUE)

        assert result == "ok"
        assert seen["max_tokens"] == 7
        assert seen["temperature"] == 0.9
        assert seen["stop"] == ["\n\n"]

    def test_explicit_caller_args_override_template(
        self, isolated_registry: Path, monkeypatch
    ):
        _write_yaml(
            isolated_registry / "_shared" / "v1.yaml",
            """
                version: 1
                system: "Sys."
                generation:
                  max_tokens: 200
                  temperature: 0.2
            """,
        )
        seen: dict[str, object] = {}

        def fake_generate(prompt, *, max_tokens, temperature, stop, repeat_penalty=1.1):
            seen["max_tokens"] = max_tokens
            seen["temperature"] = temperature
            return "ok"

        monkeypatch.setattr(explainer, "_llm_generate", fake_generate)

        explainer.explain_issue(_SAMPLE_ISSUE, max_tokens=33, temperature=0.05)

        assert seen["max_tokens"] == 33
        assert seen["temperature"] == 0.05


# ── Acceptance criteria (Fase A) ───────────────────────────────────────────


class TestAcceptanceCriteria:
    def test_yaml_edit_changes_rendered_prompt(self, isolated_registry: Path):
        """Criterion 2: changing a YAML on disk and restarting changes
        the output without touching Python.

        We simulate the restart by calling reset_cache() between the
        two loads — that's exactly what process boot does (in-memory
        cache starts empty).
        """
        yaml_path = isolated_registry / "_shared" / "v1.yaml"
        _write_yaml(
            yaml_path,
            """
                version: 1
                system: "FIRST_REV"
            """,
        )

        before = explainer.build_explainer_prompt(_SAMPLE_ISSUE)
        assert "FIRST_REV" in before

        # Editor goes in, swaps a word, restarts the API.
        _write_yaml(
            yaml_path,
            """
                version: 1
                system: "SECOND_REV"
            """,
        )
        registry.reset_cache()

        after = explainer.build_explainer_prompt(_SAMPLE_ISSUE)
        assert "SECOND_REV" in after
        assert "FIRST_REV" not in after
        assert before != after

    def test_warmup_uses_registry_template(self, isolated_registry: Path, monkeypatch):
        """Criterion 3: warm-up runs through the registry, so the
        warmed-up prefix is the one real requests will hit.
        """
        _write_yaml(
            isolated_registry / "_shared" / "v1.yaml",
            """
                version: 1
                system: "WARMUP_MARKER_FROM_YAML"
                few_shots: ""
            """,
        )
        captured: dict[str, object] = {}

        def fake_generate(prompt, *, max_tokens, temperature, stop, repeat_penalty=1.1):
            captured["prompt"] = prompt
            captured["max_tokens"] = max_tokens
            return ""

        monkeypatch.setattr(explainer, "_llm_generate", fake_generate)

        elapsed = explainer.warmup()

        assert elapsed >= 0.0
        assert captured["max_tokens"] == 1
        assert "WARMUP_MARKER_FROM_YAML" in str(captured["prompt"])


# ── Shared template ships with the package ─────────────────────────────────


class TestShippedTemplates:
    """Smoke-load every bundled template to guard against YAML syntax
    errors or missing required fields introduced during refactors.
    """

    # (module, engine) pairs that must have their own template file.
    EXPECTED_TEMPLATES = [
        ("unreal_cpp", "ue5"),
        ("unreal_blueprint", "ue5"),
        ("unity_csharp", "unity6"),
        ("unity_vs", "unity6"),
        ("naming", "ue5"),
        ("naming", "unity6"),
    ]

    def _load(self, monkeypatch, module, engine):
        monkeypatch.delenv("SHINTTOOLS_PROMPT_REGISTRY_DIR", raising=False)
        registry.reset_cache()
        try:
            return registry.load_template(module, engine)
        finally:
            registry.reset_cache()

    def test_shared_fallback_has_system_prompt(self, monkeypatch):
        t = self._load(monkeypatch, "_shared", "_shared")
        assert t.system
        assert "senior code reviewer" in t.system
        assert "\n\n" in t.stop_tokens
        # _shared is now a true fallback — it intentionally has no few-shots.
        assert t.few_shots == ""

    def test_each_module_has_dedicated_template(self, monkeypatch):
        for module, engine in self.EXPECTED_TEMPLATES:
            t = self._load(monkeypatch, module, engine)
            assert t.system, f"{module}/{engine} missing system"
            assert t.few_shots, f"{module}/{engine} has no few-shots"
            # path is …/templates/{module}/{engine}/v1.yaml
            assert (
                t.source_path.parent.name == engine
            ), f"{module}/{engine} resolved to wrong file: {t.source_path}"
            assert (
                t.source_path.parent.parent.name == module
            ), f"{module}/{engine} resolved to wrong file: {t.source_path}"

    def test_module_templates_do_not_fall_back_to_shared(self, monkeypatch):
        for module, engine in self.EXPECTED_TEMPLATES:
            t = self._load(monkeypatch, module, engine)
            assert "_shared" not in str(
                t.source_path
            ), f"{module}/{engine} incorrectly fell back to _shared"
