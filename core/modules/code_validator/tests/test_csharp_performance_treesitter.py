"""Tests for Tree-sitter-based Update body extraction in CSP rules.

Covers every csharp_performance rule that extracts the Update /
LateUpdate / FixedUpdate body (CSP001, CSP003, CSP004, CSP007, CSP008,
CSP012). The actual csharp_performance.py only has 6 Update-body
extractors — the loop/global rules (CSP002/006/009/010/011) never call
_update_body() and were intentionally left untouched.

Each migrated rule gets:
  1. a deeply-nested positive (bad call 3+ blocks deep inside Update)
  2. a clean negative (no issues)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "modules"))

from code_validator.unity.csharp.csharp_performance import (  # noqa: E402
    detect_debug_assert_in_update,
    detect_heavy_math_in_update,
    detect_instantiate_in_update,
    detect_large_update_body,
    detect_linq_in_update,
    detect_string_ops_in_update,
)
from code_validator.unity.parsers.csharp_parser import CsharpParser  # noqa: E402

FP = "Assets/Scripts/MyBehaviour.cs"


def _nested(bad_line: str) -> str:
    """Update with `bad_line` buried 3 blocks deep (if>for>if)."""
    return (
        "using UnityEngine;\n"
        "public class Outer {\n"
        "  public class MyBehaviour : MonoBehaviour {\n"
        "    void Update() {\n"
        "        if (condition) {\n"
        "            for (int i = 0; i < 10; i++) {\n"
        "                if (i > 0) {\n"
        f"                    {bad_line}\n"
        "                }\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "  }\n"
        "}\n"
    )


_CLEAN = (
    "using UnityEngine;\n"
    "public class MyBehaviour : MonoBehaviour {\n"
    "    private int _cached;\n"
    "    void Update() {\n"
    "        _cached += 1;\n"
    "        transform.position = _pos;\n"
    "    }\n"
    "}\n"
)


# ── sanity: parser actually reaches the nested node ──────────────────


def test_parser_finds_nested_update_body():
    p = CsharpParser()
    tree = p.parse(_nested("Foo();"))
    body = p.find_function_body(tree, "Update")
    assert body is not None
    assert "Foo();" in body.text.decode("utf-8")


def test_parser_update_alias_matches_lateupdate():
    src = "public class B : MonoBehaviour {\n" "  void LateUpdate() { Bar(); }\n" "}\n"
    p = CsharpParser()
    body = p.find_function_body(p.parse(src), "Update")
    assert body is not None and "Bar();" in body.text.decode("utf-8")


# ── CSP001 — LINQ inside Update ──────────────────────────────────────


def test_csp001_nested_positive():
    issues = detect_linq_in_update(
        _nested("var r = items.Where(x => x > 0).ToList();"), FP
    )
    assert len(issues) == 1 and issues[0]["rule_id"] == "CSP001"


def test_csp001_negative():
    assert detect_linq_in_update(_CLEAN, FP) == []


# ── CSP003 — heavy Mathf inside Update ───────────────────────────────


def test_csp003_nested_positive():
    issues = detect_heavy_math_in_update(
        _nested("float d = Mathf.Sqrt(x * x + y * y);"), FP
    )
    assert len(issues) == 1 and issues[0]["rule_id"] == "CSP003"


def test_csp003_negative():
    assert detect_heavy_math_in_update(_CLEAN, FP) == []


# ── CSP004 — Instantiate inside Update ───────────────────────────────


def test_csp004_nested_positive():
    issues = detect_instantiate_in_update(_nested("Instantiate(prefab, pos, rot);"), FP)
    assert len(issues) == 1 and issues[0]["rule_id"] == "CSP004"


def test_csp004_negative():
    assert detect_instantiate_in_update(_CLEAN, FP) == []


# ── CSP007 — string allocation inside Update ─────────────────────────


def test_csp007_nested_positive():
    issues = detect_string_ops_in_update(
        _nested('string s = string.Format("hp {0}", hp);'), FP
    )
    assert len(issues) == 1 and issues[0]["rule_id"] == "CSP007"


def test_csp007_negative():
    assert detect_string_ops_in_update(_CLEAN, FP) == []


# ── CSP008 — large Update body ───────────────────────────────────────


def test_csp008_nested_positive():
    filler = "\n".join(f"        int v{i} = {i};" for i in range(60))
    src = (
        "using UnityEngine;\n"
        "public class Outer {\n"
        "  public class MyBehaviour : MonoBehaviour {\n"
        "    void Update() {\n"
        "        if (true) {\n"
        f"{filler}\n"
        "        }\n"
        "    }\n"
        "  }\n"
        "}\n"
    )
    issues = detect_large_update_body(src, FP)
    assert len(issues) == 1 and issues[0]["rule_id"] == "CSP008"


def test_csp008_negative():
    assert detect_large_update_body(_CLEAN, FP) == []


# ── CSP012 — Debug.Assert inside Update ──────────────────────────────


def test_csp012_nested_positive():
    issues = detect_debug_assert_in_update(
        _nested('Debug.Assert(hp >= 0, "hp underflow");'), FP
    )
    assert len(issues) == 1 and issues[0]["rule_id"] == "CSP012"


def test_csp012_negative():
    assert detect_debug_assert_in_update(_CLEAN, FP) == []
