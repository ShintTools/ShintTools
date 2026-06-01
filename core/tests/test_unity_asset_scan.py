# core/tests/test_unity_asset_scan.py
#
# Tests for POST /assets/unity/scan — the Unity Asset Tool endpoint.
#
# Structure:
#   TestLayer1BuiltinRules   — NMU* findings for free and indie tiers
#   TestLayer2NamingRules    — user prefix/suffix rules (indie+ only)
#   TestLayer3GenericRules   — LLM layer via mocked check_custom_rules
#   TestTierGating           — free tier only gets layer 1
#   TestApplyNamingRuleUnit  — unit tests for the _apply_naming_rule helper
#
# resolve_tier is monkeypatched to avoid hitting MongoDB.
# check_custom_rules is monkeypatched to avoid hitting the LLM.

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

# ── Helpers ────────────────────────────────────────────────────────────────


def _scan_payload(
    files: list[dict],
    naming_rules: list[dict] | None = None,
    generic_rules: list[dict] | None = None,
    api_key: str = "",
) -> dict:
    return {
        "api_key": api_key,
        "files": files,
        "namingRules": naming_rules or [],
        "genericRules": generic_rules or [],
    }


def _paths(findings: list[dict]) -> set[str]:
    return {f["path"] for f in findings}


def _rule_ids(findings: list[dict]) -> list[str]:
    return [f.get("rule_id", "") for f in findings]


# ── Layer 1: built-in naming rules ────────────────────────────────────────


class TestLayer1BuiltinRules:
    """Built-in NMU* rules run for all tiers."""

    @pytest.mark.anyio
    async def test_missing_prefix_detected(self, async_client):
        # HeroDiffuse.png has no T_ prefix — NMU001 should fire.
        payload = _scan_payload(
            [
                {"path": "Assets/Textures/HeroDiffuse.png", "type": "Texture2D"},
                {"path": "Assets/Textures/T_Hero.png", "type": "Texture2D"},
            ]
        )
        resp = await async_client.post("/assets/unity/scan", json=payload)
        assert resp.status_code == 200
        findings = resp.json()["files"]
        violating = [
            f for f in findings if f["path"] == "Assets/Textures/HeroDiffuse.png"
        ]
        assert any(f["rule_id"] == "NMU001" for f in violating)

    @pytest.mark.anyio
    async def test_prefixed_asset_does_not_fire_nmu001(self, async_client):
        # A correctly prefixed asset must NOT produce an NMU001 finding even
        # if other rules (e.g. texture suffix convention) also apply.
        payload = _scan_payload(
            [
                {"path": "Assets/Textures/T_Hero.png", "type": "Texture2D"},
            ]
        )
        resp = await async_client.post("/assets/unity/scan", json=payload)
        assert resp.status_code == 200
        nmu001_findings = [
            f for f in resp.json()["files"] if f.get("rule_id") == "NMU001"
        ]
        assert (
            nmu001_findings == []
        ), "NMU001 must not fire for an asset with correct prefix"

    @pytest.mark.anyio
    async def test_spaces_in_name_remapped_to_nmu017(self, async_client):
        # NM002 (spaces in name) must be remapped to NMU017 for Unity scans.
        payload = _scan_payload(
            [
                {"path": "Assets/Textures/Hero Sword.png", "type": "Texture2D"},
            ]
        )
        resp = await async_client.post("/assets/unity/scan", json=payload)
        assert resp.status_code == 200
        findings = resp.json()["files"]
        assert any(
            f.get("rule_id") == "NMU017" for f in findings
        ), "NM002 (spaces) should be remapped to NMU017 for Unity"

    @pytest.mark.anyio
    async def test_layer1_finding_has_required_fields(self, async_client):
        # Layer 1 findings must carry rule_id, rule_name, severity, message,
        # is_auto_fixable so the plugin can display them correctly.
        payload = _scan_payload(
            [
                {"path": "Assets/Textures/HeroDiffuse.png", "type": "Texture2D"},
            ]
        )
        resp = await async_client.post("/assets/unity/scan", json=payload)
        findings = [
            f
            for f in resp.json()["files"]
            if f.get("genericRule") == -1 and f.get("namingRule") == -1
        ]
        assert findings, "Expected at least one layer-1 finding"
        f = findings[0]
        assert f["path"]
        assert f["rule_id"]
        assert f["rule_name"]
        assert f["severity"] in ("error", "warning", "info")
        assert isinstance(f["is_auto_fixable"], bool)
        assert f["genericRule"] == -1
        assert f["namingRule"] == -1

    @pytest.mark.anyio
    async def test_response_shape(self, async_client):
        payload = _scan_payload(
            [
                {"path": "Assets/Textures/HeroDiffuse.png", "type": "Texture2D"},
            ]
        )
        resp = await async_client.post("/assets/unity/scan", json=payload)
        body = resp.json()
        assert "error" in body
        assert "time" in body
        assert "files" in body
        assert isinstance(body["time"], float)


# ── Layer 2: user naming rules ────────────────────────────────────────────


class TestLayer2NamingRules:
    """User-defined prefix/suffix rules — indie+ only, deterministic."""

    @pytest.fixture
    def _indie_tier(self, monkeypatch):
        monkeypatch.setattr(
            "api.routes.assets.resolve_tier",
            AsyncMock(return_value="indie"),
        )

    @pytest.mark.anyio
    async def test_prefix_violation_detected(self, async_client, _indie_tier):
        payload = _scan_payload(
            files=[
                {"path": "Assets/Textures/HeroDiffuse.png", "type": "Texture2D"},
                {"path": "Assets/Textures/T_ValidTexture.png", "type": "Texture2D"},
                {"path": "Assets/Materials/RockSurface.mat", "type": "Material"},
            ],
            naming_rules=[
                {"type": "Texture2D", "prefix": "T_", "suffix": ""},
            ],
        )
        resp = await async_client.post("/assets/unity/scan", json=payload)
        assert resp.status_code == 200
        layer2 = [f for f in resp.json()["files"] if f.get("namingRule") == 0]
        paths = _paths(layer2)
        assert "Assets/Textures/HeroDiffuse.png" in paths
        assert "Assets/Textures/T_ValidTexture.png" not in paths
        assert "Assets/Materials/RockSurface.mat" not in paths

    @pytest.mark.anyio
    async def test_fix_has_correct_prefix_no_double_underscore(
        self, async_client, _indie_tier
    ):
        # prefix "T_" must produce "T_HeroDiffuse", not "T__HeroDiffuse".
        payload = _scan_payload(
            files=[{"path": "Assets/Textures/HeroDiffuse.png", "type": "Texture2D"}],
            naming_rules=[{"type": "Texture2D", "prefix": "T_", "suffix": ""}],
        )
        resp = await async_client.post("/assets/unity/scan", json=payload)
        layer2 = [f for f in resp.json()["files"] if f.get("namingRule") == 0]
        assert layer2, "Expected a layer-2 finding"
        assert layer2[0]["fix"] == "T_HeroDiffuse"

    @pytest.mark.anyio
    async def test_suffix_violation_detected(self, async_client, _indie_tier):
        payload = _scan_payload(
            files=[
                {"path": "Assets/Materials/RockSurface.mat", "type": "Material"},
                {"path": "Assets/Materials/RockSurface_M.mat", "type": "Material"},
            ],
            naming_rules=[
                {"type": "Material", "prefix": "", "suffix": "_M"},
            ],
        )
        resp = await async_client.post("/assets/unity/scan", json=payload)
        layer2 = [f for f in resp.json()["files"] if f.get("namingRule") == 0]
        paths = _paths(layer2)
        assert "Assets/Materials/RockSurface.mat" in paths
        assert "Assets/Materials/RockSurface_M.mat" not in paths

    @pytest.mark.anyio
    async def test_type_mismatch_skips_rule(self, async_client, _indie_tier):
        # Rule applies only to Texture2D — Material must not get flagged.
        payload = _scan_payload(
            files=[{"path": "Assets/Materials/RockSurface.mat", "type": "Material"}],
            naming_rules=[{"type": "Texture2D", "prefix": "T_", "suffix": ""}],
        )
        resp = await async_client.post("/assets/unity/scan", json=payload)
        layer2 = [f for f in resp.json()["files"] if f.get("namingRule") != -1]
        assert layer2 == []

    @pytest.mark.anyio
    async def test_multiple_naming_rules_correct_index(self, async_client, _indie_tier):
        payload = _scan_payload(
            files=[
                {"path": "Assets/Textures/Hero.png", "type": "Texture2D"},
                {"path": "Assets/Materials/Rock.mat", "type": "Material"},
            ],
            naming_rules=[
                {"type": "Texture2D", "prefix": "T_", "suffix": ""},
                {"type": "Material", "prefix": "M_", "suffix": ""},
            ],
        )
        resp = await async_client.post("/assets/unity/scan", json=payload)
        layer2 = [f for f in resp.json()["files"] if f.get("namingRule") != -1]
        indices = {f["namingRule"] for f in layer2}
        # Texture violation → index 0, Material violation → index 1
        assert 0 in indices
        assert 1 in indices


# ── Layer 3: generic rules (LLM) ─────────────────────────────────────────


class TestLayer3GenericRules:
    """LLM-backed rules — indie+, requires SHINTTOOLS_AGENT_ENABLED=1."""

    @pytest.fixture
    def _indie_agent(self, monkeypatch):
        monkeypatch.setattr(
            "api.routes.assets.resolve_tier",
            AsyncMock(return_value="indie"),
        )
        monkeypatch.setenv("SHINTTOOLS_AGENT_ENABLED", "1")

    @pytest.mark.anyio
    async def test_layer3_returns_violations_from_llm(
        self, async_client, _indie_agent, monkeypatch
    ):
        from modules.agent.custom_rule_checker import RuleViolation

        fake_violation = RuleViolation(
            file_path="Assets/Scripts/EnemyAI.cs",
            rule_name="Scripts that inherit from CustomWindow must end with Window",
            finding="EnemyAI does not end with 'Window' suffix.",
            fix_suggestion="EnemyAIWindow",
            line=0,
        )
        monkeypatch.setattr(
            "api.routes.assets.check_custom_rules",
            MagicMock(return_value=[fake_violation]),
        )

        payload = _scan_payload(
            files=[
                {"path": "Assets/Scripts/EnemyAI.cs", "type": "MonoScript"},
                {"path": "Assets/Scripts/GameManager.cs", "type": "MonoScript"},
            ],
            generic_rules=[
                {
                    "problem": "Scripts that inherit from CustomWindow must end with Window",
                    "solution": "Rename adding Window suffix",
                }
            ],
        )
        resp = await async_client.post("/assets/unity/scan", json=payload)
        assert resp.status_code == 200
        layer3 = [f for f in resp.json()["files"] if f.get("genericRule") != -1]
        assert len(layer3) == 1
        assert layer3[0]["path"] == "Assets/Scripts/EnemyAI.cs"
        assert layer3[0]["genericRule"] == 0
        assert layer3[0]["namingRule"] == -1
        assert layer3[0]["fix"] == "EnemyAIWindow"

    @pytest.mark.anyio
    async def test_layer3_skipped_when_agent_disabled(self, async_client, monkeypatch):
        monkeypatch.setattr(
            "api.routes.assets.resolve_tier",
            AsyncMock(return_value="indie"),
        )
        monkeypatch.setenv("SHINTTOOLS_AGENT_ENABLED", "0")

        mock_checker = MagicMock()
        monkeypatch.setattr("api.routes.assets.check_custom_rules", mock_checker)

        payload = _scan_payload(
            files=[{"path": "Assets/Scripts/EnemyAI.cs", "type": "MonoScript"}],
            generic_rules=[{"problem": "Some rule", "solution": "Some fix"}],
        )
        resp = await async_client.post("/assets/unity/scan", json=payload)
        assert resp.status_code == 200
        layer3 = [f for f in resp.json()["files"] if f.get("genericRule") != -1]
        assert layer3 == []

    @pytest.mark.anyio
    async def test_layer3_passes_correct_types_to_checker(
        self, async_client, _indie_agent, monkeypatch
    ):
        """Verify CustomRule objects and (path, content) tuples reach check_custom_rules."""
        from modules.agent.custom_rule_checker import CustomRule

        captured: dict = {}

        def _capture(rules, files, **kwargs):
            captured["rules"] = rules
            captured["files"] = files
            return []

        monkeypatch.setattr("api.routes.assets.check_custom_rules", _capture)

        payload = _scan_payload(
            files=[{"path": "Assets/Scripts/Foo.cs", "type": "MonoScript"}],
            generic_rules=[{"problem": "Test problem", "solution": "Test solution"}],
        )
        await async_client.post("/assets/unity/scan", json=payload)

        assert "rules" in captured
        assert len(captured["rules"]) == 1
        rule = captured["rules"][0]
        assert isinstance(rule, CustomRule)
        assert rule.name == "Test problem"
        assert rule.description == "Test solution"

        assert "files" in captured
        assert len(captured["files"]) == 1
        path, content = captured["files"][0]
        assert path == "Assets/Scripts/Foo.cs"
        assert "MonoScript" in content

    @pytest.mark.anyio
    async def test_layer3_generic_rule_index_correct(
        self, async_client, _indie_agent, monkeypatch
    ):
        """genericRule field must match the rule's index in the request array."""
        from modules.agent.custom_rule_checker import RuleViolation

        # Violation for the SECOND rule (index 1).
        fake_v = RuleViolation(
            file_path="Assets/Scripts/Foo.cs",
            rule_name="Second rule",
            finding="X",
            fix_suggestion="Y",
        )
        monkeypatch.setattr(
            "api.routes.assets.check_custom_rules",
            MagicMock(return_value=[fake_v]),
        )

        payload = _scan_payload(
            files=[{"path": "Assets/Scripts/Foo.cs", "type": "MonoScript"}],
            generic_rules=[
                {"problem": "First rule", "solution": "fix 1"},
                {"problem": "Second rule", "solution": "fix 2"},
            ],
        )
        resp = await async_client.post("/assets/unity/scan", json=payload)
        layer3 = [f for f in resp.json()["files"] if f.get("genericRule") != -1]
        assert layer3[0]["genericRule"] == 1


# ── Tier gating ───────────────────────────────────────────────────────────


class TestTierGating:
    """free → only layer 1; indie → all three layers."""

    @pytest.mark.anyio
    async def test_free_tier_omits_layer2_and_layer3(self, async_client, monkeypatch):
        # free tier is the default when MongoDB is unreachable — no mock needed.
        mock_checker = MagicMock(return_value=[])
        monkeypatch.setattr("api.routes.assets.check_custom_rules", mock_checker)
        monkeypatch.setenv("SHINTTOOLS_AGENT_ENABLED", "1")

        payload = _scan_payload(
            files=[{"path": "Assets/Textures/HeroDiffuse.png", "type": "Texture2D"}],
            naming_rules=[{"type": "Texture2D", "prefix": "T_", "suffix": ""}],
            generic_rules=[{"problem": "Some rule", "solution": "fix"}],
        )
        resp = await async_client.post("/assets/unity/scan", json=payload)
        assert resp.status_code == 200
        findings = resp.json()["files"]

        # Layer 2 and 3 must not appear for free tier.
        layer2 = [f for f in findings if f.get("namingRule", -1) != -1]
        layer3 = [f for f in findings if f.get("genericRule", -1) != -1]
        assert layer2 == []
        assert layer3 == []
        # check_custom_rules must NOT have been called.
        mock_checker.assert_not_called()

    @pytest.mark.anyio
    async def test_indie_tier_exposes_all_layers(self, async_client, monkeypatch):
        monkeypatch.setattr(
            "api.routes.assets.resolve_tier",
            AsyncMock(return_value="indie"),
        )
        monkeypatch.setenv("SHINTTOOLS_AGENT_ENABLED", "1")

        from modules.agent.custom_rule_checker import RuleViolation

        fake_v = RuleViolation(
            file_path="Assets/Textures/HeroDiffuse.png",
            rule_name="Test rule",
            finding="X",
            fix_suggestion="T_HeroDiffuse",
        )
        monkeypatch.setattr(
            "api.routes.assets.check_custom_rules",
            MagicMock(return_value=[fake_v]),
        )

        payload = _scan_payload(
            files=[{"path": "Assets/Textures/HeroDiffuse.png", "type": "Texture2D"}],
            naming_rules=[{"type": "Texture2D", "prefix": "T_", "suffix": ""}],
            generic_rules=[{"problem": "Test rule", "solution": "add T_"}],
        )
        resp = await async_client.post("/assets/unity/scan", json=payload)
        assert resp.status_code == 200
        findings = resp.json()["files"]

        layer2 = [f for f in findings if f.get("namingRule", -1) != -1]
        layer3 = [f for f in findings if f.get("genericRule", -1) != -1]
        assert layer2, "Expected layer-2 findings for indie tier"
        assert layer3, "Expected layer-3 findings for indie tier"


# ── Unit tests for _apply_naming_rule ─────────────────────────────────────


class TestApplyNamingRuleUnit:
    """Direct unit tests for the _apply_naming_rule helper — no HTTP."""

    def _file(self, path: str, asset_type: str = "Texture2D"):
        from api.routes.assets import UnityAssetFile

        return UnityAssetFile(path=path, type=asset_type)

    def _rule(self, asset_type: str, prefix: str, suffix: str):
        from api.routes.assets import NamingRule

        return NamingRule(type=asset_type, prefix=prefix, suffix=suffix)

    def test_prefix_violation_correct_fix(self):
        from api.routes.assets import _apply_naming_rule

        result = _apply_naming_rule(
            self._file("Assets/Textures/HeroDiffuse.png"),
            self._rule("Texture2D", "T_", ""),
            0,
        )
        assert result is not None
        assert result["fix"] == "T_HeroDiffuse"

    def test_prefix_no_double_underscore(self):
        from api.routes.assets import _apply_naming_rule

        # "T_" prefix + "HeroDiffuse" → must NOT produce "T__HeroDiffuse"
        result = _apply_naming_rule(
            self._file("Assets/Textures/HeroDiffuse.png"),
            self._rule("Texture2D", "T_", ""),
            0,
        )
        assert result["fix"] == "T_HeroDiffuse"
        assert "__" not in result["fix"]

    def test_prefix_without_trailing_underscore(self):
        from api.routes.assets import _apply_naming_rule

        # prefix "T" (no trailing _) should produce "T_HeroDiffuse"
        result = _apply_naming_rule(
            self._file("Assets/Textures/HeroDiffuse.png"),
            self._rule("Texture2D", "T", ""),
            0,
        )
        assert result is not None
        assert result["fix"] == "T_HeroDiffuse"

    def test_suffix_violation(self):
        from api.routes.assets import _apply_naming_rule

        result = _apply_naming_rule(
            self._file("Assets/Materials/Rock.mat", "Material"),
            self._rule("Material", "", "_M"),
            1,
        )
        assert result is not None
        assert result["fix"] == "Rock_M"
        assert result["namingRule"] == 1

    def test_clean_asset_returns_none(self):
        from api.routes.assets import _apply_naming_rule

        result = _apply_naming_rule(
            self._file("Assets/Textures/T_Hero.png"),
            self._rule("Texture2D", "T_", ""),
            0,
        )
        assert result is None

    def test_type_mismatch_returns_none(self):
        from api.routes.assets import _apply_naming_rule

        result = _apply_naming_rule(
            self._file("Assets/Materials/Rock.mat", "Material"),
            self._rule("Texture2D", "T_", ""),
            0,
        )
        assert result is None

    def test_finding_has_correct_layer_indices(self):
        from api.routes.assets import _apply_naming_rule

        result = _apply_naming_rule(
            self._file("Assets/Textures/HeroDiffuse.png"),
            self._rule("Texture2D", "T_", ""),
            2,
        )
        assert result["genericRule"] == -1
        assert result["namingRule"] == 2
