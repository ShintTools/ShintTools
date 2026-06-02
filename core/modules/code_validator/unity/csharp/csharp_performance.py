# core/modules/code_validator/rules/csharp/csharp_performance.py
#
# C# / Unity performance rule detectors - CSP001-CSP016 (11 implemented).
#
# CSP001  LINQ chain inside Update
# CSP002  String concatenation with += inside a loop
# CSP003  Heavy Mathf math inside Update
# CSP004  Instantiate inside Update
# CSP006  new WaitForSeconds per yield
# CSP007  String allocation inside Update
# CSP008  Large Update body
# CSP009  Collection copy inside a loop
# CSP010  new reference-type object inside a loop
# CSP011  Explicit GC.Collect()
# CSP012  Debug.Assert inside Update
# Total: 11 rules

from __future__ import annotations

import re
from typing import List

from code_validator.unity.csharp._csharp_helpers import (
    Issue,
    _emit,
    _find_method_body,
    _line_number,
    _update_body,
)
from code_validator.unity.parsers.csharp_parser import CsharpParser

_LINQ_OPERATORS = (
    r"Where|Select|SelectMany|ToList|ToArray|ToDictionary|First|FirstOrDefault|"
    r"Single|SingleOrDefault|Any|All|Count|GroupBy|OrderBy|OrderByDescending|"
    r"ThenBy|Aggregate|Distinct|Reverse|Take|Skip|Zip"
)


def _update_region(content: str):
    """Return (region_text, base_offset) for the Update/LateUpdate/
    FixedUpdate body.

    Tries the Tree-sitter ``CsharpParser`` first so deeply nested calls
    are extracted from the real AST ``block`` node. ``base_offset`` is the
    index of ``region_text`` inside ``content`` so the existing
    ``_line_number(content, base + m.start())`` arithmetic stays valid.

    Falls back to the regex ``_update_body`` brace-walker when
    tree-sitter is unavailable or the method is absent. Returns ``None``
    when no Update-family method exists.
    """
    try:
        parser = CsharpParser()
        tree = parser.parse(content)
        body_node = parser.find_function_body(tree, "Update")
    except Exception:
        span = _update_body(content)
        if not span:
            return None
        return content[span[0] : span[1]], span[0]
    else:
        if body_node is None:
            return None
        if hasattr(body_node, "text") and body_node.text is not None:
            region = body_node.text.decode("utf-8")
        else:
            region = content[body_node.start_byte : body_node.end_byte]
        return region, body_node.start_byte


def detect_linq_in_update(content: str, file_path: str) -> List[Issue]:
    """CSP001: LINQ chain inside Update - allocates enumerator+lambda each frame."""
    res = _update_region(content)
    if res is None:
        return []
    region, base = res
    m = re.search(rf"\.(?:{_LINQ_OPERATORS})\s*\(", region)
    if not m:
        return []
    line = _line_number(content, base + m.start())
    return [
        _emit(
            file_path,
            line,
            content,
            rule_id="CSP001",
            category="Performance",
            severity="warning",
            message="LINQ operator used inside Update - allocates enumerators/closures every frame.",  # noqa: E501
            fix_suggestion="Replace with a manual loop, or hoist the query result outside the per-frame path.",  # noqa: E501
        )
    ]


def detect_string_concat_in_loop(content: str, file_path: str) -> List[Issue]:
    """CSP002: `str += …` inside for/while/foreach body - O(n²) allocations.

    Detection: a `<var> +=` line whose RHS contains a string literal or
    `.ToString(`, located inside a brace-balanced loop body. Captures
    the most damaging case (per-iteration string build).
    """
    out: List[Issue] = []
    loop_re = re.compile(r"\b(?:for|foreach|while)\s*\(")
    for loop in loop_re.finditer(content):
        brace_open = content.find("{", loop.end())
        if brace_open < 0 or brace_open - loop.end() > 200:
            continue
        depth = 0
        end = brace_open
        for i in range(brace_open, len(content)):
            c = content[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        body_region = content[brace_open + 1 : end]
        for line_m in re.finditer(
            r"^[^\n]*\b\w+\s*\+=\s*[^\n;]*(?:\"[^\"]*\"|\.ToString\s*\()[^\n;]*;",
            body_region,
            re.MULTILINE,
        ):
            line_offset = brace_open + 1 + line_m.start()
            line = _line_number(content, line_offset)
            out.append(
                _emit(
                    file_path,
                    line,
                    content,
                    rule_id="CSP002",
                    category="Performance",
                    severity="warning",
                    message="String concatenation with += inside a loop - O(n^2) allocations.",  # noqa: E501
                    fix_suggestion="Build the result with `StringBuilder.Append` and call `.ToString()` once after the loop.",  # noqa: E501
                )
            )
    return out


def detect_heavy_math_in_update(content: str, file_path: str) -> List[Issue]:
    """CSP003: expensive Mathf calls inside Update - CPU overhead every frame."""
    res = _update_region(content)
    if res is None:
        return []
    region, base = res
    m = re.search(
        r"\bMathf\.(?:Sqrt|Sin|Cos|Tan|Asin|Acos|Atan|Atan2|Pow|Exp|Log)\s*\(",
        region,
    )
    if not m:
        return []
    fn_match = re.search(r"Mathf\.(\w+)", region[m.start() :])
    fn_name = fn_match.group(1) if fn_match else "Sqrt/Sin/Pow"
    line = _line_number(content, base + m.start())
    return [
        _emit(
            file_path,
            line,
            content,
            rule_id="CSP003",
            category="Performance",
            severity="warning",
            message=f"Mathf.{fn_name} called inside Update - transcendental math is expensive every frame.",  # noqa: E501
            fix_suggestion="Cache the result when inputs don't change every frame, or precompute a lookup table.",  # noqa: E501
        )
    ]


def detect_instantiate_in_update(content: str, file_path: str) -> List[Issue]:
    """CSP004: Instantiate inside Update - per-frame GameObject allocation."""
    res = _update_region(content)
    if res is None:
        return []
    region, base = res
    m = re.search(r"\bInstantiate\s*\(", region)
    if not m:
        return []
    line = _line_number(content, base + m.start())
    return [
        _emit(
            file_path,
            line,
            content,
            rule_id="CSP004",
            category="Performance",
            severity="error",
            message="Instantiate inside Update allocates a GameObject every frame - use object pooling.",  # noqa: E501
            fix_suggestion="Pre-spawn instances at Start and pull from a Queue/Stack pool; Destroy → SetActive(false).",  # noqa: E501
        )
    ]


def detect_new_waitforseconds(content: str, file_path: str) -> List[Issue]:
    """CSP006: `yield return new WaitForSeconds(x)` - allocates each yield.

    Caching the WaitForSeconds in a private field reuses one instance
    across coroutine iterations and avoids GC pressure on long-running
    loops.
    """
    out: List[Issue] = []
    for m in re.finditer(r"\byield\s+return\s+new\s+WaitForSeconds\s*\(", content):
        line = _line_number(content, m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="CSP006",
                category="Performance",
                severity="warning",
                message="`new WaitForSeconds(...)` per yield allocates each loop iteration.",  # noqa: E501
                fix_suggestion="Cache as a private field: `static readonly WaitForSeconds _wait = new(0.5f);` then `yield return _wait;`.",  # noqa: E501
            )
        )
    return out


def detect_string_ops_in_update(content: str, file_path: str) -> List[Issue]:
    """CSP007: string allocation inside Update - GC pressure every frame."""
    res = _update_region(content)
    if res is None:
        return []
    region, base = res
    m = re.search(
        r'(?:string\.Format|String\.Format|string\.Concat|\$"[^"]*"'
        r'|"[^"]+"\s*\+\s*\w|\w+\s*\+\s*"[^"]+")',
        region,
    )
    if not m:
        return []
    line = _line_number(content, base + m.start())
    return [
        _emit(
            file_path,
            line,
            content,
            rule_id="CSP007",
            category="Performance",
            severity="warning",
            message="String allocation inside Update generates heap garbage every frame.",  # noqa: E501
            fix_suggestion="Cache static strings, use StringBuilder, or avoid interpolation in per-frame paths.",  # noqa: E501
        )
    ]


def detect_large_update_body(content: str, file_path: str) -> List[Issue]:
    """CSP008: Update method body exceeds 50 lines - too much work per frame."""
    try:
        parser = CsharpParser()
        tree = parser.parse(content)
        # CSP008 only flags Update / LateUpdate (NOT FixedUpdate), so we
        # scan method nodes in document order and take the first whose
        # name is exactly Update or LateUpdate - the Update alias in
        # find_function_body would also match FixedUpdate.
        body_node = None
        for _n in parser._traverse(tree):
            if _n.type != "method_declaration":
                continue
            for _c in _n.children:
                if (
                    _c.type == "identifier"
                    and _c.text
                    and _c.text.decode("utf-8") in ("Update", "LateUpdate")
                ):
                    body_node = parser._find_child(_n, "block")
                    break
            if body_node is not None:
                break
    except Exception:
        sig_re = r"\b(?:private|public|protected|internal)?\s*void\s+(?:Update|LateUpdate)\s*\(\s*\)"  # noqa: E501
        span = _find_method_body(content, sig_re)
        if not span:
            return []
        body_lines = content[span[0] : span[1]].count("\n")
        sig_line = span[2]
    else:
        if body_node is None:
            return []
        if hasattr(body_node, "text") and body_node.text is not None:
            body_lines = body_node.text.decode("utf-8").count("\n")
        else:
            body_lines = content[body_node.start_byte : body_node.end_byte].count("\n")
        # Mirror the regex helper which reported the signature line; the
        # method_declaration parent's first line is that signature.
        method_node = body_node.parent
        sig_line = (
            method_node.start_point[0] + 1
            if method_node is not None
            else body_node.start_point[0] + 1
        )
    if body_lines < 50:
        return []
    return [
        _emit(
            file_path,
            sig_line,
            content,
            rule_id="CSP008",
            category="Performance",
            severity="warning",
            message=f"Update/LateUpdate has {body_lines} lines - split heavy logic into helpers or move off the frame path.",  # noqa: E501
            fix_suggestion="Extract sub-tasks into private methods; move work that doesn't need to run every frame into Coroutines.",  # noqa: E501
        )
    ]


def detect_collection_copy_in_loop(content: str, file_path: str) -> List[Issue]:
    """CSP009: new List<T>(existing) or .ToList()/.ToArray() inside a loop - O(n) allocation per iteration."""  # noqa: E501
    out: List[Issue] = []
    loop_re = re.compile(r"\b(?:for|foreach|while)\s*\(")
    for loop in loop_re.finditer(content):
        brace_open = content.find("{", loop.end())
        if brace_open < 0 or brace_open - loop.end() > 200:
            continue
        depth, end = 0, brace_open
        for i in range(brace_open, len(content)):
            if content[i] == "{":
                depth += 1
            elif content[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        body_region = content[brace_open + 1 : end]
        m = re.search(
            r"new\s+(?:List|HashSet|Dictionary|Queue|Stack)\s*<[^>]+>\s*\(\s*\w",
            body_region,
        )
        if not m:
            m = re.search(
                r"\.\s*(?:ToList|ToArray|ToDictionary|ToHashSet)\s*\(\s*\)", body_region
            )
        if not m:
            continue
        line = _line_number(content, brace_open + 1 + m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="CSP009",
                category="Performance",
                severity="warning",
                message="Collection copy/allocation inside a loop - allocates on every iteration.",  # noqa: E501
                fix_suggestion="Create the collection once outside the loop and Clear()/reuse inside.",  # noqa: E501
            )
        )
    return out


def detect_new_object_in_loop(content: str, file_path: str) -> List[Issue]:
    """CSP010: `new T()` for a reference type inside a loop - managed heap allocation per iteration."""  # noqa: E501
    out: List[Issue] = []
    _VALUE_TYPES = frozenset(
        {
            "int",
            "float",
            "double",
            "long",
            "byte",
            "short",
            "uint",
            "bool",
            "Vector2",
            "Vector3",
            "Vector4",
            "Color",
            "Color32",
            "Rect",
            "Bounds",
            "Quaternion",
            "WaitForSeconds",
            "WaitForEndOfFrame",
            "WaitForFixedUpdate",
        }
    )
    loop_re = re.compile(r"\b(?:for|foreach|while)\s*\(")
    for loop in loop_re.finditer(content):
        brace_open = content.find("{", loop.end())
        if brace_open < 0 or brace_open - loop.end() > 200:
            continue
        depth, end = 0, brace_open
        for i in range(brace_open, len(content)):
            if content[i] == "{":
                depth += 1
            elif content[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        body_region = content[brace_open + 1 : end]
        m = re.search(r"\bnew\s+([A-Z]\w+)\s*\(", body_region)
        if not m or m.group(1) in _VALUE_TYPES:
            continue
        line = _line_number(content, brace_open + 1 + m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="CSP010",
                category="Performance",
                severity="warning",
                message=f"new {m.group(1)}() inside a loop allocates a managed object on each iteration.",  # noqa: E501
                fix_suggestion="Allocate outside the loop and reset state inside, or use an object pool.",  # noqa: E501
            )
        )
    return out


def detect_gc_collect(content: str, file_path: str) -> List[Issue]:
    """CSP011: explicit GC.Collect() call - forces a stop-the-world GC pause."""
    out: List[Issue] = []
    for m in re.finditer(r"\bGC\.Collect\s*\(", content):
        line = _line_number(content, m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="CSP011",
                category="Performance",
                severity="error",
                message="GC.Collect() forces a synchronous garbage collection - causes visible frame spikes.",  # noqa: E501
                fix_suggestion="Remove the call and let the GC run autonomously; profile with Unity Memory Profiler before forcing collection.",  # noqa: E501
            )
        )
    return out


def detect_debug_assert_in_update(content: str, file_path: str) -> List[Issue]:
    """CSP012: Debug.Assert inside Update - evaluates condition and formats message every frame."""  # noqa: E501
    res = _update_region(content)
    if res is None:
        return []
    region, base = res
    m = re.search(r"\bDebug\.Assert\s*\(", region)
    if not m:
        return []
    line = _line_number(content, base + m.start())
    return [
        _emit(
            file_path,
            line,
            content,
            rule_id="CSP012",
            category="Performance",
            severity="warning",
            message="Debug.Assert inside Update evaluates its condition and formats the message every frame.",  # noqa: E501
            fix_suggestion="Wrap in `#if UNITY_EDITOR` or `#if DEBUG`, or move the assertion to Awake/Start.",  # noqa: E501
        )
    ]
