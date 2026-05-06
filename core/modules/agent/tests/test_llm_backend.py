# core/modules/agent/tests/test_llm_backend.py
#
# Unit tests for the LLM backend wrapper. These tests must NOT require
# the actual GGUF model on disk — they monkeypatch the module-level
# `_llama` singleton to keep CI fast and offline-friendly.

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from agent import llm_backend


@pytest.fixture(autouse=True)
def _reset_state():
    """Each test starts with no model loaded. Restored after the test
    so leftover state from one test never leaks into the next."""
    llm_backend.unload_model()
    yield
    llm_backend.unload_model()


class TestGenerate:
    def test_returns_text_from_llama_response(self, monkeypatch):
        fake_llama = MagicMock(return_value={"choices": [{"text": "hello world"}]})
        monkeypatch.setattr(llm_backend, "_llama", fake_llama)

        result = llm_backend.generate("hi")

        assert result == "hello world"

    def test_passes_generation_params(self, monkeypatch):
        fake_llama = MagicMock(return_value={"choices": [{"text": "ok"}]})
        monkeypatch.setattr(llm_backend, "_llama", fake_llama)

        llm_backend.generate(
            "prompt",
            max_tokens=42,
            temperature=0.7,
            stop=["</s>"],
        )

        fake_llama.assert_called_once_with(
            "prompt",
            max_tokens=42,
            temperature=0.7,
            stop=["</s>"],
        )

    def test_raises_when_model_not_loaded(self):
        with pytest.raises(RuntimeError, match="Model not loaded"):
            llm_backend.generate("hi")


class TestLoadModel:
    def test_raises_when_gguf_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            llm_backend,
            "_resolved_model_path",
            lambda: tmp_path / "missing.gguf",
        )

        with pytest.raises(RuntimeError, match="Model file not found"):
            llm_backend.load_model()

    def test_idempotent_when_already_loaded(self, monkeypatch):
        sentinel = object()
        monkeypatch.setattr(llm_backend, "_llama", sentinel)

        # Should not attempt to reload — even if the path were missing,
        # the early return saves us.
        llm_backend.load_model()

        assert llm_backend._llama is sentinel


class TestResolvedModelPath:
    def test_uses_env_overrides(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SHINTTOOLS_MODELS_DIR", str(tmp_path))
        monkeypatch.setenv("SHINTTOOLS_MODEL_FILE", "custom.gguf")

        path = llm_backend._resolved_model_path()

        assert path == tmp_path / "custom.gguf"

    def test_falls_back_to_defaults(self, monkeypatch):
        monkeypatch.delenv("SHINTTOOLS_MODELS_DIR", raising=False)
        monkeypatch.delenv("SHINTTOOLS_MODEL_FILE", raising=False)

        path = llm_backend._resolved_model_path()

        assert path.name == llm_backend.DEFAULT_MODEL_FILE
        assert path.parent == Path(llm_backend.DEFAULT_MODELS_DIR)


class TestIsLoaded:
    def test_false_when_not_loaded(self):
        assert llm_backend.is_loaded() is False

    def test_true_after_setting_singleton(self, monkeypatch):
        monkeypatch.setattr(llm_backend, "_llama", object())
        assert llm_backend.is_loaded() is True
