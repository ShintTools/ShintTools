# core/tests/test_agent_prefab.py
#
# Prefab-serving tests for /agent/explain. The prefab path is what turns a
# first-time explanation from a 20-40 s CPU generation into a µs lookup, so
# these tests pin BOTH halves of the trade: the answer is served instantly,
# and the real-context prompt is still logged for fine-tuning.

from __future__ import annotations

import json

import pytest
from api.main import app
from api.routes import agent as agent_route
from fastapi.testclient import TestClient

# TestClient (sync) rather than the conftest `async_client` fixture: pytest
# here has no asyncio plugin, so `async def` tests are silently SKIPPED —
# a green run that asserted nothing. TestClient drives the same ASGI app
# synchronously and actually executes.


@pytest.fixture
def client():
    app.state.modules = ["code_validator", "naming"]
    app.state.config_path = None
    app.state.db_connected = False
    app.state.commit_sha = "abc1234"
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def prefab_env(tmp_path, monkeypatch):
    """Point the prefab loader at a one-rule file and the fine-tuning logger
    at a tmp dir, then hand back both paths."""
    prefab_file = tmp_path / "prefabs.json"
    prefab_file.write_text(
        json.dumps(
            [
                {
                    "rule_id": "CP001",
                    "rule_name": "Component lookup in Tick",
                    "example_num": 1,
                    "explanation": "Cache the component in BeginPlay instead.",
                }
            ]
        ),
        encoding="utf-8",
    )
    log_dir = tmp_path / "ft_logs"
    monkeypatch.setenv("SHINTTOOLS_PREFAB_FILE", str(prefab_file))
    monkeypatch.setenv("SHINTTOOLS_FINETUNING_DIR", str(log_dir))

    from modules.agent import prefab_explanations

    prefab_explanations.reset_cache()
    yield log_dir
    prefab_explanations.reset_cache()


@pytest.fixture
def paid_tier(monkeypatch):
    """Explain endpoints are Indie+; stub the tier resolver so no DB is needed."""

    async def _fake_tier(_api_key):
        return ("indie", "")

    monkeypatch.setattr(agent_route, "resolve_tier_detailed", _fake_tier)


def _payload(rule_id: str = "CP001") -> dict:
    return {
        "api_key": "st_test",
        "issue": {
            "rule_id": rule_id,
            "rule_name": "Component lookup in Tick",
            "rule_explanation": "FindComponentByClass in Tick scans every frame.",
            "severity": "warning",
            "file_path": "MyActor.cpp",
            "line": 42,
            "message": "Component lookup on every frame",
            "is_auto_fixable": True,
        },
    }


def _log_lines(log_dir) -> list[dict]:
    files = list(log_dir.glob("*.jsonl")) if log_dir.exists() else []
    return [
        json.loads(line)
        for f in files
        for line in f.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class TestPrefabServing:
    def test_prefab_hit_returns_instantly(
        self, client, prefab_env, paid_tier
    ):
        resp = client.post("/agent/explain", json=_payload())

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["source"] == "prefab"
        assert body["cached"] is True
        assert body["generation_seconds"] == 0.0
        assert body["explanation"] == "Cache the component in BeginPlay instead."

    def test_prefab_hit_still_logs_for_finetuning(
        self, client, prefab_env, paid_tier
    ):
        """The whole point of the earlier prefab-off decision was fine-tuning
        data. Serving a prefab must not cost us the logged prompt."""
        client.post("/agent/explain", json=_payload())

        entries = _log_lines(prefab_env)
        assert len(entries) == 1
        assert entries[0]["rule_id"] == "CP001"
        assert entries[0]["source"] == "prefab"
        # The REAL issue payload is what makes the log useful for training.
        assert entries[0]["issue_payload"]["file_path"] == "MyActor.cpp"

    def test_rule_without_prefab_falls_through(
        self, client, prefab_env, paid_tier, monkeypatch
    ):
        """A rule with no prefab must reach the cache/live path, not 500."""
        monkeypatch.setattr(agent_route, "get_cached_explanation", _no_cache)

        resp = client.post("/agent/explain", json=_payload("ZZ999"))

        assert resp.status_code == 200
        assert resp.json()["source"] != "prefab"

    def test_serve_can_be_disabled(
        self, client, prefab_env, paid_tier, monkeypatch
    ):
        """SHINTTOOLS_PREFAB_SERVE=0 restores live-generation data collection
        without a rebuild."""
        monkeypatch.setenv("SHINTTOOLS_PREFAB_SERVE", "0")
        monkeypatch.setattr(agent_route, "get_cached_explanation", _no_cache)

        resp = client.post("/agent/explain", json=_payload())

        assert resp.json()["source"] != "prefab"
        assert _log_lines(prefab_env) == []

    def test_free_tier_still_gated(self, client, prefab_env, monkeypatch):
        """Prefab serving must not become a free-tier bypass of the paid gate."""

        async def _free(_api_key):
            return ("free", "empty_key")

        monkeypatch.setattr(agent_route, "resolve_tier_detailed", _free)

        resp = client.post("/agent/explain", json=_payload())

        assert resp.status_code == 403


async def _no_cache(_key):
    """Stub for the awaited Mongo cache read — no DB in unit tests."""
    return None


class TestProductionImportPaths:
    def test_routes_never_import_top_level_agent(self):
        """Guard for the bug this suite was written alongside.

        pytest puts core/modules/ on sys.path (modules/ has no __init__.py),
        so `import agent.X` resolves in tests — but uvicorn runs from core/
        where ONLY `modules.agent.X` resolves. A production `from agent.X`
        therefore passes tests and silently ImportErrors in the container:
        that is exactly how the LOD audit's LLM enrichment sat dead for
        releases. Worse, when both paths resolve they are DIFFERENT module
        objects with different _llama/_LLAMA_LOCK state.
        """
        import pathlib
        import re

        routes_dir = pathlib.Path(agent_route.__file__).parent
        offenders = []
        for path in routes_dir.glob("*.py"):
            for num, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if re.match(r"\s*(from|import)\s+agent\.", line):
                    offenders.append(f"{path.name}:{num}: {line.strip()}")

        assert not offenders, (
            "production code must import `modules.agent.*` (uvicorn's sys.path "
            "has no top-level `agent`):\n" + "\n".join(offenders)
        )
