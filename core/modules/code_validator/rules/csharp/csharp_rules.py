# core/modules/code_validator/rules/csharp/csharp_rules.py
#
# C# / Unity rule detectors — first implementation batch (14 of 96
# reserved IDs). Each detector takes the file content + path and returns
# a list of issue dicts, identical in shape to the cpp rules so downstream
# (filter_issues_by_tier, _analyse_file, Quality Score, dashboard
# persistence) stays engine-agnostic.
#
# Implementation notes:
#   - Regex-based, like the cpp baseline. Tree-sitter is a follow-up.
#   - Block extraction (Update {...}, catch {...}) uses a brace-balanced
#     walker. Good enough for the volume of false-positive risk in the
#     baseline; can be replaced with Roslyn / tree-sitter later.
#   - `is_auto_fixable` is False across the batch — auto-fix patterns
#     come in a later sprint together with the Unity-side ApplyFix path.

from __future__ import annotations

import re
from typing import Dict, List, Optional

Issue = Dict


# ── Helpers ─────────────────────────────────────────────────────────────


def _line_number(content: str, offset: int) -> int:
    return content.count("\n", 0, offset) + 1


def _line_text(content: str, line_no: int) -> str:
    lines = content.splitlines()
    return lines[line_no - 1].strip() if 0 < line_no <= len(lines) else ""


def _find_method_body(content: str, signature_re: str) -> Optional[tuple[int, int, int]]:
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
    sig_re = r"\b(?:private|public|protected|internal)?\s*void\s+(?:Update|LateUpdate|FixedUpdate)\s*\(\s*\)"
    span = _find_method_body(content, sig_re)
    if not span:
        return None
    return span[0], span[1]


def _emit(file_path: str, line_no: int, content: str, *,
          rule_id: str, category: str, severity: str,
          message: str, fix_suggestion: str) -> Issue:
    return {
        "asset_path": file_path,
        "line": line_no,
        "severity": severity,
        "rule_id": rule_id,
        "category": category,
        "message": message,
        "snippet": _line_text(content, line_no),
        "fix_suggestion": fix_suggestion,
        "is_auto_fixable": False,
    }


# ── Unity-specific (UN*) ────────────────────────────────────────────────


def detect_un001_findobject_in_update(content: str, file_path: str) -> List[Issue]:
    """UN001: GameObject.Find inside Update — O(scene) every frame."""
    body = _update_body(content)
    if not body:
        return []
    region = content[body[0]:body[1]]
    m = re.search(r"\bGameObject\.Find\s*\(", region)
    if not m:
        return []
    line = _line_number(content, body[0] + m.start())
    return [_emit(
        file_path, line, content,
        rule_id="UN001", category="Performance", severity="error",
        message="GameObject.Find called inside Update — scans the entire scene every frame.",
        fix_suggestion="Cache the reference in Awake/Start; expose it as [SerializeField] when possible.",
    )]


def detect_un002_getcomponent_in_update(content: str, file_path: str) -> List[Issue]:
    """UN002: GetComponent inside Update — reflection per frame."""
    body = _update_body(content)
    if not body:
        return []
    region = content[body[0]:body[1]]
    m = re.search(r"\bGetComponent\s*<", region)
    if not m:
        return []
    line = _line_number(content, body[0] + m.start())
    return [_emit(
        file_path, line, content,
        rule_id="UN002", category="Performance", severity="error",
        message="GetComponent called inside Update — cache the result in Awake/Start.",
        fix_suggestion="Move GetComponent<T>() to Awake() and store in a private field.",
    )]


def detect_un003_findobjectoftype_in_update(content: str, file_path: str) -> List[Issue]:
    """UN003: FindObjectOfType / FindAnyObjectByType inside Update."""
    body = _update_body(content)
    if not body:
        return []
    region = content[body[0]:body[1]]
    m = re.search(r"\b(?:FindObjectOfType|FindAnyObjectByType|FindObjectsOfType|FindObjectsByType)\s*<", region)
    if not m:
        return []
    line = _line_number(content, body[0] + m.start())
    return [_emit(
        file_path, line, content,
        rule_id="UN003", category="Performance", severity="error",
        message="FindObjectOfType called inside Update — scans every loaded object every frame.",
        fix_suggestion="Cache the reference in Awake/Start.",
    )]


def detect_un004_log_in_update(content: str, file_path: str) -> List[Issue]:
    """UN004: Debug.Log inside Update — IO + string format every frame."""
    body = _update_body(content)
    if not body:
        return []
    region = content[body[0]:body[1]]
    m = re.search(r"\bDebug\.(?:Log|LogWarning|LogError|LogFormat)\s*\(", region)
    if not m:
        return []
    line = _line_number(content, body[0] + m.start())
    return [_emit(
        file_path, line, content,
        rule_id="UN004", category="Performance", severity="warning",
        message="Debug.Log inside Update floods the console and serialises strings every frame.",
        fix_suggestion="Gate behind a #if UNITY_EDITOR / Conditional flag, or remove.",
    )]


def detect_un005_sendmessage_use(content: str, file_path: str) -> List[Issue]:
    """UN005: SendMessage / BroadcastMessage — reflection-based and slow."""
    out: List[Issue] = []
    for m in re.finditer(r"\b(?:SendMessage|SendMessageUpwards|BroadcastMessage)\s*\(", content):
        line = _line_number(content, m.start())
        out.append(_emit(
            file_path, line, content,
            rule_id="UN005", category="Performance", severity="warning",
            message="SendMessage uses reflection at runtime — prefer typed events / interfaces.",
            fix_suggestion="Replace with a direct method call, UnityEvent, or C# event/delegate.",
        ))
    return out


def detect_un006_public_field_monobehaviour(content: str, file_path: str) -> List[Issue]:
    """UN006: public field on a MonoBehaviour — prefer [SerializeField] private.

    Triggers when a class extends MonoBehaviour and exposes a non-static,
    non-property public field. Public fields are mutable from any caller
    and break encapsulation; SerializeField gives the same Inspector
    visibility while keeping the field internal.
    """
    cls_match = re.search(r"class\s+(\w+)\s*:[^{]*\bMonoBehaviour\b[^{]*\{", content)
    if not cls_match:
        return []
    # Restrict the scan to the class body
    body_start = cls_match.end()
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
    region = content[body_start:end]
    out: List[Issue] = []
    field_re = re.compile(
        r"^\s*public\s+(?!class\b|struct\b|enum\b|interface\b|static\b|const\b|override\b|virtual\b|abstract\b|event\b)"
        r"([\w<>,\s\[\]?]+?)\s+(\w+)\s*(?:=\s*[^;{]+)?;",
        re.MULTILINE,
    )
    for m in field_re.finditer(region):
        # Skip properties (have braces) and method declarations
        # (already excluded by the `;` anchor at end of regex).
        decl = m.group(0)
        if "{" in decl or "(" in decl:
            continue
        line = _line_number(content, body_start + m.start())
        out.append(_emit(
            file_path, line, content,
            rule_id="UN006", category="BestPractices", severity="warning",
            message=f"Public field '{m.group(2)}' on MonoBehaviour — prefer [SerializeField] private for Inspector exposure without breaking encapsulation.",
            fix_suggestion=f"[SerializeField] private {m.group(1).strip()} {m.group(2)};",
        ))
    return out


def detect_un007_empty_update(content: str, file_path: str) -> List[Issue]:
    """UN007: empty Update method — Unity still invokes it every frame."""
    sig_re = r"\b(?:private|public|protected|internal)?\s*void\s+(?:Update|LateUpdate|FixedUpdate)\s*\(\s*\)"
    span = _find_method_body(content, sig_re)
    if not span:
        return []
    body = content[span[0]:span[1]].strip()
    # Strip comments
    body_no_comments = re.sub(r"//[^\n]*", "", body)
    body_no_comments = re.sub(r"/\*.*?\*/", "", body_no_comments, flags=re.DOTALL).strip()
    if body_no_comments:
        return []
    line = span[2]
    return [_emit(
        file_path, line, content,
        rule_id="UN007", category="Performance", severity="warning",
        message="Empty Update/LateUpdate/FixedUpdate — Unity still pays the native→managed call overhead each frame.",
        fix_suggestion="Delete the method; Unity skips the per-frame call entirely.",
    )]


# ── Best practices (CSB*) ────────────────────────────────────────────────


def detect_csb001_empty_catch(content: str, file_path: str) -> List[Issue]:
    """CSB001: empty catch block swallows exceptions silently."""
    out: List[Issue] = []
    for m in re.finditer(r"\bcatch\b[^{]*\{(\s*)\}", content):
        # Body is the captured whitespace — empty if it's only whitespace.
        if m.group(1).strip():
            continue
        line = _line_number(content, m.start())
        out.append(_emit(
            file_path, line, content,
            rule_id="CSB001", category="BestPractices", severity="warning",
            message="Empty catch block silently swallows the exception.",
            fix_suggestion="Log the exception (Debug.LogException) or rethrow with `throw;`.",
        ))
    return out


def detect_csb002_todo_comment(content: str, file_path: str) -> List[Issue]:
    """CSB002: TODO / FIXME / HACK markers in source — flag for review."""
    out: List[Issue] = []
    for m in re.finditer(r"//\s*(TODO|FIXME|HACK|XXX)\b[^\n]*", content):
        line = _line_number(content, m.start())
        out.append(_emit(
            file_path, line, content,
            rule_id="CSB002", category="BestPractices", severity="info",
            message=f"{m.group(1)} comment — flag for follow-up.",
            fix_suggestion="Convert to a tracked ticket or resolve before merging.",
        ))
    return out


# ── Security (CSS*) ──────────────────────────────────────────────────────


def detect_css001_sql_concat(content: str, file_path: str) -> List[Issue]:
    """CSS001: SQL command built by string concatenation — injection risk."""
    out: List[Issue] = []
    pattern = re.compile(
        r"(?:SqlCommand|MySqlCommand|SqliteCommand|new\s+\w*Command)\s*\([^)]*\+[^)]*\)",
        re.IGNORECASE,
    )
    for m in pattern.finditer(content):
        line = _line_number(content, m.start())
        out.append(_emit(
            file_path, line, content,
            rule_id="CSS001", category="Security", severity="error",
            message="SQL command built with string concatenation — SQL injection risk.",
            fix_suggestion="Use parameterised queries with `cmd.Parameters.AddWithValue(...)`.",
        ))
    return out


def detect_css002_hardcoded_secret(content: str, file_path: str) -> List[Issue]:
    """CSS002: literal credentials in source (password = \"...\", api_key = \"...\")."""
    out: List[Issue] = []
    pattern = re.compile(
        r"\b(password|passwd|api[_-]?key|secret|token|bearer)\s*=\s*\"[^\"]{6,}\"",
        re.IGNORECASE,
    )
    for m in pattern.finditer(content):
        line = _line_number(content, m.start())
        out.append(_emit(
            file_path, line, content,
            rule_id="CSS002", category="Security", severity="error",
            message=f"Hard-coded secret literal ({m.group(1)}) in source.",
            fix_suggestion="Move to environment variable, encrypted config, or platform secret store.",
        ))
    return out


# ── Maintainability (CSM*) ───────────────────────────────────────────────


def detect_csm001_long_method(content: str, file_path: str) -> List[Issue]:
    """CSM001: method body exceeds 50 lines."""
    out: List[Issue] = []
    method_re = re.compile(
        r"\b(?:public|private|protected|internal)\s+(?:static\s+|virtual\s+|override\s+|async\s+|sealed\s+)*"
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
        body_lines = content[brace_open + 1:end].count("\n")
        if body_lines >= 50:
            line = _line_number(content, m.start())
            out.append(_emit(
                file_path, line, content,
                rule_id="CSM001", category="Maintainability", severity="warning",
                message=f"Method '{m.group(1)}' has {body_lines} lines — split into focused helpers.",
                fix_suggestion="Extract logical chunks into private helper methods (≤30 lines each).",
            ))
    return out


def detect_csm002_long_file(content: str, file_path: str) -> List[Issue]:
    """CSM002: file exceeds 500 lines — split the responsibility."""
    line_count = content.count("\n") + 1
    if line_count < 500:
        return []
    return [_emit(
        file_path, 1, content,
        rule_id="CSM002", category="Maintainability", severity="info",
        message=f"File has {line_count} lines — consider splitting into focused classes.",
        fix_suggestion="Group related members into partial classes or split into separate files.",
    )]


def detect_csm003_class_god_object(content: str, file_path: str) -> List[Issue]:
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
            out.append(_emit(
                file_path, line, content,
                rule_id="CSM003", category="Maintainability", severity="warning",
                message=f"Class '{cls.group(1)}' exposes {public_members} public members — likely a God Object.",
                fix_suggestion="Extract cohesive subsets into focused collaborator classes.",
            ))
    return out
