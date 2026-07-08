# core/modules/code_validator/rules/csharp/_csharp_helpers.py
#
# Minimal fixer + pattern map for C# / Unity rules. Mirrors the cpp
# helper module but only supports line-level transformations for now —
# AST-aware fixes via tree-sitter-c-sharp will land in a follow-up
# release once we add the dependency to the core engine image.
#
# The three patterns covered are language-agnostic (they work on raw
# text + line numbers):
#
#   mark_for_review  — insert a `// [SHINTTOOLS REVIEW] reason` line
#                      above the issue line. Used as the universal
#                      fallback so context_after is never empty for an
#                      auto-fixable rule.
#   replace_text     — swap a literal substring on the issue line.
#                      Used by UN006 (public -> [SerializeField] private).
#   delete_line      — drop the issue line entirely. Used by UN004
#                      (Debug.Log in Update).
#
# The csharp orchestrator imports _fixer + CSHARP_RULE_TO_PATTERN and
# uses them the same way cpp_orchestrator does — line-slicing for
# context_before, fixer.fix() for context_after.

import re
from typing import Dict, List, Optional, Tuple, Union

__all__ = [
    "CSharpFixer",
    "CSHARP_RULE_TO_PATTERN",
    "Issue",
    "_fixer",
    "_line_number",
    "_line_text",
    "_find_method_body",
    "_update_body",
    "_emit",
    "_AUTO_FIXABLE",
]

Issue = Dict

# ── Rule → fix pattern map ───────────────────────────────────────────
#
# Each entry routes a rule_id to a pattern handler + parameter. Rules
# absent from this map fall through to mark_for_review at orchestrator
# level so the AFTER panel of Preview is never blank.

CSHARP_RULE_TO_PATTERN: Dict[str, Tuple[str, Union[str, Tuple[str, str], None]]] = {
    # UN006 — public field on MonoBehaviour. Idiomatic Unity is to
    # use [SerializeField] private so the field stays serialised but
    # callers can't mutate it without going through a property.
    "UN006": (
        "replace_text",
        ("public ", "[SerializeField] private "),
    ),
    # UN004 — Debug.Log in Update is a per-frame hot-path waste.
    # Drop the offending line entirely. The marker keeps us safe
    # against detector regexes that anchor on `^\s*Debug.` and
    # therefore return a slightly off line number.
    "UN004": ("delete_line", "Debug."),
    # CSB002 — TODO comment. Flag for manual review; the marker
    # gives the developer a Ctrl+F handle to find the spot later.
    "CSB002": (
        "mark_for_review",
        "Resolve the TODO before merging — leftover TODOs leak into prod.",
    ),
}


# ── Detector helpers ─────────────────────────────────────────────────
#
# Shared by every csharp rule module. Moved out of the old monolithic
# csharp_rules.py during the split into category files; logic unchanged.


def _line_number(content: str, offset: int) -> int:
    return content.count("\n", 0, offset) + 1


def _line_text(content: str, line_no: int) -> str:
    lines = content.splitlines()
    return lines[line_no - 1].strip() if 0 < line_no <= len(lines) else ""


def _find_method_body(
    content: str, signature_re: str
) -> Optional[tuple[int, int, int]]:
    """Locate a method matching `signature_re` and return (body_start,
    body_end, signature_line). Body span is the inside-of-braces region
    (exclusive of the outer { }). Returns None when not found or the body
    is not a single brace-balanced block."""
    m = re.search(signature_re, content)
    if not m:
        return None
    brace_open = content.find("{", m.end())
    if brace_open < 0:
        return None
    depth = 0
    for i in range(brace_open, len(content)):
        c = content[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return brace_open + 1, i, _line_number(content, m.start())
    return None


def _update_body(content: str) -> Optional[tuple[int, int]]:
    """Return the inside-of-braces span of the first Update / LateUpdate /
    FixedUpdate method in `content`. Unity polls all three identically,
    so for "X in Update" rules we treat them as one. Returns (start, end)
    as content slice indices, or None when no such method exists."""
    sig_re = r"\b(?:private|public|protected|internal)?\s*void\s+(?:Update|LateUpdate|FixedUpdate)\s*\(\s*\)"  # noqa: E501
    span = _find_method_body(content, sig_re)
    if not span:
        return None
    return span[0], span[1]


# Rules whose detectors fire issues that the line-level CSharpFixer
# can transform (replace_text / delete_line / mark_for_review). Adding
# a rule_id here flips `is_auto_fixable` on for the wire payload so the
# Unity plugin renders the AUTO badge, the per-row Apply button, and
# pulls context_after from the orchestrator's fixer pass.
#
# Keep this in sync with CSHARP_RULE_TO_PATTERN below:
# every entry here MUST have a pattern handler, otherwise the
# orchestrator falls through to mark_for_review which still produces
# a usable diff but isn't a real auto-fix.
_AUTO_FIXABLE: set[str] = {
    "UN004",  # delete_line  — Debug.Log inside Update
    "UN006",  # replace_text — public field on MonoBehaviour
    "CSB002",  # mark_for_review — TODO comment
}


def _emit(
    file_path: str,
    line_no: int,
    content: str,
    *,
    rule_id: str,
    category: str,
    severity: str,
    message: str,
    fix_suggestion: str,
) -> Issue:
    return {
        "asset_path": file_path,
        "line": line_no,
        "severity": severity,
        "rule_id": rule_id,
        "category": category,
        "message": message,
        "snippet": _line_text(content, line_no),
        "fix_suggestion": fix_suggestion,
        "is_auto_fixable": rule_id in _AUTO_FIXABLE,
    }


class CSharpFixer:
    """Line-level fixer for C# rules. AST-free, mirrors a strict subset
    of CppFixer so the csharp orchestrator can compute context_after
    without depending on tree-sitter-c-sharp.
    """

    def fix(
        self,
        rule_id: str,
        code: str,
        line_number: Optional[int] = None,
    ) -> Tuple[str, str, List[str]]:
        if rule_id not in CSHARP_RULE_TO_PATTERN:
            return code, "", [f"No pattern for {rule_id}"]
        entry = CSHARP_RULE_TO_PATTERN[rule_id]
        name, param = entry

        if name == "mark_for_review" and line_number is not None:
            reason = param if isinstance(param, str) else "Manual review required"
            return self._apply_mark_for_review(code, line_number, reason)

        if name == "replace_text" and line_number is not None:
            if isinstance(param, tuple):
                old_text, new_text = param
            else:
                old_text, new_text = (param if isinstance(param, str) else ""), ""
            return self._apply_replace_text(code, line_number, old_text, new_text)

        if name == "delete_line" and line_number is not None:
            marker = param if isinstance(param, str) else None
            return self._apply_delete_line(code, line_number, marker)

        return code, "", [f"Unsupported pattern '{name}' for {rule_id}"]

    # ── Line-level handlers ──────────────────────────────────────────

    def _apply_mark_for_review(
        self,
        code: str,
        line_number: int,
        reason: str,
    ) -> Tuple[str, str, List[str]]:
        """Insert a `// [SHINTTOOLS REVIEW] reason` comment above the
        issue line, preserving indentation. The Preview UI renders the
        marker above the original line so the user sees both the rule
        and the action in one window.
        """
        lines = code.split("\n")
        idx = line_number - 1
        if idx < 0 or idx >= len(lines):
            return code, "", ["Invalid line number"]
        target = lines[idx]
        indent = " " * (len(target) - len(target.lstrip()))
        lines.insert(idx, f"{indent}// [SHINTTOOLS REVIEW] {reason}")
        return (
            "\n".join(lines),
            "",
            [f"Line {line_number}: marked for review - {reason}"],
        )

    def _apply_replace_text(
        self,
        code: str,
        line_number: int,
        old_text: str,
        new_text: str,
    ) -> Tuple[str, str, List[str]]:
        """Swap the FIRST occurrence of `old_text` near `line_number`.
        We scan the issue line plus the two surrounding lines because
        detectors that anchor on `^\\s*pattern` regexes can return the
        line where the matching `\\n` lives (one off the real source
        line). Returns the original code untouched when the substring
        isn't anywhere in the small search window — the orchestrator
        then routes to mark_for_review so the AFTER panel still
        renders something.
        """
        lines = code.split("\n")
        idx = line_number - 1
        if idx < 0 or idx >= len(lines):
            return code, "", ["Invalid line number"]

        # Scan idx, idx+1, idx-1, idx+2, idx-2 in that order. The vast
        # majority of detectors point at the right line; the others are
        # off by exactly one due to the regex-anchor edge case above.
        for offset in (0, 1, -1, 2, -2):
            j = idx + offset
            if 0 <= j < len(lines) and old_text in lines[j]:
                lines[j] = lines[j].replace(old_text, new_text, 1)
                return (
                    "\n".join(lines),
                    "",
                    [f"Line {j + 1}: replaced '{old_text}' -> '{new_text}'"],
                )
        return code, "", [f"'{old_text}' not on lines {line_number}±2"]

    @staticmethod
    def _statement_end(lines: List[str], start: int) -> int:
        """Index of the last line of the statement starting at `start`.

        When the start line opens a paren that doesn't close on the same line
        (a multi-line `Debug.Log($"...",\n  arg);` call), walk forward until
        the parens balance and the line ends with `;`. A self-contained line
        returns `start`. Mirrors CppFixer so deleting a multi-line statement
        never orphans its continuation lines into code that won't compile.
        """
        depth = lines[start].count("(") - lines[start].count(")")
        if depth <= 0:
            return start
        for j in range(start + 1, min(start + 25, len(lines))):
            depth += lines[j].count("(") - lines[j].count(")")
            if depth <= 0 and lines[j].rstrip().endswith(";"):
                return j
        return start  # boundary not found — delete only the start line

    def _apply_delete_line(
        self,
        code: str,
        line_number: int,
        marker: Optional[str] = None,
    ) -> Tuple[str, str, List[str]]:
        """Remove the full statement on the issue line (or the closest line
        containing `marker` within ±2 of `line_number`). When `marker` is
        None, the statement at the exact `line_number` is deleted.

        A multi-line call (e.g. a wrapped `Debug.Log(...)`) is removed whole;
        popping only its first line would orphan the argument lines.
        """
        lines = code.split("\n")
        idx = line_number - 1
        if idx < 0 or idx >= len(lines):
            return code, "", ["Invalid line number"]

        start = idx
        if marker:
            for offset in (0, 1, -1, 2, -2):
                j = idx + offset
                if 0 <= j < len(lines) and marker in lines[j]:
                    start = j
                    break
            else:
                return code, "", [f"marker '{marker}' not on lines {line_number}±2"]

        end = self._statement_end(lines, start)
        deleted = "\n".join(lines[start : end + 1]).strip()
        del lines[start : end + 1]
        return (
            "\n".join(lines),
            "",
            [f"Line {start + 1}: deleted ({deleted[:80]!r})"],
        )


# Module-level singleton — matches the cpp helper pattern. Cheap to
# construct (no state besides method dispatch), so we never bother
# wrapping it in a lazy property.
_fixer: CSharpFixer = CSharpFixer()
