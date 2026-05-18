# core/modules/code_validator/rules/cpp/_cpp_helpers.py
#
# Shared helper functions and constants for C++ rules.
# This module provides common utilities for C++ file analysis and validation
# used across all C++ rule categories (Performance, Best Practices, Security,
# Maintainability).

import re
from pathlib import Path
from typing import Dict

try:
    from code_validator.unreal.parsers.fixers.cpp_fixer import CppFixer
    from code_validator.unreal.parsers.fixers.fix_patterns import RULE_TO_PATTERN
except ModuleNotFoundError:
    RULE_TO_PATTERN = {}
    CppFixer = None  # type: ignore[assignment,misc]

__all__ = [
    "CppFixer",
    "RULE_TO_PATTERN",
    "Issue",
    "_fixer",
    "_CPP_EXT",
    "_is_cpp",
    "_is_header",
    "_is_source",
    "_code_part",
    "_is_comment_line",
    "_extract_class_name",
    "_get_line_number",
    "_char_pos_for_line",
    "_is_fixable",
]

try:
    _fixer: "CppFixer | None" = CppFixer() if CppFixer is not None else None
except Exception:
    # tree-sitter runtime init can fail (version mismatch, missing lib, etc.)
    # Rules still work without the fixer — auto-fix just won't be available.
    _fixer = None

# Type alias for issue dictionary
Issue = Dict

# ── CONSTANTS ─────────────────────────────────────────

# Extensions considered C++ files
_CPP_EXT = {".cpp", ".h", ".hpp", ".cc"}

# ── HELPER FUNCTIONS ──────────────────────────────────


def _is_cpp(file_path: str) -> bool:
    """Returns True if the file is any kind of C++ file."""
    return Path(file_path).suffix.lower() in _CPP_EXT


def _is_header(file_path: str) -> bool:
    """Returns True if the file is a C++ header."""
    return Path(file_path).suffix.lower() in {".h", ".hpp"}


def _is_source(file_path: str) -> bool:
    """Returns True if the file is a C++ source file."""
    return Path(file_path).suffix.lower() in {".cpp", ".cc"}


def _code_part(line: str) -> str:
    """Return the code-only portion of a line, stripping trailing // comments.

    Uses a simple scan that skips characters inside double-quoted strings so
    a // sequence inside a string literal is not treated as a comment.
    Covers ~99% of real UE5 code without full lexer complexity.
    """
    in_str = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == '"' and (i == 0 or line[i - 1] != "\\"):
            in_str = not in_str
        if not in_str and ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
            return line[:i]
        i += 1
    return line


def _is_comment_line(stripped: str) -> bool:
    """Return True if the stripped line is a pure comment (starts with // or *)."""
    return (
        stripped.startswith("//")
        or stripped.startswith("*")
        or stripped.startswith("/*")
    )


def _extract_class_name(content: str, pos: int) -> str:
    """
    Extracts the UE5 class name from the nearest function
    signature before position pos in the content.
    Looks for pattern: ReturnType AClassName::FunctionName
    Returns 'Unknown' if no class signature is found.
    """
    snippet = content[:pos]
    class_matches = re.findall(r"\b([A-Z]\w+)::\w+\s*\(", snippet)
    return class_matches[-1] if class_matches else "Unknown"


def _get_line_number(content: str, pos: int) -> int:
    """
    Returns the 1-indexed line number for a character
    position in the content string.
    """
    return content[:pos].count("\n") + 1


def _char_pos_for_line(lines: list, line_no: int) -> int:
    """
    Returns the character position in the full content
    for the start of line_no (1-indexed).
    Used to extract class name for line-by-line rules.
    """
    return sum(len(line) + 1 for line in lines[: line_no - 1])


def _is_fixable(rule_id: str) -> bool:
    """Check if a rule has a real auto-fix pattern."""
    if rule_id not in RULE_TO_PATTERN:
        return False
    pattern_name = RULE_TO_PATTERN[rule_id][0]
    return pattern_name != "mark_for_review"
