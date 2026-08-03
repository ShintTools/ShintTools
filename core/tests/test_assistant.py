# core/tests/test_assistant.py
#
# M0 — conversation skeleton + per-intent tier gating.
#
# The assistant serves EVERY tier; what a tier cannot do is an intent-level
# 403, never a blanket 403 on the route. Mongo is absent in this test
# environment, so these also exercise the in-process fallback store.

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from modules.assistant.tiers import (
    ALL_INTENTS,
    allowed_intents_for,
    assistant_capabilities,
)


def _patch_tier(monkeypatch, tier: str):
    monkeypatch.setattr(
        "api.routes.assistant.resolve_tier_detailed",
        AsyncMock(return_value=(tier, "")),
    )


class TestCapabilityTable:
    def test_every_tier_allows_something(self):
        for tier in ("free", "indie", "studio", "enterprise"):
            assert allowed_intents_for(tier), tier

    def test_free_is_a_subset_of_indie_is_a_subset_of_studio(self):
        assert allowed_intents_for("free") < allowed_intents_for("indie")
        assert allowed_intents_for("indie") < allowed_intents_for("studio")
        assert allowed_intents_for("studio") == ALL_INTENTS

    def test_enterprise_is_exactly_studio(self):
        # GH #37: Enterprise is a superset of Studio and must never drift.
        assert assistant_capabilities("enterprise") is assistant_capabilities(
            "studio"
        )

    def test_unknown_tier_defaults_to_free(self):
        assert allowed_intents_for("") == allowed_intents_for("free")
        assert allowed_intents_for("banana") == allowed_intents_for("free")


class TestMessageEndpoint:
    @pytest.mark.anyio
    async def test_free_tier_can_talk(self, async_client, monkeypatch):
        _patch_tier(monkeypatch, "free")
        resp = await async_client.post(
            "/assistant/message",
            json={"message": "hola", "intent": "general_help"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["conversation_id"].startswith("ac-")
        assert data["tier"] == "free"
        assert data["reply"]["raw_text"]

    @pytest.mark.anyio
    async def test_free_tier_gated_per_intent_not_per_route(
        self, async_client, monkeypatch
    ):
        _patch_tier(monkeypatch, "free")
        resp = await async_client.post(
            "/assistant/message",
            json={"message": "simula esto", "intent": "simulate_change"},
        )
        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert detail["current_tier"] == "free"
        assert "general_help" in detail["allowed_intents"]

    @pytest.mark.anyio
    async def test_studio_reaches_every_intent_gate(
        self, async_client, monkeypatch
    ):
        _patch_tier(monkeypatch, "studio")
        for intent in sorted(ALL_INTENTS):
            resp = await async_client.post(
                "/assistant/message",
                json={"message": "x", "intent": intent},
            )
            assert resp.status_code == 200, intent

    @pytest.mark.anyio
    async def test_conversation_continues_across_turns(
        self, async_client, monkeypatch
    ):
        _patch_tier(monkeypatch, "studio")
        first = await async_client.post(
            "/assistant/message", json={"message": "primero"}
        )
        conv_id = first.json()["conversation_id"]

        second = await async_client.post(
            "/assistant/message",
            json={"message": "segundo", "conversation_id": conv_id},
        )
        assert second.json()["conversation_id"] == conv_id

        history = await async_client.get(
            f"/assistant/conversations/{conv_id}"
        )
        turns = history.json()["turns"]
        # 2 user turns + 2 assistant replies, in order.
        assert [t["role"] for t in turns] == [
            "user", "assistant", "user", "assistant",
        ]
        assert turns[0]["raw_text"] == "primero"
        assert turns[2]["raw_text"] == "segundo"

    @pytest.mark.anyio
    async def test_unknown_conversation_is_404(self, async_client, monkeypatch):
        _patch_tier(monkeypatch, "studio")
        resp = await async_client.post(
            "/assistant/message",
            json={"message": "x", "conversation_id": "ac-nope"},
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_unknown_intent_falls_back_to_help_not_500(
        self, async_client, monkeypatch
    ):
        _patch_tier(monkeypatch, "free")
        resp = await async_client.post(
            "/assistant/message",
            json={"message": "x", "intent": "hack_the_planet"},
        )
        assert resp.status_code == 200
        assert resp.json()["intent"] == "general_help"

    @pytest.mark.anyio
    async def test_capabilities_endpoint_reports_the_table(
        self, async_client, monkeypatch
    ):
        _patch_tier(monkeypatch, "indie")
        resp = await async_client.get("/assistant/capabilities")
        data = resp.json()
        assert data["tier"] == "indie"
        assert data["memory"] == "session"
        assert "why_rule" in data["intents"]
        assert "simulate_change" not in data["intents"]
