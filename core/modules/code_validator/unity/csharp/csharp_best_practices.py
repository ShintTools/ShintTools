# core/modules/code_validator/rules/csharp/csharp_best_practices.py
#
# C# / Unity best-practice rule detectors - CSB001-CSB034 (14 implemented).
#
# CSB001  Empty catch block
# CSB002  TODO / FIXME / HACK comment
# CSB003  catch (Exception) without rethrow or logging
# CSB004  Infinite loop without break/return
# CSB005  async void method
# CSB006  Magic number literal
# CSB009  Unity lifecycle method missing override
# CSB010  Hardcoded absolute path
# CSB011  Empty if body
# CSB012  event += without matching -= in OnDestroy
# CSB013  Debug.Log outside #if UNITY_EDITOR guard
# CSB014  float assigned a double literal (missing f suffix)
# CSB015  Empty destructor/finalizer
# CSB016  Commented-out code block
# Total: 14 rules

from __future__ import annotations

import re
from typing import List

from code_validator.unity.csharp._csharp_helpers import (
    Issue,
    _emit,
    _find_method_body,
    _line_number,
)


def detect_empty_catch(content: str, file_path: str) -> List[Issue]:
    """CSB001: empty catch block swallows exceptions silently."""
    out: List[Issue] = []
    for m in re.finditer(r"\bcatch\b[^{]*\{(\s*)\}", content):
        # Body is the captured whitespace - empty if it's only whitespace.
        if m.group(1).strip():
            continue
        line = _line_number(content, m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="CSB001",
                category="BestPractices",
                severity="warning",
                message="Empty catch block silently swallows the exception.",
                fix_suggestion="Log the exception (Debug.LogException) or rethrow with `throw;`.",  # noqa: E501
            )
        )
    return out


def detect_todo_comment(content: str, file_path: str) -> List[Issue]:
    """CSB002: TODO / FIXME / HACK markers in source - flag for review."""
    out: List[Issue] = []
    for m in re.finditer(r"//\s*(TODO|FIXME|HACK|XXX)\b[^\n]*", content):
        line = _line_number(content, m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="CSB002",
                category="BestPractices",
                severity="info",
                message=f"{m.group(1)} comment - flag for follow-up.",
                fix_suggestion="Convert to a tracked ticket or resolve before merging.",
            )
        )
    return out


def detect_catch_exception_broad(content: str, file_path: str) -> List[Issue]:
    """CSB003: `catch (Exception)` without filter - swallows specific errors.

    Allowed when the catch body either rethrows (`throw;`) or logs the
    exception (`LogException` / `LogError` / `Console.WriteLine`). Anything
    else is considered overly broad and worth flagging.
    """
    out: List[Issue] = []
    # No \{ at end — use find() so inline comments between ) and { don't
    # break the match (e.g. `catch (Exception e) // note\n{`).
    pattern = re.compile(r"\bcatch\s*\(\s*(?:System\.)?Exception\s+(\w+)\s*\)")
    for m in pattern.finditer(content):
        brace = content.find("{", m.end())
        if brace < 0:
            continue
        depth = 1
        end = brace
        for i in range(brace + 1, len(content)):
            if content[i] == "{":
                depth += 1
            elif content[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        body = content[brace + 1 : end]
        rethrows = re.search(r"\bthrow\s*[;(]", body)
        logged = re.search(
            r"\b(?:Log(?:Exception|Error|Warning)|Console\.(?:Write|Error))\b", body
        )
        if rethrows or logged:
            continue
        line = _line_number(content, m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="CSB003",
                category="BestPractices",
                severity="warning",
                message="`catch (Exception)` without rethrow or logging - masks bugs.",
                fix_suggestion="Catch a specific exception type, or `Debug.LogException(ex)` and rethrow.",  # noqa: E501
            )
        )
    return out


def detect_infinite_loop(content: str, file_path: str) -> List[Issue]:
    """CSB004: while(true) or for(;;) without break/return/goto - hangs the game thread."""  # noqa: E501
    out: List[Issue] = []
    # No \{ at end — use find() so inline comments between ) and { don't
    # break the match (e.g. `while (true) // note\n{`).
    loop_re = re.compile(r"\b(?:while\s*\(\s*true\s*\)|for\s*\(\s*;\s*;\s*\))")
    for loop in loop_re.finditer(content):
        brace_open = content.find("{", loop.end())
        if brace_open < 0:
            continue
        depth, end = 1, brace_open
        for i in range(brace_open + 1, len(content)):
            if content[i] == "{":
                depth += 1
            elif content[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        body = content[brace_open + 1 : end]
        if re.search(r"\b(?:break|return|goto|throw)\b", body):
            continue
        line = _line_number(content, loop.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="CSB004",
                category="BestPractices",
                severity="error",
                message="Infinite loop without break/return - will hang the game thread if reached on the main thread.",  # noqa: E501
                fix_suggestion="Add a termination condition, or convert to a Coroutine with a loop condition and `yield return null`.",  # noqa: E501
            )
        )
    return out


def detect_async_void(content: str, file_path: str) -> List[Issue]:
    """CSB005: `async void` method - exceptions crash the process.

    The single justified case is event handlers (signature ends in
    `(object sender, EventArgs e)` or names starting with `On…`). Plain
    async void methods are unobservable failure points.
    """
    out: List[Issue] = []
    pattern = re.compile(
        r"\b(?:public|private|protected|internal)\s+(?:static\s+)?async\s+void\s+(\w+)\s*\(([^)]*)\)",  # noqa: E501
    )
    for m in pattern.finditer(content):
        name = m.group(1)
        params = m.group(2)
        is_event_handler = (
            name.startswith("On")
            or "EventArgs" in params
            or re.search(r"\bsender\b", params)
        )
        if is_event_handler:
            continue
        line = _line_number(content, m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="CSB005",
                category="BestPractices",
                severity="warning",
                message=f"async void method '{name}' - uncaught exceptions crash the process.",  # noqa: E501
                fix_suggestion="Return `async Task` (or `async UniTask` in Unity) so callers can await and observe errors.",  # noqa: E501
            )
        )
    return out


def detect_magic_number(content: str, file_path: str) -> List[Issue]:
    """CSB006: magic number literal in expression.

    Flags integer / float literals >2 that appear in expressions but not
    in declarations (`= 5;`), array indices `[0]/[1]`, or single-digit
    loop bounds. Skips obvious enumerations (0/1/-1).
    """
    out: List[Issue] = []
    # Scan each line; skip lines that look like declarations.
    for idx, line_text in enumerate(content.splitlines(), start=1):
        stripped = line_text.strip()
        if not stripped or stripped.startswith("//"):
            continue
        # Skip declarations and obvious initialisers.
        if re.search(r"\b(?:const|static\s+readonly|readonly|enum)\b", stripped):
            continue
        if re.match(
            r"^\s*(?:public|private|protected|internal)?\s*[\w<>?,\[\]\s]+=\s*[\d.\-+e]+\s*[;,]",  # noqa: E501
            stripped,
        ):
            continue
        # Look for numeric literals in expressions.
        for num in re.finditer(
            r"(?<![\w.])-?\d+(?:\.\d+)?[fFdDmM]?(?![\w.])", stripped
        ):
            val = num.group(0).rstrip("fFdDmM")
            try:
                f = float(val)
            except ValueError:
                continue
            if abs(f) <= 2:  # 0, 1, 2, -1 are common, skip
                continue
            # Skip if the number is the immediate RHS of `=` (assignment-init)
            preceding = stripped[: num.start()].rstrip()
            if preceding.endswith("="):
                continue
            # Skip array indices like `[5]` or `[i + 5]` where the number is small
            if (
                preceding.endswith("[")
                or "[" in preceding[-10:]
                and "]" not in preceding[-10:]
            ):
                # Inside brackets - small literal indices are typical
                if abs(f) < 10:
                    continue
            out.append(
                _emit(
                    file_path,
                    idx,
                    content,
                    rule_id="CSB006",
                    category="BestPractices",
                    severity="info",
                    message=f"Magic number {val} in expression - extract to a named constant.",  # noqa: E501
                    fix_suggestion=f"Replace with `private const float MyMeaningfulName = {val};` (or appropriate type).",  # noqa: E501
                )
            )
            break  # one issue per line keeps the report compact
    return out


def detect_missing_override(content: str, file_path: str) -> List[Issue]:
    """CSB009: Unity lifecycle method declared without override in a derived class - silently shadows the base."""  # noqa: E501
    _LIFECYCLE = frozenset(
        {
            "Start",
            "Awake",
            "OnEnable",
            "OnDisable",
            "OnDestroy",
            "Update",
            "LateUpdate",
            "FixedUpdate",
            "OnApplicationQuit",
        }
    )
    out: List[Issue] = []
    cls_re = re.compile(r"class\s+\w+\s*:\s*([^{\n,]+)")
    for cls_m in cls_re.finditer(content):
        base = cls_m.group(1).strip()
        if base in {"MonoBehaviour", "ScriptableObject", "NetworkBehaviour"}:
            continue
        method_re = re.compile(
            r"^\s*(?:public|private|protected|internal)?\s+void\s+("
            + "|".join(_LIFECYCLE)
            + r")\s*\(\s*\)",
            re.MULTILINE,
        )
        for m in method_re.finditer(content, cls_m.end()):
            line_start = content.rfind("\n", 0, m.start()) + 1
            line_end = content.find("\n", m.start())
            line_src = content[line_start:line_end]
            if "override" in line_src or "virtual" in line_src:
                continue
            line = _line_number(content, m.start())
            out.append(
                _emit(
                    file_path,
                    line,
                    content,
                    rule_id="CSB009",
                    category="BestPractices",
                    severity="warning",
                    message=f"{m.group(1)}() shadows the base class implementation - add `override` to be explicit.",  # noqa: E501
                    fix_suggestion=f"Change to `protected override void {m.group(1)}()` and add `base.{m.group(1)}();`.",  # noqa: E501
                )
            )
    return out


def detect_hardcoded_path(content: str, file_path: str) -> List[Issue]:
    """CSB010: hardcoded absolute file-system path - breaks on other machines and platforms."""  # noqa: E501
    out: List[Issue] = []
    for m in re.finditer(
        r'"(?:'
        r'[A-Za-z]:\\[^"\\]{3,}'  # Windows absolute: C:\...
        r'|/(?:home|Users|var|tmp|opt)/[^"]{3,}'  # Unix absolute: /home/...
        r'|Assets/[^"]{3,}'  # Unity project-relative: Assets/...
        r')"',
        content,
    ):
        line = _line_number(content, m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="CSB010",
                category="BestPractices",
                severity="warning",
                message="Hardcoded absolute path - will not work on other machines or platforms.",  # noqa: E501
                fix_suggestion="Use Application.dataPath, Application.persistentDataPath, or Path.Combine with relative segments.",  # noqa: E501
            )
        )
    return out


def detect_empty_if_body(content: str, file_path: str) -> List[Issue]:
    """CSB011: empty if body {} - likely a logic error or unfinished branch."""
    out: List[Issue] = []
    # Use find() for { so inline comments between ) and { don't break the
    # match (e.g. `if (cond) // note\n{\n}`). Then scan for empty body.
    cond_re = re.compile(r"\bif\s*\([^)]+\)")
    for m in cond_re.finditer(content):
        brace_open = content.find("{", m.end())
        if brace_open < 0:
            continue
        brace_close = content.find("}", brace_open + 1)
        if brace_close < 0:
            continue
        body = content[brace_open + 1 : brace_close]
        if body.strip():
            continue
        line = _line_number(content, m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="CSB011",
                category="BestPractices",
                severity="warning",
                message="Empty if body - likely an unfinished branch or accidental semicolon.",  # noqa: E501
                fix_suggestion="Add the intended code, invert the condition to remove dead branches, or delete the if block.",  # noqa: E501
            )
        )
    return out


def detect_event_not_unsubscribed(content: str, file_path: str) -> List[Issue]:
    """CSB012: event += subscription without matching -= in OnDestroy - listener memory leak."""  # noqa: E501
    subscriptions: List[tuple] = []
    for m in re.finditer(r"(\w+)\s*\+=\s*\w+\s*;", content):
        event_name = m.group(1)
        if event_name.lower() in {
            "onclick",
            "onvaluechanged",
            "onendedit",
            "ontrigger",
        }:
            continue
        subscriptions.append((event_name, _line_number(content, m.start())))
    if not subscriptions:
        return []
    ondestroy_span = _find_method_body(
        content, r"\b(?:override\s+)?void\s+OnDestroy\s*\(\s*\)"
    )
    ondestroy_body = (
        content[ondestroy_span[0] : ondestroy_span[1]] if ondestroy_span else ""
    )
    out: List[Issue] = []
    for event_name, sub_line in subscriptions:
        if re.search(rf"\b{re.escape(event_name)}\s*-=\s*\w+", ondestroy_body):
            continue
        out.append(
            _emit(
                file_path,
                sub_line,
                content,
                rule_id="CSB012",
                category="BestPractices",
                severity="warning",
                message=f"Event `{event_name} +=` has no matching `-=` in OnDestroy - listener leak.",  # noqa: E501
                fix_suggestion=f"In OnDestroy: `{event_name} -= <HandlerName>;`",
            )
        )
    return out


def detect_log_outside_editor_guard(content: str, file_path: str) -> List[Issue]:
    """CSB013: Debug.Log outside #if UNITY_EDITOR guard - active in production builds."""  # noqa: E501
    out: List[Issue] = []
    in_guard = False
    for idx, raw_line in enumerate(content.splitlines(), start=1):
        stripped = raw_line.strip()
        if re.match(r"#\s*if\s+(?:UNITY_EDITOR|DEBUG)\b", stripped):
            in_guard = True
        elif re.match(r"#\s*endif\b", stripped):
            in_guard = False
        if in_guard:
            continue
        if re.search(
            r"\bDebug\.(?:Log|LogWarning|LogError|LogFormat|LogException)\s*\(",
            stripped,
        ):
            out.append(
                _emit(
                    file_path,
                    idx,
                    content,
                    rule_id="CSB013",
                    category="BestPractices",
                    severity="info",
                    message="Debug.Log is active in production builds - wrap in #if UNITY_EDITOR or remove.",  # noqa: E501
                    fix_suggestion="#if UNITY_EDITOR\n    Debug.Log(...);\n#endif",
                )
            )
    return out


def detect_float_no_f_suffix(content: str, file_path: str) -> List[Issue]:
    """CSB014: float variable assigned a double literal (missing f suffix) - implicit narrowing conversion."""  # noqa: E501
    out: List[Issue] = []
    for m in re.compile(
        r"\bfloat\s+\w+\s*=\s*-?\d+\.\d+(?![fFdDmM\d])", re.MULTILINE
    ).finditer(content):
        line = _line_number(content, m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="CSB014",
                category="BestPractices",
                severity="info",
                message="Float assigned a double literal (missing `f` suffix) - implicit narrowing conversion.",  # noqa: E501
                fix_suggestion="Append `f` to the literal (e.g. `1.5` → `1.5f`).",
            )
        )
    return out


def detect_empty_destructor(content: str, file_path: str) -> List[Issue]:
    """CSB015: empty destructor/finalizer - registers for GC finalization queue with no benefit."""  # noqa: E501
    out: List[Issue] = []
    for m in re.finditer(r"~\s*\w+\s*\(\s*\)\s*\{(\s*)\}", content):
        if m.group(1).strip():
            continue
        line = _line_number(content, m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="CSB015",
                category="BestPractices",
                severity="warning",
                message="Empty destructor/finalizer registers the object for the finalization queue with no benefit, delaying GC collection.",  # noqa: E501
                fix_suggestion="Delete the empty destructor; use IDisposable + GC.SuppressFinalize(this) if cleanup is needed.",  # noqa: E501
            )
        )
    return out


def detect_commented_out_code(content: str, file_path: str) -> List[Issue]:
    """CSB016: three or more consecutive commented-out code lines - dead code clutters the file."""  # noqa: E501
    out: List[Issue] = []
    lines = content.splitlines()
    code_re = re.compile(r"^\s*//\s*(?:[a-z_]|[A-Z].*[;{}()=])")
    run_start = -1
    run_count = 0

    def _flush(start: int, count: int) -> None:
        if count >= 3:
            out.append(
                _emit(
                    file_path,
                    start + 1,
                    content,
                    rule_id="CSB016",
                    category="Maintainability",
                    severity="info",
                    message=f"{count} consecutive commented-out code lines - remove dead code.",  # noqa: E501
                    fix_suggestion="Delete the commented block; use version control to recover old code.",  # noqa: E501
                )
            )

    for i, raw_line in enumerate(lines):
        if code_re.match(raw_line):
            if run_start < 0:
                run_start = i
            run_count += 1
        else:
            _flush(run_start, run_count)
            run_start = -1
            run_count = 0
    _flush(run_start, run_count)
    return out
