"""C# (Unity) fixer Apply-safety regression tests.

Parity with the C++ marketplace-review hardening: the line-level delete_line
fix must remove a WHOLE multi-line statement (e.g. a wrapped Debug.Log) rather
than only its first line, which would orphan the argument lines into code that
does not compile.
"""

import sys
from pathlib import Path

_CORE = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, _CORE)
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "modules"))

from code_validator.unity.csharp._csharp_helpers import CSharpFixer  # noqa: E402

_FIXER = CSharpFixer()


class TestCSharpDeleteLineSafety:
    def test_removes_whole_multiline_debug_log(self):
        code = (
            "void Update()\n"
            "{\n"
            "    Debug.Log(\n"
            '        $"health {health} at "\n'
            '        + transform.position);\n'
            "    Keep();\n"
            "}"
        )
        fixed, _, _ = _FIXER.fix("UN004", code, line_number=3)
        assert "Debug.Log" not in fixed
        assert "transform.position);" not in fixed  # continuation not orphaned
        assert "Keep();" in fixed  # following statement untouched

    def test_single_line_deletes_only_that_statement(self):
        code = (
            "void Update()\n"
            "{\n"
            '    Debug.Log("tick");\n'
            "    DoWork();\n"
            "}"
        )
        fixed, _, _ = _FIXER.fix("UN004", code, line_number=3)
        assert "Debug.Log" not in fixed
        assert "DoWork();" in fixed

    def test_marker_finds_line_within_window(self):
        # Detector points one line above the actual Debug. line; the marker
        # scan still finds it and removes the whole statement.
        code = (
            "void Update()\n"
            "{\n"
            '    Debug.Log("x");\n'
            "    Other();\n"
            "}"
        )
        fixed, _, _ = _FIXER.fix("UN004", code, line_number=2)
        assert "Debug.Log" not in fixed
        assert "Other();" in fixed
