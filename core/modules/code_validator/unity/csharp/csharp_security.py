# core/modules/code_validator/rules/csharp/csharp_security.py
#
# C# / Unity security rule detectors — CSS001-CSS013 (9 implemented).
#
# CSS001  SQL command built by string concatenation
# CSS002  Hardcoded secret literal
# CSS003  Hardcoded http:// URL
# CSS004  PlayerPrefs storing credentials
# CSS005  Instantiate result used without null check
# CSS006  GetComponent result used without null check
# CSS007  Direct cast without null/type check
# CSS008  Division by variable without zero check
# CSS009  Collision/trigger handler without null check
# Total: 9 rules

from __future__ import annotations

import re
from typing import List

from code_validator.unity.csharp._csharp_helpers import (
    Issue,
    _emit,
    _find_method_body,
    _line_number,
)


def detect_sql_concat(content: str, file_path: str) -> List[Issue]:
    """CSS001: SQL command built by string concatenation — injection risk."""
    out: List[Issue] = []
    pattern = re.compile(
        r"(?:SqlCommand|MySqlCommand|SqliteCommand|new\s+\w*Command)\s*\([^)]*\+[^)]*\)",  # noqa: E501
        re.IGNORECASE,
    )
    for m in pattern.finditer(content):
        line = _line_number(content, m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="CSS001",
                category="Security",
                severity="error",
                message="SQL command built with string concatenation — SQL injection risk.",  # noqa: E501
                fix_suggestion="Use parameterised queries with `cmd.Parameters.AddWithValue(...)`.",  # noqa: E501
            )
        )
    return out


def detect_hardcoded_secret(content: str, file_path: str) -> List[Issue]:
    """CSS002: literal credentials in source (password = \"...\", api_key = \"...\")."""
    out: List[Issue] = []
    pattern = re.compile(
        r"\b(password|passwd|api[_-]?key|secret|token|bearer)\s*=\s*\"[^\"]{6,}\"",
        re.IGNORECASE,
    )
    for m in pattern.finditer(content):
        line = _line_number(content, m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="CSS002",
                category="Security",
                severity="error",
                message=f"Hard-coded secret literal ({m.group(1)}) in source.",
                fix_suggestion="Move to environment variable, encrypted config, or platform secret store.",  # noqa: E501
            )
        )
    return out


def detect_http_url(content: str, file_path: str) -> List[Issue]:
    """CSS003: hardcoded `http://` URL literal — should be https."""
    out: List[Issue] = []
    for m in re.finditer(r"\"http://[^\"\\s]+\"", content):
        line = _line_number(content, m.start())
        # Skip example/comment-ish localhost references — harmless and noisy.
        snippet = m.group(0).lower()
        if "localhost" in snippet or "127.0.0.1" in snippet:
            continue
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="CSS003",
                category="Security",
                severity="warning",
                message="Hardcoded `http://` URL — traffic is unencrypted.",
                fix_suggestion="Switch to https://, or wire the base URL through configuration.",  # noqa: E501
            )
        )
    return out


def detect_playerprefs_secret(content: str, file_path: str) -> List[Issue]:
    """CSS004: PlayerPrefs storing credentials.

    PlayerPrefs is plaintext on disk (registry on Windows, plist on
    macOS, XML on Linux/Android). Storing passwords / tokens / keys
    there is a leak waiting to happen.
    """
    out: List[Issue] = []
    pattern = re.compile(
        r"PlayerPrefs\.SetString\s*\(\s*\"[^\"]*(?:password|passwd|token|secret|api[_-]?key|bearer)[^\"]*\"",  # noqa: E501
        re.IGNORECASE,
    )
    for m in pattern.finditer(content):
        line = _line_number(content, m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="CSS004",
                category="Security",
                severity="error",
                message="PlayerPrefs stores credential-like data in plaintext on disk.",
                fix_suggestion="Use a platform secure store (Keychain / DPAPI) or encrypt before persisting.",  # noqa: E501
            )
        )
    return out


def detect_instantiate_no_check(content: str, file_path: str) -> List[Issue]:
    """CSS005: Instantiate() result used without null check — crashes if prefab is missing."""  # noqa: E501
    out: List[Issue] = []
    pattern = re.compile(
        r"\b(\w+)\s*=\s*(?:Object\.)?Instantiate\s*[<(][^;]+;\s*\n"
        r"(?:[^\n]*\n){0,3}[^\n]*\b\1\s*\.",
    )
    for m in pattern.finditer(content):
        line = _line_number(content, m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="CSS005",
                category="Security",
                severity="warning",
                message="Instantiate() result dereferenced without null check — NullReferenceException if prefab is unassigned.",  # noqa: E501
                fix_suggestion="Check `if (instance == null) { Debug.LogError(...); return; }` before use.",  # noqa: E501
            )
        )
    return out


def detect_getcomponent_no_check(content: str, file_path: str) -> List[Issue]:
    """CSS006: GetComponent result immediately dereferenced without null check — NullReferenceException risk."""  # noqa: E501
    out: List[Issue] = []
    pattern = re.compile(
        r"\b(\w+)\s*=\s*GetComponent(?:InChildren|InParent)?\s*<[^>]+>\s*\(\s*\)\s*;\s*\n"  # noqa: E501
        r"(?:[^\n]*\n){0,3}[^\n]*\b\1\s*\.",
    )
    for m in pattern.finditer(content):
        line = _line_number(content, m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="CSS006",
                category="Security",
                severity="warning",
                message="GetComponent result dereferenced without null check — component may not be attached.",  # noqa: E501
                fix_suggestion="Guard with `if (comp == null) { Debug.LogError(...); return; }` before use.",  # noqa: E501
            )
        )
    return out


def detect_direct_cast_no_check(content: str, file_path: str) -> List[Issue]:
    """CSS007: direct C# cast (Type)obj without null check — InvalidCastException risk."""  # noqa: E501
    _PRIMITIVES = frozenset(
        {
            "int",
            "float",
            "double",
            "long",
            "byte",
            "short",
            "uint",
            "bool",
            "string",
            "object",
            "var",
            "char",
            "decimal",
        }
    )
    out: List[Issue] = []
    for m in re.finditer(r"\(\s*([A-Z]\w+)\s*\)\s*(\w+)(?!\s*\{)", content):
        cast_type = m.group(1)
        if cast_type in _PRIMITIVES:
            continue
        preceding = content[max(0, m.start() - 4) : m.start()].strip()
        if preceding.endswith("new") or preceding.endswith("("):
            continue
        line = _line_number(content, m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="CSS007",
                category="Security",
                severity="warning",
                message=f"Direct cast ({cast_type}) without null/type check — use `as` + null guard or `is` pattern.",  # noqa: E501
                fix_suggestion=f"Replace with `var x = obj as {cast_type}; if (x == null) return;`",  # noqa: E501
            )
        )
    return out


def detect_division_no_zero_check(content: str, file_path: str) -> List[Issue]:
    """CSS008: division by a variable without preceding zero check — DivideByZeroException risk."""  # noqa: E501
    out: List[Issue] = []
    _SAFE_VARS = frozenset({"i", "j", "k", "n", "t", "dt", "deltaTime"})
    for m in re.compile(r"\b\w+\s*/\s*(\w+)\b").finditer(content):
        divisor = m.group(1)
        if re.match(r"^\d+$", divisor) or divisor in _SAFE_VARS:
            continue
        line_no = _line_number(content, m.start())
        prev = "\n".join(content.splitlines()[max(0, line_no - 6) : line_no - 1])
        if re.search(
            rf"\b{re.escape(divisor)}\s*(?:!=|>|>=)\s*0|"
            rf"if\s*\([^)]*\b{re.escape(divisor)}\b",
            prev,
        ):
            continue
        out.append(
            _emit(
                file_path,
                line_no,
                content,
                rule_id="CSS008",
                category="Security",
                severity="warning",
                message=f"Division by `{divisor}` without zero check — DivideByZeroException if {divisor} == 0.",  # noqa: E501
                fix_suggestion=f"Guard with `if ({divisor} == 0) return;` or `if ({divisor} != 0) {{ ... }}`.",  # noqa: E501
            )
        )
    return out


def detect_collision_no_null_check(content: str, file_path: str) -> List[Issue]:
    """CSS009: OnCollisionEnter/OnTriggerEnter uses parameter without null check — crash on destroyed objects."""  # noqa: E501
    out: List[Issue] = []
    sig_re = re.compile(
        r"void\s+(?:OnCollisionEnter|OnCollisionExit|OnCollisionStay"
        r"|OnTriggerEnter|OnTriggerExit|OnTriggerStay"
        r"|OnCollisionEnter2D|OnTriggerEnter2D)\s*\(\s*\w+\s+(\w+)\s*\)"
    )
    for sig in sig_re.finditer(content):
        param = sig.group(1)
        span = _find_method_body(content, re.escape(sig.group(0)))
        if not span:
            continue
        body = content[span[0] : span[1]]
        if re.search(
            rf"\b{re.escape(param)}\s*(?:==|!=)\s*null|"
            rf"if\s*\([^)]*\b{re.escape(param)}\b",
            body,
        ):
            continue
        if not re.search(rf"\b{re.escape(param)}\s*\.", body):
            continue
        line = _line_number(content, sig.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="CSS009",
                category="Security",
                severity="warning",
                message=f"Collision/trigger handler uses `{param}` without null check — may crash if the object is destroyed mid-frame.",  # noqa: E501
                fix_suggestion=f"Guard with `if ({param} == null) return;` at the top of the handler.",  # noqa: E501
            )
        )
    return out
