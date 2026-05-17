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

from typing import Dict, List, Optional, Tuple, Union

__all__ = [
    "CSharpFixer",
    "CSHARP_RULE_TO_PATTERN",
    "Issue",
    "_fixer",
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

    def _apply_delete_line(
        self,
        code: str,
        line_number: int,
        marker: Optional[str] = None,
    ) -> Tuple[str, str, List[str]]:
        """Remove the issue line (or the closest line containing `marker`
        within ±2 of `line_number`). When `marker` is None, the line at
        the exact `line_number` is deleted unconditionally.
        """
        lines = code.split("\n")
        idx = line_number - 1
        if idx < 0 or idx >= len(lines):
            return code, "", ["Invalid line number"]

        if marker:
            for offset in (0, 1, -1, 2, -2):
                j = idx + offset
                if 0 <= j < len(lines) and marker in lines[j]:
                    deleted = lines.pop(j)
                    return (
                        "\n".join(lines),
                        "",
                        [f"Line {j + 1}: deleted ({deleted.strip()!r})"],
                    )
            return code, "", [f"marker '{marker}' not on lines {line_number}±2"]

        deleted = lines.pop(idx)
        return (
            "\n".join(lines),
            "",
            [f"Line {line_number}: deleted ({deleted.strip()!r})"],
        )


# Module-level singleton — matches the cpp helper pattern. Cheap to
# construct (no state besides method dispatch), so we never bother
# wrapping it in a lazy property.
_fixer: CSharpFixer = CSharpFixer()
