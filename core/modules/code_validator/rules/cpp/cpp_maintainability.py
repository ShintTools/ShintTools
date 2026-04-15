# core/modules/code_validator/rules/cpp/cpp_maintainability.py
#
# Maintainability rules (CM) for Unreal Engine 5 C++.
# Detects code smells like long functions, deep nesting,
# duplicate includes, and leftover debug code.
#
# Rule index:
#   CM001  GEngine debug message left in code
#   CM002  Function body exceeds 80 lines
#   CM003  TODO / FIXME / HACK comments
#   CM004  File too long (> 500 lines)
#   CM005  Too many function parameters (> 5)
#   CM006  Deep nesting (> 4 levels)
#   CM007  Duplicate #include
#   CM008  Empty destructor
# Total: 8 rules

import re
from typing import List

from core.modules.code_validator.rules.cpp._cpp_helpers import (
    Issue,
    _char_pos_for_line,
    _code_part,
    _extract_class_name,
    _is_comment_line,
    _is_cpp,
    _is_fixable,
)


# CM001: GEngine debug message left in code
def detect_debug_message(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects GEngine->AddOnScreenDebugMessage calls.
    These are useful during development but must be removed
    before shipping — they cause visual noise and slight
    performance overhead in release builds.
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()
    in_block_comment = False
    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()
        if in_block_comment:
            if "*/" in source_line:
                in_block_comment = False
            continue
        if stripped.startswith("/*"):
            if "*/" not in source_line[stripped.find("/*") + 2 :]:
                in_block_comment = True
            continue
        if _is_comment_line(stripped):
            continue
        code = _code_part(source_line)
        if re.search(r"GEngine->AddOnScreenDebugMessage", code):
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": _extract_class_name(
                        content,
                        _char_pos_for_line(source_lines, line_no),
                    ),
                    "severity": "error",
                    "rule_id": "CM001",
                    "category": "Maintainability",
                    "message": (
                        "GEngine debug message left in code — "
                        "remove before shipping."
                    ),
                    "snippet": source_line.strip(),
                    "fix_suggestion": ("Remove debug message from production"),
                    "is_auto_fixable": _is_fixable("CM001"),
                }
            )
    return issues


# CM002: Function body exceeds 80 lines
def detect_long_function(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects functions whose body exceeds 80 lines.
    Long functions are hard to read, test and maintain.
    Split them into smaller functions with clear
    responsibilities.
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()
    total_lines = len(source_lines)

    func_pattern = re.compile(
        r"^\s*(?:[\w:<>*&]+\s+)+(\w+)\s*\([^;]*\)\s*"
        r"(?:const\s*)?(?:override\s*)?(?:noexcept\s*)?\{"
    )

    line_idx = 0
    while line_idx < total_lines:
        func_match = func_pattern.match(source_lines[line_idx])
        if func_match:
            func_name = func_match.group(1)
            start_line = line_idx + 1
            brace_depth = source_lines[line_idx].count("{") - source_lines[
                line_idx
            ].count("}")
            end_idx = line_idx + 1

            while end_idx < total_lines and brace_depth > 0:
                brace_depth += source_lines[end_idx].count("{") - source_lines[
                    end_idx
                ].count("}")
                end_idx += 1

            func_length = end_idx - line_idx
            if func_length > 80:
                class_name = _extract_class_name(
                    content,
                    _char_pos_for_line(source_lines, start_line),
                )
                snippet_line = (
                    source_lines[start_line - 1].strip()
                    if start_line <= len(source_lines)
                    else ""
                )
                issues.append(
                    {
                        "asset_path": file_path,
                        "line": start_line,
                        "class": class_name,
                        "severity": "warning",
                        "rule_id": "CM002",
                        "category": "Maintainability",
                        "message": (
                            f"Function '{func_name}' is "
                            f"{func_length} lines long — "
                            "split into smaller functions "
                            "(max 80)."
                        ),
                        "snippet": snippet_line,
                        "fix_suggestion": ("Extract to smaller functions"),
                        "is_auto_fixable": _is_fixable("CM002"),
                    }
                )
            line_idx = end_idx
        else:
            line_idx += 1

    return issues


# CM003: TODO / FIXME / HACK comments detected
def detect_todo_comments(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects TODO, FIXME and HACK comments left in the code.
    These indicate unfinished work or temporary workarounds
    that should be tracked and resolved before shipping.
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()
    for line_no, source_line in enumerate(source_lines, start=1):
        if re.search(
            r"//.*\b(TODO|FIXME|HACK)\b",
            source_line,
            re.IGNORECASE,
        ):
            tag_match = re.search(
                r"\b(TODO|FIXME|HACK)\b",
                source_line,
                re.IGNORECASE,
            )
            tag_found = tag_match.group(1).upper() if tag_match else "TODO"
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": _extract_class_name(
                        content,
                        _char_pos_for_line(source_lines, line_no),
                    ),
                    "severity": "info",
                    "rule_id": "CM003",
                    "category": "Maintainability",
                    "message": (
                        f"{tag_found} comment detected — "
                        "track and resolve before shipping."
                    ),
                    "snippet": source_line.strip(),
                    "fix_suggestion": ("Remove or resolve TODO comment"),
                    "is_auto_fixable": _is_fixable("CM003"),
                }
            )
    return issues


# CM004: File too long (> 500 lines)
def detect_file_too_long(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects source files exceeding the maximum line count.
    Large files are hard to navigate and usually indicate
    that a class has too many responsibilities.
    Split into smaller, focused files.
    Threshold defined in Tech Doc Section 12.1
    (max_file_lines: 500).
    """
    if not _is_cpp(file_path):
        return []

    _MAX_FILE_LINES: int = 500

    total_lines = len(content.splitlines())
    if total_lines <= _MAX_FILE_LINES:
        return []

    return [
        {
            "asset_path": file_path,
            "line": 1,
            "class": "Unknown",
            "severity": "warning",
            "rule_id": "CM004",
            "category": "Maintainability",
            "message": (
                f"File has {total_lines} lines "
                f"(max: {_MAX_FILE_LINES}) — split into "
                "smaller, focused files."
            ),
            "snippet": content.splitlines()[0].strip(),
            "fix_suggestion": ("Split file into smaller modules"),
            "is_auto_fixable": _is_fixable("CM004"),
        }
    ]


# CM005: Too many function parameters (> 5)
def detect_too_many_parameters(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects functions with more parameters than the threshold.
    Functions with many parameters are harder to call correctly,
    test and maintain. Consider passing a dedicated struct
    instead. Epic Coding Standard: 'Avoid overly-long function
    parameter lists.'
    """
    if not _is_cpp(file_path):
        return []

    _MAX_PARAMS: int = 5

    issues: List[Issue] = []
    source_lines = content.splitlines()

    func_pattern = re.compile(
        r"^\s*(?:[\w:<>*&~]+\s+)+(\w+)\s*\(([^;{}]*)\)\s*"
        r"(?:const\s*)?(?:override\s*)?(?:noexcept\s*)?"
        r"(?:\{|;)"
    )

    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()
        if stripped.startswith("//") or stripped.startswith("#"):
            continue

        func_match = func_pattern.match(source_line)
        if not func_match:
            continue

        func_name = func_match.group(1)
        param_list = func_match.group(2).strip()

        # Skip empty parameter lists and void
        if not param_list or param_list == "void":
            continue

        # Count parameters by splitting on commas, ignoring
        # commas inside template angle brackets
        depth = 0
        param_count = 1
        for char in param_list:
            if char in "<([":
                depth += 1
            elif char in ">)]":
                depth -= 1
            elif char == "," and depth == 0:
                param_count += 1

        if param_count <= _MAX_PARAMS:
            continue

        issues.append(
            {
                "asset_path": file_path,
                "line": line_no,
                "class": _extract_class_name(
                    content,
                    _char_pos_for_line(source_lines, line_no),
                ),
                "severity": "warning",
                "rule_id": "CM005",
                "category": "Maintainability",
                "message": (
                    f"Function '{func_name}' has "
                    f"{param_count} parameters "
                    f"(max: {_MAX_PARAMS}) — consider "
                    "passing a dedicated struct instead."
                ),
                "snippet": source_line.strip(),
                "fix_suggestion": ("Use parameter object pattern"),
                "is_auto_fixable": _is_fixable("CM005"),
            }
        )

    return issues


# CM006: Deep nesting (> 4 levels)
def detect_deep_nesting(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects code blocks nested more than 4 levels deep.
    Deep nesting makes code hard to read and indicates
    the function should be refactored.
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    _MAX_NESTING: int = 4
    brace_depth = 0
    reported_lines: set = set()

    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()
        if stripped.startswith("//"):
            continue

        # Count braces
        open_braces = source_line.count("{")
        close_braces = source_line.count("}")

        if open_braces > 0:
            brace_depth += open_braces
            if brace_depth > _MAX_NESTING and line_no not in reported_lines:
                reported_lines.add(line_no)
                issues.append(
                    {
                        "asset_path": file_path,
                        "line": line_no,
                        "class": _extract_class_name(
                            content,
                            _char_pos_for_line(source_lines, line_no),
                        ),
                        "severity": "warning",
                        "rule_id": "CM006",
                        "category": "Maintainability",
                        "message": (
                            f"Code nested {brace_depth} "
                            "levels deep "
                            f"(max: {_MAX_NESTING}) — "
                            "refactor to reduce complexity."
                        ),
                        "snippet": source_line.strip(),
                        "fix_suggestion": ("Reduce nesting with early " "returns"),
                        "is_auto_fixable": _is_fixable("CM006"),
                    }
                )

        brace_depth -= close_braces
        if brace_depth < 0:
            brace_depth = 0

    return issues


# CM007: Duplicate #include
def detect_duplicate_include(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects the same header included multiple times in a file.
    While pragma once prevents multiple inclusion, duplicate
    #include lines are redundant and should be cleaned up.
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()
    seen_includes: dict = {}

    for line_no, source_line in enumerate(source_lines, start=1):
        include_match = re.search(r'#include\s+[<"]([^>"]+)[>"]', source_line)
        if include_match:
            header = include_match.group(1)
            if header in seen_includes:
                issues.append(
                    {
                        "asset_path": file_path,
                        "line": line_no,
                        "class": "Unknown",
                        "severity": "info",
                        "rule_id": "CM007",
                        "category": "Maintainability",
                        "message": (
                            f"Duplicate #include '{header}'"
                            " — already included on line "
                            f"{seen_includes[header]}."
                        ),
                        "snippet": source_line.strip(),
                        "fix_suggestion": ("Remove duplicate #include"),
                        "is_auto_fixable": _is_fixable("CM007"),
                    }
                )
            else:
                seen_includes[header] = line_no

    return issues


# CM008: Empty destructor
def detect_empty_destructor(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects empty destructor implementations. If a destructor
    has no cleanup logic, it can be removed or defaulted
    unless it needs to be virtual.
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    for line_no, source_line in enumerate(source_lines, start=1):
        # Match: ~ClassName() { } or ~ClassName()\n{\n}
        if re.search(r"~\w+\s*\(\s*\)\s*\{\s*\}", source_line):
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": _extract_class_name(
                        content,
                        _char_pos_for_line(source_lines, line_no),
                    ),
                    "severity": "info",
                    "rule_id": "CM008",
                    "category": "Maintainability",
                    "message": (
                        "Empty destructor — remove or use "
                        "'= default' unless it must be "
                        "virtual."
                    ),
                    "snippet": source_line.strip(),
                    "fix_suggestion": ("Use = default for empty destructor"),
                    "is_auto_fixable": _is_fixable("CM008"),
                }
            )

    return issues
