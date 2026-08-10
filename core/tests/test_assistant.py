# core/tests/test_assistant.py
#
# M0 — conversation skeleton + per-intent tier gating.
# M1 — closed-menu intent router + explain_finding action.
#
# The assistant serves EVERY tier; what a tier cannot do is an intent-level
# 403, never a blanket 403 on the route. Mongo is absent in this test
# environment, so these also exercise the in-process fallback store, and
# the LLM is never loaded, so the router's keyword layer and the action's
# deterministic degradation are what run — exactly the free-image path.

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from modules.assistant.actions import explain_finding
from modules.assistant.intent_router import (
    INTENT_GRAMMAR,
    classify,
    classify_by_keywords,
)
from modules.assistant.tiers import (
    ALL_INTENTS,
    NON_ROUTABLE_INTENTS,
    ROUTABLE_INTENTS,
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


# ── M1: intent router ─────────────────────────────────────────────────────────


class TestIntentRouter:
    def test_grammar_covers_the_routable_menu_and_nothing_else(self):
        # The grammar is rebuilt from ROUTABLE_INTENTS at import — it must
        # name every routable intent exactly once and contain no other
        # terminal.
        for intent in ROUTABLE_INTENTS:
            assert f'"{intent}"' in INTENT_GRAMMAR
        terminals = INTENT_GRAMMAR.split("::=")[1].count('"') // 2
        assert terminals == len(ROUTABLE_INTENTS)

    def test_the_model_can_never_emit_confirm_pending(self):
        """A committing intent must not be reachable by classification.

        confirm_pending flips a proposed fact to confirmed / a draft rule to
        active. It is only correct when the previous turn actually left a
        proposal open — a fact about the thread, established in Python
        before the router runs. Give the model the token and it will
        eventually emit it on a message that was not an affirmation, and
        that turn would commit a stored decision nobody agreed to.
        """
        assert "confirm_pending" in ALL_INTENTS  # it IS a capability
        assert "confirm_pending" in NON_ROUTABLE_INTENTS
        assert "confirm_pending" not in ROUTABLE_INTENTS
        assert "confirm_pending" not in INTENT_GRAMMAR
        # …and the keyword layer must not reach it either.
        for message in ("sí", "yes", "confirmo", "confirm it", "ok"):
            assert classify_by_keywords(message) != "confirm_pending"

    def test_keyword_layer_routes_both_languages(self):
        cases = {
            "why is this flagged on my texture?": "explain_finding",
            "explica este warning": "explain_finding",
            "dame un resumen del scan": "summarize_module",
            "what if I fix these 5 issues?": "simulate_change",
            "qué pasaría si bajo las sombras": "simulate_change",
            "crea una regla: prohibido TCHAR_TO_ANSI": "define_rule",
            "recuerda que usamos Nanite en personajes": "remember_fact",
            "¿qué decidimos sobre los lightmaps?": "recall_fact",
            "why does this rule exist": "why_rule",
        }
        for message, expected in cases.items():
            assert classify_by_keywords(message) == expected, message

    def test_unmatched_text_defaults_to_help_never_guesses(self):
        assert classify_by_keywords("buenos días") == "general_help"
        assert classify_by_keywords("") == "general_help"

    def test_classify_without_llm_reports_keyword_source(self):
        # No model in this environment — the router must degrade, not raise.
        intent, source = classify("explica este issue")
        assert intent == "explain_finding"
        assert source == "keywords"

    def test_explicit_marker_beats_the_model(self, monkeypatch):
        """A named operation is not a topic the classifier gets to weigh in on.

        The regression: with a model loaded the keyword table never runs, so
        "nueva regla: …" reached the 1.5B, which answered summarize_module
        (the sentence does mention naming) — and the assistant replied with
        the previous naming scan instead of storing the rule. The user saw an
        answer they had already been given.
        """
        monkeypatch.setattr(
            "modules.assistant.intent_router._classify_by_llm",
            lambda _message: "summarize_module",
        )
        intent, source = classify(
            "nueva regla: convención de nombres, los widgets empiezan por SShint"
        )
        assert intent == "define_rule"
        assert source == "explicit"

    def test_explicit_marker_survives_the_module_correction(self, monkeypatch):
        # Module aliases include bare "naming" and "lod", which land inside a
        # rule's own subject. The explain_finding -> summarize_module
        # correction must not fire on a message that named an operation.
        monkeypatch.setattr(
            "modules.assistant.intent_router._classify_by_llm",
            lambda _message: "explain_finding",
        )
        intent, _ = classify("new rule: lod meshes must call Super::BeginPlay")
        assert intent == "define_rule"

    def test_module_questions_still_reach_the_model(self, monkeypatch):
        # The new layer must be narrow: an ordinary module question carries no
        # marker and stays on the classification path it always used.
        monkeypatch.setattr(
            "modules.assistant.intent_router._classify_by_llm",
            lambda _message: "summarize_module",
        )
        intent, source = classify("how is the code validator doing?")
        assert intent == "summarize_module"
        assert source == "llm"

    @pytest.mark.anyio
    async def test_free_text_message_is_routed(self, async_client, monkeypatch):
        _patch_tier(monkeypatch, "studio")
        resp = await async_client.post(
            "/assistant/message",
            json={"message": "dame un resumen del último scan"},
        )
        assert resp.status_code == 200
        assert resp.json()["intent"] == "summarize_module"


# ── M1: explain_finding action ────────────────────────────────────────────────

_FINDING = {
    "rule_id": "LT003",
    "rule_name": "Texture over budget",
    "rule_explanation": (
        "Texture resolution exceeds the slot budget for its LOD group."
    ),
    "message": "4096×4096 texture exceeds the 2048 px max-size budget.",
    "fix_suggestion": "Set max_texture_size to 2048.",
    "auto_fixable": True,
}


class TestExplainFinding:
    @pytest.mark.anyio
    async def test_inline_finding_degrades_to_grounded_text(self):
        # No LLM loaded -> deterministic reply built ONLY from rule-engine
        # fields; nothing invented.
        result = await explain_finding.run({"finding": dict(_FINDING)})
        assert result["resolved"] is True
        assert result["degraded"] is True
        assert "Texture over budget" in result["reply"]
        assert "2048" in result["reply"]
        assert "Auto-Fix" in result["reply"]

    @pytest.mark.anyio
    async def test_no_target_is_an_honest_ask_not_a_guess(self):
        result = await explain_finding.run({"message": "why?"})
        assert result["resolved"] is False
        assert "rule id" in result["reply"]

    @pytest.mark.anyio
    async def test_unresolvable_context_ref_is_honest(self):
        # Mongo is down in tests — the lookup must degrade to "not found".
        result = await explain_finding.run(
            {"context_ref": "an-000000000000", "rule_id": "LT003"}
        )
        assert result["resolved"] is False

    @pytest.mark.anyio
    async def test_end_to_end_explain_via_endpoint(
        self, async_client, monkeypatch
    ):
        _patch_tier(monkeypatch, "free")
        resp = await async_client.post(
            "/assistant/message",
            json={
                "message": "why is this flagged?",
                "intent": "explain_finding",
                "finding": _FINDING,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "explain_finding"
        assert "Texture over budget" in data["reply"]["raw_text"]


# ── M2: memory ────────────────────────────────────────────────────────────────


class TestMemory:
    @pytest.mark.anyio
    async def test_remember_proposes_and_never_self_confirms(self):
        from modules.assistant import memory_store
        from modules.assistant.actions import remember_fact

        result = await remember_fact.run(
            {
                "message": "recuerda que usamos Nanite en todos los personajes",
                "studio_id": "s1",
                "project_id": "p1",
            }
        )
        assert result["fact_status"] == "proposed"
        assert result["fact_id"]
        # The hard rule: a proposed fact is invisible to grounding.
        assert await memory_store.confirmed_facts("s1", "p1") == []

    @pytest.mark.anyio
    async def test_recall_only_sees_confirmed_facts(self):
        from modules.assistant import memory_store
        from modules.assistant.actions import recall_fact, remember_fact

        proposed = await remember_fact.run(
            {
                "message": "remember that all lightmaps bake at 512",
                "studio_id": "s2",
                "project_id": "p2",
            }
        )
        # Before confirmation: recall knows nothing.
        before = await recall_fact.run(
            {"message": "what did we decide about lightmaps?",
             "studio_id": "s2", "project_id": "p2"}
        )
        assert before["facts"] == []

        await memory_store.set_fact_status(proposed["fact_id"], "confirmed")

        after = await recall_fact.run(
            {"message": "what did we decide about lightmaps?",
             "studio_id": "s2", "project_id": "p2"}
        )
        assert proposed["fact_id"] in after["facts"]
        assert "512" in after["reply"]

    @pytest.mark.anyio
    async def test_retracted_fact_stays_forgotten(self):
        from modules.assistant import memory_store
        from modules.assistant.actions import recall_fact, remember_fact

        proposed = await remember_fact.run(
            {"message": "remember that shadows are medium on Switch",
             "studio_id": "s3", "project_id": "p3"}
        )
        await memory_store.set_fact_status(proposed["fact_id"], "confirmed")
        await memory_store.set_fact_status(proposed["fact_id"], "retracted")

        result = await recall_fact.run(
            {"message": "shadows on Switch?", "studio_id": "s3",
             "project_id": "p3"}
        )
        assert result["facts"] == []

    @pytest.mark.anyio
    async def test_muted_project_refuses_to_remember(self):
        from modules.assistant import memory_store
        from modules.assistant.actions import remember_fact

        await memory_store.set_memory_muted("s4", "p4", True)
        result = await remember_fact.run(
            {"message": "remember that this is secret",
             "studio_id": "s4", "project_id": "p4"}
        )
        assert result["fact_id"] == ""
        assert "muted" in result["reply"]

    @pytest.mark.anyio
    async def test_purge_project_removes_everything(self):
        from modules.assistant import memory_store
        from modules.assistant.actions import remember_fact

        proposed = await remember_fact.run(
            {"message": "remember that the NDA build ships in june",
             "studio_id": "s5", "project_id": "p5"}
        )
        await memory_store.set_fact_status(proposed["fact_id"], "confirmed")
        removed = await memory_store.purge_project("s5", "p5")
        assert removed >= 1
        assert await memory_store.list_facts("s5", "p5") == []

    @pytest.mark.anyio
    async def test_memory_endpoints_are_studio_gated(
        self, async_client, monkeypatch
    ):
        _patch_tier(monkeypatch, "indie")
        resp = await async_client.get(
            "/assistant/memory", params={"studio_id": "s1"}
        )
        assert resp.status_code == 403

        _patch_tier(monkeypatch, "studio")
        resp = await async_client.get(
            "/assistant/memory", params={"studio_id": "s1"}
        )
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_confirm_endpoint_round_trip(
        self, async_client, monkeypatch
    ):
        from modules.assistant.actions import remember_fact

        _patch_tier(monkeypatch, "studio")
        proposed = await remember_fact.run(
            {"message": "remember that props use 1k textures",
             "studio_id": "s6", "project_id": "p6"}
        )
        resp = await async_client.post(
            "/assistant/memory/confirm",
            json={"fact_id": proposed["fact_id"], "accept": True},
        )
        assert resp.status_code == 200
        assert resp.json()["fact"]["status"] == "confirmed"

    def test_extractor_strips_preamble_verbatim(self):
        from modules.assistant.fact_extractor import (
            classify_fact_type,
            extract_statement,
        )

        assert extract_statement(
            "recuerda que usamos Nanite en personajes"
        ) == "usamos Nanite en personajes"
        assert extract_statement(
            "Remember that props use 1k textures"
        ) == "props use 1k textures"
        # Nothing paraphrased — the user's own words are the value.
        assert classify_fact_type("hemos decidido usar Lumen") == "decision"
        assert classify_fact_type("preferimos BC7 para albedo") == "preference"


# ── Confirming a proposal in the conversation ─────────────────────────────────
#
# The reported bug: "when I confirm a fact so the memory persists, it answers
# with an already-processed summary of the last scans."
#
# Cause: no intent meant "yes". A bare "sí" was not a continuation (the opener
# list had "ok" and "vale" but never "sí"), so it reached the classifier, whose
# grammar forces one of the routable intents — and whichever came back
# inherited the previous turn's context_ref and answered about the analysis.


class TestAffirmationLexicon:
    def test_bare_yes_and_no_in_both_languages(self):
        from modules.assistant.pending import read_affirmation

        for yes in ("sí", "si", "Sí.", "vale", "confirmo", "confírmalo",
                    "yes", "  YES  ", "confirm it", "go ahead", "hazlo"):
            assert read_affirmation(yes) == "accept", yes
        for no in ("no", "No.", "nope", "cancela", "olvídalo", "déjalo",
                   "discard", "never mind"):
            assert read_affirmation(no) == "reject", no

    def test_an_answer_carrying_new_content_is_not_a_bare_yes(self):
        """"sí, pero solo para Unity" is not the proposal that was made.

        Confirming it would store something the user did not agree to. It
        must fall through to normal routing and be answered on its merits.
        """
        from modules.assistant.pending import read_affirmation

        assert read_affirmation("sí, pero solo para Unity") is None
        assert read_affirmation("yes but only for the mobile profile") is None
        assert read_affirmation("no me convence el resumen del scan") is None
        assert read_affirmation("") is None

    def test_substrings_never_fire(self):
        """"si arreglo esto" opens with "si" and is a simulate_change."""
        from modules.assistant.pending import read_affirmation

        assert read_affirmation("si arreglo esto que pasa") is None
        assert read_affirmation("no LOD chain on this mesh") is None


class TestPendingConfirmation:
    @staticmethod
    def _conv(turns):
        return {"turns": turns}

    def test_only_the_newest_assistant_turn_arms_the_question(self):
        """A proposal from ten turns ago is not what "sí" means now."""
        from modules.assistant.pending import pending_proposal

        stale = self._conv([
            {"role": "assistant", "proposed_fact_id": "f-old"},
            {"role": "user", "raw_text": "otra cosa"},
            {"role": "assistant", "raw_text": "un resumen", "intent": "x"},
        ])
        assert pending_proposal(stale) is None

        fresh = self._conv([
            {"role": "assistant", "proposed_fact_id": "f-old"},
            {"role": "user", "raw_text": "recuerda que X"},
            {"role": "assistant", "proposed_fact_id": "f-new",
             "proposed_subject": "X"},
        ])
        assert pending_proposal(fresh) == {
            "kind": "fact", "id": "f-new", "subject": "X",
        }

    @pytest.mark.anyio
    async def test_yes_confirms_the_fact_and_quotes_it(
        self, async_client, monkeypatch
    ):
        from modules.assistant import memory_store

        _patch_tier(monkeypatch, "studio")
        first = await async_client.post(
            "/assistant/message",
            json={
                "message": "recuerda que usamos Nanite en todos los personajes",
                "studio_id": "sc1", "project_id": "pc1",
            },
        )
        body = first.json()
        conv_id = body["conversation_id"]
        assert body["intent"] == "remember_fact"
        # The id must now leave the Core — without it no client can offer a
        # confirm button, which is what made the promised card impossible.
        assert body["pending_fact_id"]
        assert await memory_store.confirmed_facts("sc1", "pc1") == []

        second = await async_client.post(
            "/assistant/message",
            json={"message": "sí", "conversation_id": conv_id,
                  "studio_id": "sc1", "project_id": "pc1"},
        )
        data = second.json()
        assert data["intent"] == "confirm_pending"
        # The reply must show WHAT was stored, not a fixed acknowledgement.
        assert "Nanite" in data["reply"]["raw_text"]
        assert len(await memory_store.confirmed_facts("sc1", "pc1")) == 1
        # …and the question is disarmed, so a later "sí" cannot re-commit it.
        assert not data["pending_fact_id"]

    @pytest.mark.anyio
    async def test_no_retracts_and_the_fact_stays_forgotten(
        self, async_client, monkeypatch
    ):
        from modules.assistant import memory_store

        _patch_tier(monkeypatch, "studio")
        first = await async_client.post(
            "/assistant/message",
            json={"message": "recuerda que los props usan texturas de 1k",
                  "studio_id": "sc2", "project_id": "pc2"},
        )
        conv_id = first.json()["conversation_id"]

        second = await async_client.post(
            "/assistant/message",
            json={"message": "no", "conversation_id": conv_id,
                  "studio_id": "sc2", "project_id": "pc2"},
        )
        assert second.json()["intent"] == "confirm_pending"
        assert await memory_store.confirmed_facts("sc2", "pc2") == []

    @pytest.mark.anyio
    async def test_yes_activates_a_draft_rule(self, async_client, monkeypatch):
        from modules.assistant import rule_store

        _patch_tier(monkeypatch, "studio")
        first = await async_client.post(
            "/assistant/message",
            json={"message": "nueva regla: prohibido TCHAR_TO_ANSI en headers",
                  "studio_id": "sc3", "project_id": "pc3"},
        )
        body = first.json()
        assert body["intent"] == "define_rule"
        assert body["pending_rule_id"]
        assert await rule_store.active_rules("sc3", "pc3") == []

        second = await async_client.post(
            "/assistant/message",
            json={"message": "confírmalo", "conversation_id":
                  body["conversation_id"],
                  "studio_id": "sc3", "project_id": "pc3"},
        )
        assert second.json()["intent"] == "confirm_pending"
        assert len(await rule_store.active_rules("sc3", "pc3")) == 1

    @pytest.mark.anyio
    async def test_confirming_never_answers_about_the_last_scan(
        self, async_client, monkeypatch
    ):
        """The reported bug, end to end, on the production path.

        A scan is in view (context_ref set — the panel always sends it) and
        the model is loaded, which is what makes the bug visible: without a
        model "sí" fell to the keyword table and got the help text, but in
        production it reached the 1.5B, came back summarize_module, and
        inherited the context_ref to answer about the analysis.

        The classifier is pinned to summarize_module here to reproduce that
        exactly. The shortcut must win before it is ever consulted — if this
        test ever sees summarize_module again, the ordering in _plan_turn
        has regressed.
        """
        _patch_tier(monkeypatch, "studio")
        monkeypatch.setattr(
            "modules.assistant.intent_router._classify_by_llm",
            lambda _message: "summarize_module",
        )
        first = await async_client.post(
            "/assistant/message",
            json={"message": "recuerda que Lumen va desactivado en Switch",
                  "context_ref": "an-42", "module_context": "code_validator",
                  "studio_id": "sc4", "project_id": "pc4"},
        )
        conv_id = first.json()["conversation_id"]

        second = await async_client.post(
            "/assistant/message",
            json={"message": "sí", "conversation_id": conv_id,
                  "context_ref": "an-42", "module_context": "code_validator",
                  "studio_id": "sc4", "project_id": "pc4"},
        )
        data = second.json()
        assert data["intent"] == "confirm_pending"
        assert data["intent"] != "summarize_module"
        reply = data["reply"]["raw_text"].lower()
        assert "lumen" in reply
        for scan_word in ("finding", "hallazgo", "scan has", "severity"):
            assert scan_word not in reply

    @pytest.mark.anyio
    async def test_yes_with_nothing_pending_routes_normally(
        self, async_client, monkeypatch
    ):
        _patch_tier(monkeypatch, "studio")
        resp = await async_client.post(
            "/assistant/message", json={"message": "sí"}
        )
        assert resp.status_code == 200
        assert resp.json()["intent"] != "confirm_pending"

    @pytest.mark.anyio
    async def test_the_proposal_survives_reopening_the_thread(
        self, async_client, monkeypatch
    ):
        """The pending id lives on the turn, not in process state."""
        _patch_tier(monkeypatch, "studio")
        first = await async_client.post(
            "/assistant/message",
            json={"message": "recuerda que el equipo usa PascalCase",
                  "studio_id": "sc5", "project_id": "pc5"},
        )
        conv_id = first.json()["conversation_id"]

        history = await async_client.get(f"/assistant/conversations/{conv_id}")
        turns = history.json()["turns"]
        assert turns[-1]["proposed_fact_id"]
        assert turns[-1]["proposed_subject"] == "el equipo usa PascalCase"


# ── M3: studio rules ──────────────────────────────────────────────────────────


class TestRuleCompiler:
    def test_forbidden_api_compiles_to_template(self):
        from modules.assistant.rule_compiler import compile_rule

        compiled = compile_rule("never use TCHAR_TO_ANSI in headers")
        assert compiled["tier"] == "template"
        assert compiled["template"]["template_id"] == "forbidden_api"
        assert compiled["template"]["params"]["api"] == "TCHAR_TO_ANSI"
        assert ".h" in compiled["template"]["params"]["scope_suffixes"]

    def test_spanish_prohibition_compiles(self):
        from modules.assistant.rule_compiler import compile_rule

        compiled = compile_rule("prohibido GetAllActorsOfClass en el proyecto")
        assert compiled["tier"] == "template"
        assert compiled["template"]["params"]["api"] == "GetAllActorsOfClass"

    def test_ambiguous_prose_falls_to_llm_tier_never_guesses(self):
        from modules.assistant.rule_compiler import compile_rule

        compiled = compile_rule(
            "components should be initialized before use where sensible"
        )
        assert compiled["tier"] == "llm_evaluated"

    def test_prose_never_is_not_an_api(self):
        from modules.assistant.rule_compiler import compile_rule

        # "never use more than 4 samplers" — "more" must not become an API.
        compiled = compile_rule("never use more than 4 samplers per material")
        assert compiled["tier"] == "llm_evaluated"

    def test_naming_prefix_compiles_to_its_own_template(self):
        # naming_pattern shipped with rule_templates from the start but
        # nothing here produced it, so the commonest studio rule of all — a
        # naming convention — could never reach its deterministic template.
        from modules.assistant.rule_compiler import compile_rule

        compiled = compile_rule("all widgets start with SShint")
        assert compiled["tier"] == "template"
        assert compiled["template"]["template_id"] == "naming_pattern"
        assert compiled["template"]["params"]["pattern"] == r"SShint.*"

    def test_spanish_naming_prefix_scopes_to_the_named_extension(self):
        from modules.assistant.rule_compiler import compile_rule

        compiled = compile_rule("las texturas .uasset empiezan por T_")
        params = compiled["template"]["params"]
        assert params["pattern"] == r"T_.*"
        assert params["file_glob_suffix"] == ".uasset"

    def test_naming_suffix_anchors_at_the_end(self):
        from modules.assistant.rule_compiler import compile_rule

        compiled = compile_rule("los materiales terminan con _Inst")
        assert compiled["template"]["params"]["pattern"] == r".*_Inst"

    def test_required_call_compiles_to_required_text(self):
        from modules.assistant.rule_compiler import compile_rule

        compiled = compile_rule(
            "every Actor must call Super::BeginPlay in .cpp"
        )
        assert compiled["template"]["template_id"] == "required_text"
        assert compiled["template"]["params"]["required"] == "Super::BeginPlay"
        assert compiled["template"]["params"]["scope_suffixes"] == [".cpp"]

    def test_a_budget_is_not_a_required_token(self):
        from modules.assistant.rule_compiler import compile_rule

        # "must have more than 3 LODs" is a budget; "more" must not be stored
        # as the token every file has to contain.
        compiled = compile_rule("meshes must have more than 3 LODs")
        assert compiled["tier"] == "llm_evaluated"

    def test_compiled_patterns_are_escaped_so_a_rule_cannot_break_a_scan(self):
        import re

        from modules.assistant.rule_compiler import compile_rule

        compiled = compile_rule("all files start with A_")
        # Whatever we build must be a valid regex — rule_templates swallows
        # re.error, so an unescaped pattern would silently match nothing.
        re.compile(compiled["template"]["params"]["pattern"])


class TestTemplateEvaluation:
    def test_forbidden_api_flags_with_line_numbers(self):
        from modules.assistant.rule_templates import evaluate_template_rule

        rule = {
            "name": "No TCHAR_TO_ANSI in headers",
            "template": {
                "template_id": "forbidden_api",
                "params": {"api": "TCHAR_TO_ANSI", "scope_suffixes": [".h"]},
            },
        }
        files = [
            ("Source/Foo.h", "int x;\nauto s = TCHAR_TO_ANSI(*Name);\n"),
            ("Source/Foo.cpp", "auto s = TCHAR_TO_ANSI(*Name);\n"),  # out of scope
        ]
        violations = evaluate_template_rule(rule, files)
        assert len(violations) == 1
        assert violations[0]["file"] == "Source/Foo.h"
        assert violations[0]["line"] == 2
        assert violations[0]["source"] == "studio_rule"

    def test_file_location_template(self):
        from modules.assistant.rule_templates import evaluate_template_rule

        rule = {
            "name": "Tests under Source/Tests",
            "template": {
                "template_id": "file_location",
                "params": {
                    "file_glob_suffix": "Test.cpp",
                    "required_dir": "Source/Tests",
                },
            },
        }
        violations = evaluate_template_rule(
            rule,
            [
                ("Source/Tests/FooTest.cpp", ""),
                ("Source/Misc/BarTest.cpp", ""),
            ],
        )
        assert [v["file"] for v in violations] == ["Source/Misc/BarTest.cpp"]

    def test_broken_rule_never_breaks_the_scan(self):
        from modules.assistant.rule_templates import evaluate_template_rule

        assert evaluate_template_rule({"template": {}}, [("a.h", "x")]) == []
        assert evaluate_template_rule(
            {"template": {"template_id": "naming_pattern",
                          "params": {"pattern": "([unclosed"}}},
            [("a.h", "x")],
        ) == []


class TestRuleLifecycle:
    @pytest.mark.anyio
    async def test_define_rule_creates_a_draft_that_does_not_run(self):
        from modules.assistant import rule_store
        from modules.assistant.actions import define_rule

        result = await define_rule.run(
            {
                "message": "never use TCHAR_TO_ANSI in headers",
                "studio_id": "rs1",
                "project_id": "rp1",
                "engine": "unreal",
            }
        )
        assert result["rule_tier"] == "template"
        assert result["rule_status"] == "draft"
        # A draft is invisible to scans until activated + confirmed.
        assert await rule_store.active_rules("rs1", "rp1", "unreal") == []

    @pytest.mark.anyio
    async def test_two_different_rules_get_two_different_replies(self):
        """The reply must show WHICH rule was understood.

        The Tier B branch used to be a constant string, so every rule that
        missed a template produced a byte-identical answer: defining a second
        rule was indistinguishable from the assistant repeating itself.
        Nothing caught it because these tests only ever asserted on tier and
        status, never on the text the user actually reads.
        """
        from modules.assistant.actions import define_rule

        first = await define_rule.run(
            {"message": "cinematics should be reviewed for pacing",
             "studio_id": "rs3", "project_id": "rp3", "engine": "unreal"}
        )
        second = await define_rule.run(
            {"message": "audio cues need a designer sign-off",
             "studio_id": "rs3", "project_id": "rp3", "engine": "unreal"}
        )
        assert first["rule_tier"] == second["rule_tier"] == "llm_evaluated"
        assert first["reply"] != second["reply"]
        assert "cinematics" in first["reply"]
        assert "audio cues" in second["reply"]

    @pytest.mark.anyio
    async def test_activated_rule_runs_in_the_project_scan(
        self, async_client, monkeypatch
    ):
        from modules.assistant import rule_store
        from modules.assistant.actions import define_rule

        _patch_tier(monkeypatch, "studio")
        created = await define_rule.run(
            {"message": "never use TCHAR_TO_ANSI in headers",
             "studio_id": "rs2", "project_id": "rp2", "engine": "unreal"}
        )
        await rule_store.set_rule_status(
            created["rule_id"], status="active", confirmed=True
        )

        monkeypatch.setattr(
            "api.routes.validate.resolve_tier",
            AsyncMock(return_value="studio"),
        )
        resp = await async_client.post(
            "/validate/project",
            json={
                "studio_id": "rs2",
                "project_id": "rp2",
                "engine": "unreal",
                "files": [
                    {"name": "Foo.h", "path": "Source/Foo.h", "type": "h",
                     "content": "auto s = TCHAR_TO_ANSI(*Name);\n"},
                ],
            },
        )
        assert resp.status_code == 200
        studio_findings = [
            i for i in resp.json()["issues"] if i.get("source") == "studio_rule"
        ]
        assert len(studio_findings) == 1
        assert "TCHAR_TO_ANSI" in studio_findings[0]["message"]

    @pytest.mark.anyio
    async def test_scan_without_studio_id_runs_no_studio_rules(
        self, async_client, monkeypatch
    ):
        monkeypatch.setattr(
            "api.routes.validate.resolve_tier",
            AsyncMock(return_value="studio"),
        )
        resp = await async_client.post(
            "/validate/project",
            json={
                "project_id": "rp3",
                "engine": "unreal",
                "files": [
                    {"name": "Foo.h", "path": "Source/Foo.h", "type": "h",
                     "content": "auto s = TCHAR_TO_ANSI(*Name);\n"},
                ],
            },
        )
        assert resp.status_code == 200
        assert [
            i for i in resp.json()["issues"] if i.get("source") == "studio_rule"
        ] == []

    @pytest.mark.anyio
    async def test_llm_rule_cache_round_trip(self):
        from modules.assistant import rule_store

        key = rule_store.eval_cache_key("sr-x", 1, "file content")
        assert await rule_store.get_cached_eval(key) is None
        await rule_store.save_cached_eval(key, [{"message": "v"}])
        assert await rule_store.get_cached_eval(key) == [{"message": "v"}]
        # A different version is a different key — edits re-evaluate.
        assert rule_store.eval_cache_key("sr-x", 2, "file content") != key

    @pytest.mark.anyio
    async def test_rules_endpoints_gated_by_capability(
        self, async_client, monkeypatch
    ):
        _patch_tier(monkeypatch, "free")
        resp = await async_client.get("/assistant/rules")
        assert resp.status_code == 403

        _patch_tier(monkeypatch, "indie")
        resp = await async_client.get("/assistant/rules")
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_indie_cannot_activate_a_template_rule(
        self, async_client, monkeypatch
    ):
        from modules.assistant.actions import define_rule

        created = await define_rule.run(
            {"message": "never use GetAllActorsOfClass in the project",
             "studio_id": "rs4", "project_id": "rp4", "engine": "unreal"}
        )
        _patch_tier(monkeypatch, "indie")
        resp = await async_client.post(
            "/assistant/rules/confirm",
            json={"rule_id": created["rule_id"], "accept": True},
        )
        assert resp.status_code == 403


# ── M4: model profiles + golden set ───────────────────────────────────────────


class TestModelProfiles:
    def test_light_always_resolves(self):
        from modules.assistant.model_profile import resolve_profile

        assert resolve_profile("light") == ("light", "")
        assert resolve_profile("") == ("light", "")
        assert resolve_profile("nonsense") == ("light", "")

    def test_advanced_without_the_model_downgrades_with_reason(self):
        # The 7B gguf is not installed in this environment.
        from modules.assistant.model_profile import resolve_profile

        profile, reason = resolve_profile("advanced")
        assert profile == "light"
        assert reason == "advanced_model_not_installed"

    def test_env_can_force_a_profile(self, monkeypatch):
        from modules.assistant.model_profile import resolve_profile

        monkeypatch.setenv("SHINTTOOLS_ASSISTANT_PROFILE", "light")
        # Even a Studio entitlement serves light when forced.
        assert resolve_profile("advanced") == ("light", "")

    def test_profiles_share_the_model_family(self):
        # Same tokenizer/family so prompts + LoRA carry over — a profile
        # swap must never mean a prompt-format migration.
        from modules.assistant.model_profile import PROFILES

        for config in PROFILES.values():
            assert "Qwen2.5-Coder" in config["model_file"]


class TestGoldenSet:
    @staticmethod
    def _pairs():
        import yaml
        from pathlib import Path

        golden = (
            Path(__file__).resolve().parent.parent
            / "modules" / "assistant" / "eval" / "golden_intents.yaml"
        )
        return yaml.safe_load(golden.read_text(encoding="utf-8"))["pairs"]

    def test_every_golden_intent_is_on_the_menu(self):
        # Anti-drift: the golden set cannot reference intents that don't
        # exist — same contract as rule_costs.yaml vs the rule catalog.
        pairs = self._pairs()
        assert len(pairs) >= 50
        for pair in pairs:
            assert pair["intent"] in ALL_INTENTS, pair

    def test_every_routable_intent_has_golden_coverage(self):
        # ROUTABLE_INTENTS, not ALL_INTENTS: the golden set measures the
        # ROUTER, and confirm_pending is deliberately unreachable from it —
        # a golden pair for it would assert exactly the behaviour that must
        # never happen. Its own coverage is TestPendingConfirmation.
        covered = {pair["intent"] for pair in self._pairs()}
        assert covered == set(ROUTABLE_INTENTS)

    def test_module_directed_questions_route_and_resolve(self):
        """Entries carrying a `module` must reach the right module.

        Two claims, both of which failed before: the keyword layer knew no
        module name at all (so these fell through to general_help), and the
        resolver did not exist (so the module was never consulted).
        """
        from modules.assistant.module_resolver import resolve_module

        directed = [p for p in self._pairs() if p.get("module")]
        assert directed, "the golden set must cover module-directed questions"
        for pair in directed:
            assert classify_by_keywords(pair["message"]) == pair["intent"], pair
            module, source = resolve_module(pair["message"])
            assert module is not None, pair
            assert module.id == pair["module"], pair
            assert source == "message"

    def test_keyword_layer_never_leaves_the_menu_and_help_is_clean(self):
        # The keyword layer's hard guarantees (accuracy belongs to the
        # harness, not CI): always on-menu, and pure greetings never
        # misroute into an action.
        for pair in self._pairs():
            got = classify_by_keywords(pair["message"])
            assert got in ALL_INTENTS
            if pair["intent"] == "general_help":
                assert got == "general_help", pair["message"]


# ── M6: why_rule, simulator, decision monitor ────────────────────────────────


class TestWhyRule:
    @pytest.mark.anyio
    async def test_cites_the_real_cost_engine(self):
        from modules.assistant.actions import why_rule

        result = await why_rule.run({"message": "why CP001?"})
        assert result["rule_id"] == "CP001"
        # The differentiator: real bands + calibration, not generic advice.
        assert result["cost"]["dimensions"]
        assert result["cost"]["calibration_version"]
        assert "calibration" in result["reply"]

    @pytest.mark.anyio
    async def test_picks_the_rule_up_from_the_selected_finding(self):
        from modules.assistant.actions import why_rule

        result = await why_rule.run({"message": "why does this rule exist?",
                                     "finding": {"rule_id": "CP001"}})
        assert result["rule_id"] == "CP001"

    @pytest.mark.anyio
    async def test_uncosted_rule_says_so_instead_of_inventing(self):
        from modules.assistant.actions import why_rule

        # A real catalog rule with no rule_costs entry.
        result = await why_rule.run({"rule_id": "LT003"})
        assert result["rule_name"]
        assert not result["cost"]
        assert "no calibrated cost" in result["reply"]

    @pytest.mark.anyio
    async def test_unknown_rule_is_refused_not_improvised(self):
        from modules.assistant.actions import why_rule

        result = await why_rule.run({"rule_id": "ZZ999"})
        assert "don't have ZZ999" in result["reply"]

    @pytest.mark.anyio
    async def test_no_rule_asks_instead_of_guessing(self):
        from modules.assistant.actions import why_rule

        result = await why_rule.run({"message": "why?"})
        assert result["rule_id"] == ""
        assert "Which rule" in result["reply"]


class TestSimulateChange:
    @pytest.mark.anyio
    async def test_without_a_report_it_refuses_to_estimate(self):
        from modules.assistant.actions import simulate_change

        result = await simulate_change.run({"message": "what if I fix these?"})
        assert result["simulated"] is False
        assert "Predictive Profiler" in result["reply"]

    @pytest.mark.anyio
    async def test_without_a_selection_it_asks_for_one(self):
        from modules.assistant.actions import simulate_change

        result = await simulate_change.run({"report_id": "pr-abc"})
        assert result["simulated"] is False
        assert "Pick the issues" in result["reply"]

    @pytest.mark.anyio
    async def test_expired_report_is_honest(self):
        from modules.assistant.actions import simulate_change

        result = await simulate_change.run(
            {"report_id": "pr-gone", "selected_item_ids": ["i1"]}
        )
        assert result["simulated"] is False


class TestDecisionMonitor:
    _FACT = {
        "fact_id": "af-1",
        "value": "all character meshes use Nanite",
    }

    def test_flags_a_finding_that_contradicts_a_decision(self):
        from modules.assistant.decision_monitor import find_contradictions

        findings = [
            {
                "rule_id": "LD012",
                "rule_name": "Nanite candidate",
                "asset_path": "/Game/Characters/SM_Hero",
                "message": "High-poly character meshes should enable Nanite.",
            }
        ]
        pairs = find_contradictions([self._FACT], findings)
        assert len(pairs) == 1
        assert pairs[0]["fact_id"] == "af-1"
        assert len(pairs[0]["shared_terms"]) >= 2

    def test_unrelated_finding_is_not_paired(self):
        from modules.assistant.decision_monitor import find_contradictions

        findings = [
            {
                "rule_id": "LT003",
                "rule_name": "Texture over budget",
                "asset_path": "/Game/Props/T_Barrel",
                "message": "4096 texture exceeds the 2048 budget.",
            }
        ]
        assert find_contradictions([self._FACT], findings) == []

    def test_a_vague_fact_never_pairs(self):
        from modules.assistant.decision_monitor import find_contradictions

        vague = {"fact_id": "af-2", "value": "we use it"}
        findings = [{"rule_id": "LT003", "message": "texture too big"}]
        assert find_contradictions([vague], findings) == []

    @pytest.mark.anyio
    async def test_proposed_facts_never_produce_a_nudge(self):
        from modules.assistant import decision_monitor
        from modules.assistant.actions import remember_fact

        await remember_fact.run(
            {"message": "remember that all character meshes use Nanite",
             "studio_id": "dm1", "project_id": "dp1"}
        )
        findings = [
            {"rule_id": "LD012", "rule_name": "Nanite candidate",
             "asset_path": "/Game/Characters/SM_Hero",
             "message": "High-poly character meshes should enable Nanite."}
        ]
        # Unconfirmed -> silent, by contract.
        assert await decision_monitor.check_scan("dm1", "dp1", findings) == []

    @pytest.mark.anyio
    async def test_confirmed_fact_produces_a_rendered_nudge(self):
        from modules.assistant import decision_monitor, memory_store
        from modules.assistant.actions import remember_fact

        proposed = await remember_fact.run(
            {"message": "remember that all character meshes use Nanite",
             "studio_id": "dm2", "project_id": "dp2"}
        )
        await memory_store.set_fact_status(proposed["fact_id"], "confirmed")

        findings = [
            {"rule_id": "LD012", "rule_name": "Nanite candidate",
             "asset_path": "/Game/Characters/SM_Hero",
             "message": "High-poly character meshes should enable Nanite."}
        ]
        pairs = await decision_monitor.check_scan("dm2", "dp2", findings)
        assert len(pairs) == 1
        assert "SM_Hero" in pairs[0]["nudge"]
        assert "Nanite" in pairs[0]["nudge"]


class TestSummarizeModule:
    @pytest.mark.anyio
    async def test_with_no_module_and_no_scan_it_asks_which_module(self):
        from modules.assistant.actions import summarize_module

        result = await summarize_module.run({})
        assert result["resolved"] is False
        # Nothing to work from at all: name the modules rather than issue an
        # instruction the user did not ask for.
        assert "Which module" in result["reply"]

    @pytest.mark.anyio
    async def test_named_module_without_a_scan_describes_the_module(self):
        """The old reply here was "run a scan first" — a dead end.

        A module's coverage and rule count are real information available
        with no scan at all, and answering the question beats instructing the
        user to go do something before they may ask it.
        """
        from modules.assistant.actions import summarize_module

        result = await summarize_module.run(
            {"message": "how is the code validator doing?"}
        )
        assert result["module"] == "code_validator"
        assert "checks" in result["reply"]


class TestModuleResolution:
    """The defect behind "I ask about a rule and it answers with a mesh"."""

    def test_a_named_module_outranks_the_open_panel(self):
        from modules.assistant.module_resolver import resolve_module

        module, source = resolve_module(
            "how is the code validator doing?", module_context="lod_audit"
        )
        assert module is not None and module.id == "code_validator"
        assert source == "message"

    def test_the_open_panel_is_used_when_no_module_is_named(self):
        from modules.assistant.module_resolver import resolve_module

        module, source = resolve_module("summarize this", module_context="lod_audit")
        assert module is not None and module.id == "lod_audit"
        assert source == "context"

    def test_longer_aliases_win(self):
        """"lod auditor" must not be swallowed by the bare "lod" alias."""
        from modules.assistant.module_resolver import resolve_module

        module, _ = resolve_module("what did the lod auditor find?")
        assert module is not None and module.id == "lod_audit"

    def test_module_question_overrides_an_llm_explain_finding(self, monkeypatch):
        """The model's answer is corrected when Python can decide better.

        Reported from a real session: "share the results view of code
        validator" was classified explain_finding by the loaded model, and the
        action then asked which of 360 findings was meant — to a question that
        named no finding. Module awareness lived only in the keyword layer,
        which never runs while a model is available.
        """
        from modules.assistant import intent_router

        monkeypatch.setattr(
            intent_router, "_classify_by_llm", lambda _m: "explain_finding"
        )

        intent, source = intent_router.classify(
            "share the results view of code validator"
        )
        assert intent == "summarize_module"
        assert source == "llm+module"

        # Naming a rule IS a finding question — the override must not fire.
        intent, source = intent_router.classify("why LT003 on the lod auditor?")
        assert intent == "explain_finding"
        assert source == "llm"

        # No module named — nothing to correct with.
        intent, source = intent_router.classify("why is this flagged?")
        assert intent == "explain_finding"
        assert source == "llm"

    def test_naming_a_module_is_not_a_continuation(self):
        """A short "y el code validator?" changes subject, it does not follow on.

        Inheriting the previous turn's grounding here is what made the
        assistant keep answering about the old module after the user moved on.
        """
        from modules.assistant.conversation_context import is_continuation

        assert is_continuation("y por que?") is True
        assert is_continuation("y el code validator?") is False

    def test_naming_an_operation_is_not_a_continuation(self):
        """"y recuerda que…" states something new; it does not follow on.

        Continuation runs BEFORE classification and inherits the previous
        turn's intent wholesale, so a rule phrased as a follow-up was
        answered as whatever the last turn was — the same "it repeated its
        previous answer" symptom, reached by a different route.
        """
        from modules.assistant.conversation_context import is_continuation

        assert is_continuation("y recuerda que usamos PascalCase") is False
        assert is_continuation("y nueva regla: prefijo T_") is False

    def test_fix_logs_are_not_scan_results(self):
        """code_validator_fixes records an Auto-Fix run, not findings.

        Matching module report types by prefix would pick it up and report
        its entries as findings — true-looking and wrong.
        """
        from modules.assistant import module_registry

        assert module_registry.for_report_type("code_validator_fixes") is None
        assert (
            module_registry.for_report_type("code_validator_project").id
            == "code_validator"
        )


class TestExplainFindingNeverGuesses:
    @pytest.mark.anyio
    async def test_ambiguous_analysis_asks_instead_of_picking_the_first_row(self):
        """The regression this whole change exists for.

        Unselected, the old code returned issues[0] — the first row of
        whatever analysis was ambient — and presented it as the answer.
        """
        doc = {
            "analysis_id": "an-x",
            "report_type": "lod_audit",
            "issues": [
                {"rule_id": "LT003", "rule_name": "Texture size", "asset_path": "/A"},
                {"rule_id": "LT003", "rule_name": "Texture size", "asset_path": "/B"},
                {"rule_id": "LD004", "rule_name": "LOD count", "asset_path": "/C"},
            ],
        }

        finding, error = await _resolve_against(doc, rule_id="", asset_path="")
        assert finding is None
        assert "guessing" in error
        assert "LT003" in error  # the most frequent candidate is named

    @pytest.mark.anyio
    async def test_naming_a_module_with_no_finding_answers_about_the_module(self):
        """"Show me the code validator results" is not a finding question.

        The router calls it explain_finding often enough, and asking which of
        360 findings was meant is honest but useless — the user named the
        module.
        """
        from modules.assistant.actions import explain_finding

        result = await explain_finding.run(
            {"message": "share the results view of code validator"}
        )
        assert result.get("module") == "code_validator"
        assert "which one" not in result["reply"].lower()

    def test_an_explain_click_still_goes_to_the_finding(self):
        """A selector must never be redirected to the module summary."""
        from modules.assistant.actions.explain_finding import (
            _is_module_level_question,
        )

        assert _is_module_level_question(
            {"message": "how is the code validator?"}
        ) is True
        assert _is_module_level_question(
            {"message": "how is the code validator?", "rule_id": "CS001"}
        ) is False
        assert _is_module_level_question(
            {"message": "why is this flagged?", "module_context": "code_validator"}
        ) is False

    @pytest.mark.anyio
    async def test_a_selector_resolves_normally(self):
        doc = {
            "analysis_id": "an-x",
            "issues": [
                {"rule_id": "LT003", "asset_path": "/A"},
                {"rule_id": "LD004", "asset_path": "/C"},
            ],
        }
        finding, error = await _resolve_against(doc, rule_id="LD004", asset_path="")
        assert error == ""
        assert finding["rule_id"] == "LD004"

    @pytest.mark.anyio
    async def test_a_single_finding_needs_no_selector(self):
        doc = {"analysis_id": "an-x", "issues": [{"rule_id": "LT003"}]}
        finding, error = await _resolve_against(doc, rule_id="", asset_path="")
        assert error == ""
        assert finding["rule_id"] == "LT003"


async def _resolve_against(doc, rule_id: str, asset_path: str):
    """Run _resolve_from_analysis against an in-memory document.

    The action reads Mongo directly; these tests stub that single lookup
    rather than standing up a database for three list comprehensions.
    """
    import sys
    import types

    from modules.assistant.actions import explain_finding

    class _Coll:
        async def find_one(self, query):
            return doc if query.get("analysis_id") == doc["analysis_id"] else None

    fake_db = types.ModuleType("api.database")
    fake_db.analysis_results = _Coll()  # type: ignore[attr-defined]
    real = sys.modules.get("api.database")
    sys.modules["api.database"] = fake_db
    try:
        return await explain_finding._resolve_from_analysis(
            doc["analysis_id"], rule_id, asset_path
        )
    finally:
        if real is not None:
            sys.modules["api.database"] = real
        else:
            sys.modules.pop("api.database", None)


class TestActionCoverage:
    def test_every_intent_has_an_action(self):
        from modules.assistant.actions import ACTIONS

        # general_help is answered by the route itself; everything else
        # must have a deterministic action behind it.
        assert set(ACTIONS) == ALL_INTENTS - {"general_help"}
