# core/tests/test_assistant_context.py
#
# M8 — conversation context, deterministic continuation, and streaming.
#
# The gap M8 closes: turns and compaction digests were being written but
# never read back, so a follow-up ("and why does that matter?") had nothing
# to resolve against — the referent lived in a turn nobody looked at. These
# tests pin both halves: that the thread reaches the prompt, and that a
# continuation can only ever inherit a target the user already had on
# screen.
#
# As with test_assistant.py, no LLM is loaded here, so what runs is the
# free-image path: keyword routing and deterministic degradation.

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from modules.assistant.actions import explain_finding

_FINDING = {
    "rule_id": "LT003",
    "rule_name": "Texture over budget",
    "rule_explanation": (
        "Texture resolution exceeds the slot budget for its LOD group."
    ),
    "message": "4096x4096 texture exceeds the 2048 px max-size budget.",
    "fix_suggestion": "Set max_texture_size to 2048.",
    "auto_fixable": True,
}


def _patch_tier(monkeypatch, tier: str):
    monkeypatch.setattr(
        "api.routes.assistant.resolve_tier_detailed",
        AsyncMock(return_value=(tier, "")),
    )


def _parse_sse(body: str) -> list[dict]:
    return [
        json.loads(line[len("data: "):])
        for line in body.split("\n\n")
        if line.startswith("data: ")
    ]


# ── Continuation detection ────────────────────────────────────────────────────


class TestIsContinuation:
    def test_short_anaphoric_openers_continue(self):
        from modules.assistant.conversation_context import is_continuation

        for message in (
            "y por que?",
            "and why does that matter?",
            "mas simple",
            "ok, but for mobile?",
            "explain that",
            "eso",
            "que significa exactamente",
        ):
            assert is_continuation(message), message

    def test_a_message_naming_its_own_target_does_not(self):
        from modules.assistant.conversation_context import is_continuation

        # Carries its own subject, so it deserves a fresh classification
        # even though it is short and opens with a continuation word.
        assert not is_continuation("and why LT003?")
        assert not is_continuation("y Source/Foo.cpp?")

    def test_a_long_message_does_not(self):
        from modules.assistant.conversation_context import is_continuation

        assert not is_continuation(
            "and now explain how the texture streaming pool interacts with "
            "the bias we set on the character meshes last week"
        )

    def test_empty_is_not_a_continuation(self):
        from modules.assistant.conversation_context import is_continuation

        assert not is_continuation("")
        assert not is_continuation("   ")


class TestLastGrounding:
    def test_picks_the_newest_value_of_each_field_independently(self):
        from modules.assistant.conversation_context import last_grounding

        conversation = {
            "turns": [
                {"role": "user", "intent": "explain_finding",
                 "context_ref": "an-old", "rule_id": "LT003", "asset_path": ""},
                {"role": "assistant", "intent": "explain_finding",
                 "context_ref": "an-new", "rule_id": "", "asset_path": ""},
            ]
        }
        found = last_grounding(conversation)
        # Newest analysis, but the rule is still the one the user named.
        assert found["context_ref"] == "an-new"
        assert found["rule_id"] == "LT003"
        assert found["intent"] == "explain_finding"

    def test_general_help_is_never_inherited(self):
        from modules.assistant.conversation_context import last_grounding

        conversation = {
            "turns": [
                {"role": "user", "intent": "why_rule", "rule_id": "CP006"},
                {"role": "assistant", "intent": "general_help"},
            ]
        }
        # Otherwise every follow-up after a help reply would recite the help.
        assert last_grounding(conversation)["intent"] == "why_rule"

    def test_empty_conversation_grounds_nothing(self):
        from modules.assistant.conversation_context import last_grounding

        assert last_grounding(None) == {
            "intent": "", "context_ref": "", "rule_id": "", "asset_path": ""
        }


# ── History assembly ──────────────────────────────────────────────────────────


class TestBuildHistory:
    def test_no_thread_no_block(self):
        from modules.assistant.conversation_context import build_history

        assert build_history(None) == ""
        assert build_history({"turns": []}) == ""

    def test_summary_and_turns_both_land(self):
        from modules.assistant.conversation_context import build_history

        block = build_history(
            {"turns": [{"role": "assistant",
                        "raw_text": "LT003 is about size."}]},
            "[explain_finding] why is this flagged",
        )
        assert "Earlier in this conversation:" in block
        assert "explain_finding" in block
        assert "Assistant: LT003 is about size." in block

    def test_trailing_user_turn_is_not_echoed_back(self):
        from modules.assistant.conversation_context import build_history

        # The question being answered is handed to the model separately;
        # showing it twice only invites an answer to the older copy.
        block = build_history(
            {"turns": [
                {"role": "assistant", "raw_text": "earlier answer"},
                {"role": "user", "raw_text": "the question being answered"},
            ]}
        )
        assert "earlier answer" in block
        assert "the question being answered" not in block

    def test_block_is_bounded(self):
        from modules.assistant.conversation_context import (
            MAX_HISTORY_CHARS,
            build_history,
        )

        conversation = {
            "turns": [
                {"role": "assistant", "raw_text": "x" * 5000} for _ in range(10)
            ]
        }
        assert len(build_history(conversation)) <= MAX_HISTORY_CHARS + 1


# ── Narration ─────────────────────────────────────────────────────────────────


class TestNarrator:
    def test_history_reaches_the_prompt(self):
        from modules.assistant import narrator

        prompt = narrator.build_prompt("and why?", "Rule: LT003", "User: hi")
        assert "CONVERSATION SO FAR:" in prompt
        assert "User: hi" in prompt
        assert "Rule: LT003" in prompt
        assert prompt.rstrip().endswith("ASSISTANT:")

    def test_no_history_no_empty_section(self):
        from modules.assistant import narrator

        assert "CONVERSATION SO FAR:" not in narrator.build_prompt(
            "why?", "Rule: LT003"
        )

    def test_data_block_carries_only_engine_fields(self):
        from modules.assistant import narrator

        block = narrator.finding_data_block(dict(_FINDING))
        assert "LT003" in block
        assert "Texture over budget" in block
        # A field the engine never set must not appear as an empty slot for
        # the model to helpfully fill in.
        assert "Line:" not in block

    def test_narrate_returns_none_without_a_model(self):
        from modules.assistant import narrator

        # Free image / model not loaded -> the caller degrades, never crashes.
        assert narrator.narrate("why?", "Rule: LT003") is None


class TestConversationalExplain:
    @pytest.mark.anyio
    async def test_prepare_separates_target_resolution_from_narration(self):
        prepared = await explain_finding.prepare({"finding": dict(_FINDING)})
        assert prepared["finding"]["rule_id"] == "LT003"

        missing = await explain_finding.prepare({"message": "why?"})
        assert "error" in missing

    @pytest.mark.anyio
    async def test_history_does_not_break_the_degraded_path(self):
        result = await explain_finding.run(
            {"finding": dict(_FINDING), "history": "User: why?",
             "message": "and?"}
        )
        assert result["resolved"] is True
        assert result["degraded"] is True
        assert "Texture over budget" in result["reply"]


# ── End to end ────────────────────────────────────────────────────────────────


class TestContinuationEndToEnd:
    @pytest.mark.anyio
    async def test_followup_inherits_intent_and_grounding(
        self, async_client, monkeypatch
    ):
        _patch_tier(monkeypatch, "studio")

        first = await async_client.post(
            "/assistant/message",
            json={
                "message": "why is this flagged?",
                "intent": "explain_finding",
                "finding": _FINDING,
                "rule_id": "LT003",
                "context_ref": "an-abc123",
            },
        )
        assert first.status_code == 200
        assert first.json()["continued"] is False
        conversation_id = first.json()["conversation_id"]

        # No intent, no finding, no rule_id — all of it must be inherited.
        second = await async_client.post(
            "/assistant/message",
            json={"message": "y por que?", "conversation_id": conversation_id},
        )
        assert second.status_code == 200
        data = second.json()
        assert data["intent"] == "explain_finding"
        assert data["continued"] is True
        assert data["reply"]["rule_id"] == "LT003"
        assert data["reply"]["context_ref"] == "an-abc123"

    @pytest.mark.anyio
    async def test_a_fresh_question_is_not_treated_as_a_continuation(
        self, async_client, monkeypatch
    ):
        _patch_tier(monkeypatch, "studio")
        first = await async_client.post(
            "/assistant/message",
            json={"message": "why is this flagged?",
                  "intent": "explain_finding", "finding": _FINDING},
        )
        conversation_id = first.json()["conversation_id"]

        second = await async_client.post(
            "/assistant/message",
            json={
                "message": "dame un resumen del ultimo scan",
                "conversation_id": conversation_id,
            },
        )
        assert second.json()["intent"] == "summarize_module"
        assert second.json()["continued"] is False


class TestMessageStream:
    @pytest.mark.anyio
    async def test_stream_emits_meta_chunks_and_done(
        self, async_client, monkeypatch
    ):
        _patch_tier(monkeypatch, "free")
        resp = await async_client.post(
            "/assistant/message/stream",
            json={
                "message": "why is this flagged?",
                "intent": "explain_finding",
                "finding": _FINDING,
            },
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")

        events = _parse_sse(resp.text)
        assert "meta" in events[0]
        assert events[0]["meta"]["intent"] == "explain_finding"
        assert events[-1]["done"] is True
        # Degraded (no model) still delivers the grounded text, not silence.
        assert "Texture over budget" in events[-1]["full_text"]
        assert events[-1]["turn_id"].startswith("at-")

    @pytest.mark.anyio
    async def test_tier_403_happens_before_the_stream_opens(
        self, async_client, monkeypatch
    ):
        _patch_tier(monkeypatch, "free")
        resp = await async_client.post(
            "/assistant/message/stream",
            json={"message": "what if I fix these?",
                  "intent": "simulate_change"},
        )
        # A real status code, not an error event buried in a 200 stream.
        assert resp.status_code == 403
        assert "simulate_change" in resp.json()["detail"]["error"]

    @pytest.mark.anyio
    async def test_unknown_conversation_404s_before_the_stream(
        self, async_client, monkeypatch
    ):
        _patch_tier(monkeypatch, "studio")
        resp = await async_client.post(
            "/assistant/message/stream",
            json={"message": "hola", "conversation_id": "ac-doesnotexist"},
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_non_narrating_intent_streams_one_chunk(
        self, async_client, monkeypatch
    ):
        _patch_tier(monkeypatch, "studio")
        resp = await async_client.post(
            "/assistant/message/stream",
            json={"message": "why CP006?", "intent": "why_rule"},
        )
        events = _parse_sse(resp.text)
        chunks = [e for e in events if "chunk" in e]
        # Table-driven answers are instant; faking a typing effect would be
        # theatre rather than feedback.
        assert len(chunks) == 1
        assert events[-1]["full_text"] == chunks[0]["chunk"]

    @pytest.mark.anyio
    async def test_streamed_turn_is_recorded_in_the_thread(
        self, async_client, monkeypatch
    ):
        _patch_tier(monkeypatch, "studio")
        resp = await async_client.post(
            "/assistant/message/stream",
            json={"message": "why is this flagged?",
                  "intent": "explain_finding", "finding": _FINDING},
        )
        conversation_id = _parse_sse(resp.text)[0]["meta"]["conversation_id"]

        thread = await async_client.get(
            f"/assistant/conversations/{conversation_id}"
        )
        roles = [t["role"] for t in thread.json()["turns"]]
        # Streaming must persist exactly like the blocking path, or a
        # follow-up after a streamed answer would have no history.
        assert roles == ["user", "assistant"]


class TestSummaryIsReadBack:
    @pytest.mark.anyio
    async def test_latest_summary_degrades_to_empty_without_mongo(self):
        from modules.assistant import memory_store

        assert await memory_store.latest_summary("ac-whatever") == ""
