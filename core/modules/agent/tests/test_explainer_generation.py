# core/modules/agent/tests/test_explainer_generation.py
#
# Generation-parameter tests for the explainer: the knobs that decide how
# LONG an explanation takes to produce on CPU. They monkeypatch the llama
# singleton so nothing here needs the GGUF on disk.

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from agent import explainer, llm_backend
from agent.prompts import registry


@pytest.fixture(autouse=True)
def _reset_state():
    llm_backend.unload_model()
    registry.reset_cache()
    yield
    llm_backend.unload_model()
    registry.reset_cache()


def _cpp_issue() -> dict:
    return {
        "rule_id": "CP001",
        "rule_name": "Component lookup in Tick",
        "rule_explanation": "FindComponentByClass in Tick is a per-frame scan.",
        "engine": "ue5",
        "file_path": "MyActor.cpp",
        "line": 42,
        "message": "Component lookup on every frame",
        "is_auto_fixable": True,
        "snippet": "UHealthComponent* H = FindComponentByClass<UHealthComponent>();",
    }


class TestGenerationParams:
    """Every generation pays ~10-15 tok/s on CPU, so max_tokens and the stop
    set ARE the latency budget: the model must stop when the explanation ends
    rather than run to the token ceiling."""

    def test_template_stop_tokens_reach_llama(self, monkeypatch):
        fake = MagicMock(return_value={"choices": [{"text": "Explanation here."}]})
        monkeypatch.setattr(llm_backend, "_llama", fake)

        explainer.explain_issue(_cpp_issue())

        stop = fake.call_args.kwargs["stop"]
        # "\nINPUT" cuts the model when it starts mimicking the few-shot
        # delimiter without a preceding blank line — "\n\n" alone misses that.
        assert "\nINPUT" in stop
        assert "\n\n" in stop

    def test_max_tokens_capped_at_template_value(self, monkeypatch):
        fake = MagicMock(return_value={"choices": [{"text": "Explanation here."}]})
        monkeypatch.setattr(llm_backend, "_llama", fake)

        explainer.explain_issue(_cpp_issue())

        # 150, not the old 220: the post-trim discards everything past the
        # last complete sentence anyway, so generating to 220 burned ~7 s of
        # CPU on tokens that never reached the user.
        assert fake.call_args.kwargs["max_tokens"] == 150

    def test_explicit_max_tokens_overrides_template(self, monkeypatch):
        fake = MagicMock(return_value={"choices": [{"text": "Explanation here."}]})
        monkeypatch.setattr(llm_backend, "_llama", fake)

        explainer.explain_issue(_cpp_issue(), max_tokens=64)

        assert fake.call_args.kwargs["max_tokens"] == 64


class TestRegistryDefaults:
    def test_fallback_max_tokens_is_150(self, tmp_path, monkeypatch):
        """A template with no `generation:` block falls back to 150 — the
        fallback must not silently reintroduce the old 220 ceiling."""
        module_dir = tmp_path / "unreal_cpp" / "ue5"
        module_dir.mkdir(parents=True)
        (module_dir / "v1.yaml").write_text(
            "version: 1\n"
            "model: test\n"
            "system: |-\n"
            "  Be brief.\n"
            "few_shots: |-\n"
            "  INPUT\n"
            "  EXPLANATION\n"
            "stop_tokens:\n"
            '  - "\\n\\n"\n',
            encoding="utf-8",
        )
        monkeypatch.setenv("SHINTTOOLS_PROMPT_REGISTRY_DIR", str(tmp_path))
        registry.reset_cache()

        template = registry.load_template("unreal_cpp", "ue5")

        assert template.max_tokens == 150
