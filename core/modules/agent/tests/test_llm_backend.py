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


class TestLodAdapter:
    """The optional LOD LoRA adapter is applied ONLY inside lod_adapter()
    and always detached afterwards, so the Deep Code Validator (which never
    enters the context) keeps serving the unmodified Coder."""

    def test_loaded_false_by_default(self):
        assert llm_backend.lod_adapter_loaded() is False

    def test_noop_when_unconfigured(self, monkeypatch):
        # Model loaded but no adapter registered → transparent no-op.
        monkeypatch.setattr(llm_backend, "_llama", MagicMock())
        monkeypatch.setattr(llm_backend, "_lod_adapter", None)

        with llm_backend.lod_adapter() as applied:
            assert applied is False

    def test_applies_and_clears(self, monkeypatch):
        import llama_cpp

        fake_llama = MagicMock()
        fake_llama.ctx = "CTX"
        adapter = object()
        monkeypatch.setattr(llm_backend, "_llama", fake_llama)
        monkeypatch.setattr(llm_backend, "_lod_adapter", adapter)

        set_mock = MagicMock(return_value=0)  # 0 == success
        clear_mock = MagicMock()
        monkeypatch.setattr(llama_cpp, "llama_lora_adapter_set", set_mock)
        monkeypatch.setattr(llama_cpp, "llama_lora_adapter_clear", clear_mock)

        with llm_backend.lod_adapter() as applied:
            assert applied is True
            set_mock.assert_called_once_with("CTX", adapter, 1.0)
            clear_mock.assert_not_called()  # still active inside the block

        clear_mock.assert_called_once_with("CTX")  # detached on exit

    def test_clears_on_exception(self, monkeypatch):
        import llama_cpp

        fake_llama = MagicMock()
        fake_llama.ctx = "CTX"
        monkeypatch.setattr(llm_backend, "_llama", fake_llama)
        monkeypatch.setattr(llm_backend, "_lod_adapter", object())
        monkeypatch.setattr(
            llama_cpp, "llama_lora_adapter_set", MagicMock(return_value=0)
        )
        clear_mock = MagicMock()
        monkeypatch.setattr(llama_cpp, "llama_lora_adapter_clear", clear_mock)

        with pytest.raises(ValueError):
            with llm_backend.lod_adapter():
                raise ValueError("boom")

        clear_mock.assert_called_once_with("CTX")  # never left applied

    def test_scale_from_env(self, monkeypatch):
        import llama_cpp

        monkeypatch.setenv("SHINTTOOLS_LOD_LORA_SCALE", "0.5")
        fake_llama = MagicMock()
        fake_llama.ctx = "CTX"
        monkeypatch.setattr(llm_backend, "_llama", fake_llama)
        monkeypatch.setattr(llm_backend, "_lod_adapter", object())
        set_mock = MagicMock(return_value=0)
        monkeypatch.setattr(llama_cpp, "llama_lora_adapter_set", set_mock)
        monkeypatch.setattr(llama_cpp, "llama_lora_adapter_clear", MagicMock())

        with llm_backend.lod_adapter():
            pass

        assert set_mock.call_args.args[2] == 0.5

    def test_init_adapter_noop_without_env(self, monkeypatch):
        monkeypatch.delenv("SHINTTOOLS_LOD_LORA_PATH", raising=False)
        monkeypatch.setattr(llm_backend, "_llama", MagicMock())

        llm_backend._init_lod_adapter()

        assert llm_backend._lod_adapter is None

    def test_init_adapter_noop_when_file_missing(self, monkeypatch, tmp_path):
        monkeypatch.setenv(
            "SHINTTOOLS_LOD_LORA_PATH", str(tmp_path / "nope.gguf")
        )
        monkeypatch.setattr(llm_backend, "_llama", MagicMock())

        llm_backend._init_lod_adapter()

        assert llm_backend._lod_adapter is None

    def test_init_adapter_registers_when_present(self, monkeypatch, tmp_path):
        import llama_cpp

        adapter_file = tmp_path / "lod.gguf"
        adapter_file.write_bytes(b"fake")
        monkeypatch.setenv("SHINTTOOLS_LOD_LORA_PATH", str(adapter_file))
        fake_llama = MagicMock()
        fake_llama.model = "MODEL"
        monkeypatch.setattr(llm_backend, "_llama", fake_llama)

        sentinel = object()
        init_mock = MagicMock(return_value=sentinel)
        monkeypatch.setattr(llama_cpp, "llama_lora_adapter_init", init_mock)

        llm_backend._init_lod_adapter()

        init_mock.assert_called_once_with("MODEL", str(adapter_file).encode("utf-8"))
        assert llm_backend._lod_adapter is sentinel
