# core/modules/naming/tests/test_compliant_guard.py
#
# Tests for the "already-compliant" guard in naming_orchestrator:
#   _drop_noop_suggestions() removes findings whose fix_suggestion equals
#   the current asset name (the asset already follows the convention),
#   except for rules that legitimately keep the name.

import sys
from pathlib import Path

_MODULES = Path(__file__).parent.parent.parent  # core/modules
_CORE = _MODULES.parent  # core
sys.path.insert(0, str(_CORE))
sys.path.insert(0, str(_MODULES))

from naming.naming_orchestrator import (  # noqa: E402
    _NAME_PRESERVING_RULES,
    _drop_noop_suggestions,
    run_all_naming_rules,
)


def _issue(rule_id, current, fix):
    return {"rule_id": rule_id, "current_name": current, "fix_suggestion": fix}


# ── _drop_noop_suggestions unit ──────────────────────────────────────────


def test_rename_noop_is_dropped():
    # A rename rule (NM007) whose fix equals the current name == compliant.
    issues = [_issue("NM007", "SM_Rock", "SM_Rock")]
    assert _drop_noop_suggestions(issues) == []


def test_real_rename_is_kept():
    issues = [_issue("NM007", "SM_rock", "SM_Rock")]
    assert _drop_noop_suggestions(issues) == issues


def test_name_preserving_rules_kept_even_when_same():
    # Wrong-folder / duplicate / unfixable rules keep their same-name finding.
    issues = [_issue(rid, "SM_Rock", "SM_Rock") for rid in _NAME_PRESERVING_RULES]
    assert _drop_noop_suggestions(issues) == issues


def test_missing_current_name_is_untouched():
    # Unity-specific findings carry no current_name -> never dropped.
    issues = [{"rule_id": "NMU017", "fix_suggestion": "Assets/T_Rock.png"}]
    assert _drop_noop_suggestions(issues) == issues
    issues2 = [_issue("NM007", "", "SM_Rock")]
    assert _drop_noop_suggestions(issues2) == issues2


def test_whitespace_difference_only_is_dropped():
    issues = [_issue("NM007", "SM_Rock", "SM_Rock ")]
    assert _drop_noop_suggestions(issues) == []


# ── end-to-end through run_all_naming_rules ──────────────────────────────


def test_compliant_asset_yields_no_findings():
    records = [{"asset_path": "/Game/Meshes/SM_Rock", "asset_type": "StaticMesh"}]
    issues = run_all_naming_rules(records, engine="unreal")
    assert issues == []


def test_wrong_folder_finding_survives_guard():
    # Correct name, wrong folder -> NM009 with same-name suggestion, must stay.
    records = [{"asset_path": "/Game/Textures/SM_Rock", "asset_type": "StaticMesh"}]
    issues = run_all_naming_rules(records, engine="unreal")
    assert any(i["rule_id"] == "NM009" for i in issues)
