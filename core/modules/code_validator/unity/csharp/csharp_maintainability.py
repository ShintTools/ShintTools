# core/modules/code_validator/rules/csharp/csharp_maintainability.py
#
# C# / Unity maintainability rule detectors - CSM001-CSM008 (5 implemented).
#
# CSM001  Method body exceeds 50 lines
# CSM002  File exceeds 500 lines
# CSM003  God object (>12 public members)
# CSM004  Method with >5 parameters
# CSM005  Control-flow nesting depth >= 4
# Total: 5 rules

from __future__ import annotations

import re
from typing import List

from code_validator.unity.csharp._csharp_helpers import Issue, _emit, _line_number


def detect_long_method(content: str, file_path: str) -> List[Issue]:
    """CSM001: method body exceeds 50 lines."""
    out: List[Issue] = []
    method_re = re.compile(
        r"\b(?:public|private|protected|internal)\s+(?:static\s+|virtual\s+|override\s+|async\s+|sealed\s+)*"  # noqa: E501
        r"[\w<>,\s\[\]?]+?\s+(\w+)\s*\([^)]*\)\s*\{",
    )
    for m in method_re.finditer(content):
        # Walk the body to find its closing brace.
        depth = 1
        brace_open = m.end() - 1
        end = brace_open
        for i in range(m.end(), len(content)):
            if content[i] == "{":
                depth += 1
            elif content[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        body_lines = content[brace_open + 1 : end].count("\n")
        if body_lines >= 50:
            line = _line_number(content, m.start())
            out.append(
                _emit(
                    file_path,
                    line,
                    content,
                    rule_id="CSM001",
                    category="Maintainability",
                    severity="warning",
                    message=f"Method '{m.group(1)}' has {body_lines} lines - split into focused helpers.",  # noqa: E501
                    fix_suggestion="Extract logical chunks into private helper methods (<=30 lines each).",  # noqa: E501
                )
            )
    return out


def detect_long_file(content: str, file_path: str) -> List[Issue]:
    """CSM002: file exceeds 500 lines - split the responsibility."""
    line_count = content.count("\n") + 1
    if line_count < 500:
        return []
    return [
        _emit(
            file_path,
            1,
            content,
            rule_id="CSM002",
            category="Maintainability",
            severity="info",
            message=f"File has {line_count} lines - consider splitting into focused classes.",  # noqa: E501
            fix_suggestion="Group related members into partial classes or split into separate files.",  # noqa: E501
        )
    ]


def detect_class_god_object(content: str, file_path: str) -> List[Issue]:
    """CSM003: class with > 12 public members (methods or properties)."""
    out: List[Issue] = []
    class_re = re.compile(r"\bclass\s+(\w+)\b[^{]*\{")
    for cls in class_re.finditer(content):
        body_start = cls.end()
        depth = 1
        end = body_start
        for i in range(body_start, len(content)):
            if content[i] == "{":
                depth += 1
            elif content[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        body = content[body_start:end]
        public_members = len(re.findall(r"^\s*public\s+", body, re.MULTILINE))
        if public_members > 12:
            line = _line_number(content, cls.start())
            out.append(
                _emit(
                    file_path,
                    line,
                    content,
                    rule_id="CSM003",
                    category="Maintainability",
                    severity="warning",
                    message=f"Class '{cls.group(1)}' exposes {public_members} public members - likely a God Object.",  # noqa: E501
                    fix_suggestion="Extract cohesive subsets into focused collaborator classes.",  # noqa: E501
                )
            )
    return out


def detect_too_many_params(content: str, file_path: str) -> List[Issue]:
    """CSM004: method with > 5 parameters - bundle into a struct/options class."""
    out: List[Issue] = []
    method_re = re.compile(
        r"\b(?:public|private|protected|internal)\s+(?:static\s+|virtual\s+|override\s+|async\s+|sealed\s+)*"  # noqa: E501
        r"[\w<>,\s\[\]?]+?\s+(\w+)\s*\(([^)]*)\)\s*\{",
    )
    for m in method_re.finditer(content):
        params_raw = m.group(2).strip()
        if not params_raw:
            continue
        # Don't split on commas inside generic args like `Dictionary<string,int>`
        depth = 0
        params: List[str] = []
        last = 0
        for i, c in enumerate(params_raw):
            if c == "<":
                depth += 1
            elif c == ">":
                depth -= 1
            elif c == "," and depth == 0:
                params.append(params_raw[last:i].strip())
                last = i + 1
        params.append(params_raw[last:].strip())
        params = [p for p in params if p]
        if len(params) <= 5:
            continue
        line = _line_number(content, m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="CSM004",
                category="Maintainability",
                severity="warning",
                message=f"Method '{m.group(1)}' has {len(params)} parameters - extract a parameter object.",  # noqa: E501
                fix_suggestion="Group related parameters into a `record` or `struct`; pass that instead.",  # noqa: E501
            )
        )
    return out


def detect_deep_nesting(content: str, file_path: str) -> List[Issue]:
    """CSM005: control-flow nesting depth ≥ 4 - extract guard clauses / helpers.

    Tracks nesting depth by walking { / } while inside method bodies.
    Reports at the deepest opening brace per method when threshold is hit.
    """
    out: List[Issue] = []
    method_re = re.compile(
        r"\b(?:public|private|protected|internal)\s+(?:static\s+|virtual\s+|override\s+|async\s+|sealed\s+)*"  # noqa: E501
        r"[\w<>,\s\[\]?]+?\s+(\w+)\s*\([^)]*\)\s*\{",
    )
    for m in method_re.finditer(content):
        brace_open = m.end() - 1
        depth = 1
        max_depth = 1
        max_pos = brace_open
        for i in range(brace_open + 1, len(content)):
            c = content[i]
            if c == "{":
                depth += 1
                if depth > max_depth:
                    max_depth = depth
                    max_pos = i
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
        # max_depth counts the method body itself as level 1; control
        # nesting of 4 inside that body means max_depth == 5.
        if max_depth >= 5:
            line = _line_number(content, max_pos)
            out.append(
                _emit(
                    file_path,
                    line,
                    content,
                    rule_id="CSM005",
                    category="Maintainability",
                    severity="warning",
                    message=f"Method '{m.group(1)}' nests {max_depth - 1} levels deep - flatten with early returns or extract helpers.",  # noqa: E501
                    fix_suggestion="Replace nested if/else chains with early-return guard clauses, or move inner blocks into private methods.",  # noqa: E501
                )
            )
    return out
