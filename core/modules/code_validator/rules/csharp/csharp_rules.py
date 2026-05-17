# core/modules/code_validator/rules/csharp/csharp_rules.py
#
# C# / Unity rule detectors — 27 of 96 reserved IDs (batches 1 + 2).
# Each detector takes the file content + path and returns a list of
# issue dicts, identical in shape to the cpp rules so downstream
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
# Keep this in sync with CSHARP_RULE_TO_PATTERN in _csharp_helpers.py:
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


# ── Unity-specific (UN*) ────────────────────────────────────────────────


def detect_un001_findobject_in_update(content: str, file_path: str) -> List[Issue]:
    """UN001: GameObject.Find inside Update — O(scene) every frame."""
    body = _update_body(content)
    if not body:
        return []
    region = content[body[0] : body[1]]
    m = re.search(r"\bGameObject\.Find\s*\(", region)
    if not m:
        return []
    line = _line_number(content, body[0] + m.start())
    return [
        _emit(
            file_path,
            line,
            content,
            rule_id="UN001",
            category="Performance",
            severity="error",
            message="GameObject.Find called inside Update — scans the entire scene every frame.",  # noqa: E501
            fix_suggestion="Cache the reference in Awake/Start; expose it as [SerializeField] when possible.",  # noqa: E501
        )
    ]


def detect_un002_getcomponent_in_update(content: str, file_path: str) -> List[Issue]:
    """UN002: GetComponent inside Update — reflection per frame."""
    body = _update_body(content)
    if not body:
        return []
    region = content[body[0] : body[1]]
    m = re.search(r"\bGetComponent\s*<", region)
    if not m:
        return []
    line = _line_number(content, body[0] + m.start())
    return [
        _emit(
            file_path,
            line,
            content,
            rule_id="UN002",
            category="Performance",
            severity="error",
            message="GetComponent called inside Update — cache the result in Awake/Start.",  # noqa: E501
            fix_suggestion="Move GetComponent<T>() to Awake() and store in a private field.",  # noqa: E501
        )
    ]


def detect_un003_findobjectoftype_in_update(
    content: str, file_path: str
) -> List[Issue]:
    """UN003: FindObjectOfType / FindAnyObjectByType inside Update."""
    body = _update_body(content)
    if not body:
        return []
    region = content[body[0] : body[1]]
    m = re.search(
        r"\b(?:FindObjectOfType|FindAnyObjectByType|FindObjectsOfType|FindObjectsByType)\s*<",  # noqa: E501
        region,
    )
    if not m:
        return []
    line = _line_number(content, body[0] + m.start())
    return [
        _emit(
            file_path,
            line,
            content,
            rule_id="UN003",
            category="Performance",
            severity="error",
            message="FindObjectOfType called inside Update — scans every loaded object every frame.",  # noqa: E501
            fix_suggestion="Cache the reference in Awake/Start.",
        )
    ]


def detect_un004_log_in_update(content: str, file_path: str) -> List[Issue]:
    """UN004: Debug.Log inside Update — IO + string format every frame."""
    body = _update_body(content)
    if not body:
        return []
    region = content[body[0] : body[1]]
    m = re.search(r"\bDebug\.(?:Log|LogWarning|LogError|LogFormat)\s*\(", region)
    if not m:
        return []
    line = _line_number(content, body[0] + m.start())
    return [
        _emit(
            file_path,
            line,
            content,
            rule_id="UN004",
            category="Performance",
            severity="warning",
            message="Debug.Log inside Update floods the console and serialises strings every frame.",  # noqa: E501
            fix_suggestion="Gate behind a #if UNITY_EDITOR / Conditional flag, or remove.",  # noqa: E501
        )
    ]


def detect_un005_sendmessage_use(content: str, file_path: str) -> List[Issue]:
    """UN005: SendMessage / BroadcastMessage — reflection-based and slow."""
    out: List[Issue] = []
    for m in re.finditer(
        r"\b(?:SendMessage|SendMessageUpwards|BroadcastMessage)\s*\(", content
    ):
        line = _line_number(content, m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="UN005",
                category="Performance",
                severity="warning",
                message="SendMessage uses reflection at runtime — prefer typed events / interfaces.",  # noqa: E501
                fix_suggestion="Replace with a direct method call, UnityEvent, or C# event/delegate.",  # noqa: E501
            )
        )
    return out


def detect_un006_public_field_monobehaviour(
    content: str, file_path: str
) -> List[Issue]:
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
        r"^\s*public\s+(?!class\b|struct\b|enum\b|interface\b|static\b|const\b|override\b|virtual\b|abstract\b|event\b)"  # noqa: E501
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
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="UN006",
                category="BestPractices",
                severity="warning",
                message=f"Public field '{m.group(2)}' on MonoBehaviour — prefer [SerializeField] private for Inspector exposure without breaking encapsulation.",  # noqa: E501
                fix_suggestion=f"[SerializeField] private {m.group(1).strip()} {m.group(2)};",  # noqa: E501
            )
        )
    return out


def detect_un007_empty_update(content: str, file_path: str) -> List[Issue]:
    """UN007: empty Update method — Unity still invokes it every frame."""
    sig_re = r"\b(?:private|public|protected|internal)?\s*void\s+(?:Update|LateUpdate|FixedUpdate)\s*\(\s*\)"  # noqa: E501
    span = _find_method_body(content, sig_re)
    if not span:
        return []
    body = content[span[0] : span[1]].strip()
    # Strip comments
    body_no_comments = re.sub(r"//[^\n]*", "", body)
    body_no_comments = re.sub(
        r"/\*.*?\*/", "", body_no_comments, flags=re.DOTALL
    ).strip()
    if body_no_comments:
        return []
    line = span[2]
    return [
        _emit(
            file_path,
            line,
            content,
            rule_id="UN007",
            category="Performance",
            severity="warning",
            message="Empty Update/LateUpdate/FixedUpdate — Unity still pays the native→managed call overhead each frame.",  # noqa: E501
            fix_suggestion="Delete the method; Unity skips the per-frame call entirely.",  # noqa: E501
        )
    ]


# ── Best practices (CSB*) ────────────────────────────────────────────────


def detect_csb001_empty_catch(content: str, file_path: str) -> List[Issue]:
    """CSB001: empty catch block swallows exceptions silently."""
    out: List[Issue] = []
    for m in re.finditer(r"\bcatch\b[^{]*\{(\s*)\}", content):
        # Body is the captured whitespace — empty if it's only whitespace.
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


def detect_csb002_todo_comment(content: str, file_path: str) -> List[Issue]:
    """CSB002: TODO / FIXME / HACK markers in source — flag for review."""
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
                message=f"{m.group(1)} comment — flag for follow-up.",
                fix_suggestion="Convert to a tracked ticket or resolve before merging.",
            )
        )
    return out


# ── Security (CSS*) ──────────────────────────────────────────────────────


def detect_css001_sql_concat(content: str, file_path: str) -> List[Issue]:
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


def detect_css002_hardcoded_secret(content: str, file_path: str) -> List[Issue]:
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


# ── Maintainability (CSM*) ───────────────────────────────────────────────


def detect_csm001_long_method(content: str, file_path: str) -> List[Issue]:
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
                    message=f"Method '{m.group(1)}' has {body_lines} lines — split into focused helpers.",  # noqa: E501
                    fix_suggestion="Extract logical chunks into private helper methods (≤30 lines each).",  # noqa: E501
                )
            )
    return out


def detect_csm002_long_file(content: str, file_path: str) -> List[Issue]:
    """CSM002: file exceeds 500 lines — split the responsibility."""
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
            message=f"File has {line_count} lines — consider splitting into focused classes.",  # noqa: E501
            fix_suggestion="Group related members into partial classes or split into separate files.",  # noqa: E501
        )
    ]


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
            out.append(
                _emit(
                    file_path,
                    line,
                    content,
                    rule_id="CSM003",
                    category="Maintainability",
                    severity="warning",
                    message=f"Class '{cls.group(1)}' exposes {public_members} public members — likely a God Object.",  # noqa: E501
                    fix_suggestion="Extract cohesive subsets into focused collaborator classes.",  # noqa: E501
                )
            )
    return out


# ─────────────────────────────────────────────────────────────────────────
# Batch 2 — 13 additional detectors
# ─────────────────────────────────────────────────────────────────────────


# ── Unity-specific (UN*) — batch 2 ─────────────────────────────────────


def detect_un008_camera_main_in_update(content: str, file_path: str) -> List[Issue]:
    """UN008: Camera.main inside Update.

    Camera.main is `GameObject.FindGameObjectWithTag("MainCamera")` under
    the hood — full scene tag scan every frame.
    """
    body = _update_body(content)
    if not body:
        return []
    region = content[body[0] : body[1]]
    m = re.search(r"\bCamera\.main\b", region)
    if not m:
        return []
    line = _line_number(content, body[0] + m.start())
    return [
        _emit(
            file_path,
            line,
            content,
            rule_id="UN008",
            category="Performance",
            severity="error",
            message="Camera.main inside Update — does a full FindGameObjectWithTag scan every frame.",  # noqa: E501
            fix_suggestion="Cache the camera reference in Awake/Start (private Camera _mainCam = Camera.main).",  # noqa: E501
        )
    ]


def detect_un012_tag_string_compare(content: str, file_path: str) -> List[Issue]:
    """UN012: `obj.tag == "X"` — boxes a string each call. Use CompareTag.

    Unity's GameObject.tag getter allocates a new managed string every
    access; equality with a literal allocates again. CompareTag avoids
    both allocations and is recommended by Unity's own profiler docs.
    """
    out: List[Issue] = []
    pattern = re.compile(r"\.\s*tag\s*(?:==|!=)\s*\"[^\"]+\"")
    for m in pattern.finditer(content):
        line = _line_number(content, m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="UN012",
                category="Performance",
                severity="warning",
                message="String comparison with .tag allocates per access — use CompareTag instead.",  # noqa: E501
                fix_suggestion='Replace `obj.tag == "X"` with `obj.CompareTag("X")`.',
            )
        )
    return out


# ── Performance (CSP*) — batch 2 ──────────────────────────────────────


_LINQ_OPERATORS = (
    r"Where|Select|SelectMany|ToList|ToArray|ToDictionary|First|FirstOrDefault|"
    r"Single|SingleOrDefault|Any|All|Count|GroupBy|OrderBy|OrderByDescending|"
    r"ThenBy|Aggregate|Distinct|Reverse|Take|Skip|Zip"
)


def detect_csp001_linq_in_update(content: str, file_path: str) -> List[Issue]:
    """CSP001: LINQ chain inside Update — allocates enumerator+lambda each frame."""
    body = _update_body(content)
    if not body:
        return []
    region = content[body[0] : body[1]]
    m = re.search(rf"\.(?:{_LINQ_OPERATORS})\s*\(", region)
    if not m:
        return []
    line = _line_number(content, body[0] + m.start())
    return [
        _emit(
            file_path,
            line,
            content,
            rule_id="CSP001",
            category="Performance",
            severity="warning",
            message="LINQ operator used inside Update — allocates enumerators/closures every frame.",  # noqa: E501
            fix_suggestion="Replace with a manual loop, or hoist the query result outside the per-frame path.",  # noqa: E501
        )
    ]


def detect_csp002_string_concat_in_loop(content: str, file_path: str) -> List[Issue]:
    """CSP002: `str += …` inside for/while/foreach body — O(n²) allocations.

    Heuristic: a `<var> +=` line that contains either a string literal
    or `.ToString(` on the RHS, located inside a brace-balanced loop body.
    Captures the most damaging case (per-iteration string build); leaves
    the small fraction of false positives to a future Tree-sitter pass.
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
                    message="String concatenation with += inside a loop — O(n²) allocations.",  # noqa: E501
                    fix_suggestion="Build the result with `StringBuilder.Append` and call `.ToString()` once after the loop.",  # noqa: E501
                )
            )
    return out


def detect_csp004_instantiate_in_update(content: str, file_path: str) -> List[Issue]:
    """CSP004: Instantiate inside Update — per-frame GameObject allocation."""
    body = _update_body(content)
    if not body:
        return []
    region = content[body[0] : body[1]]
    m = re.search(r"\bInstantiate\s*\(", region)
    if not m:
        return []
    line = _line_number(content, body[0] + m.start())
    return [
        _emit(
            file_path,
            line,
            content,
            rule_id="CSP004",
            category="Performance",
            severity="error",
            message="Instantiate inside Update allocates a GameObject every frame — use object pooling.",  # noqa: E501
            fix_suggestion="Pre-spawn instances at Start and pull from a Queue/Stack pool; Destroy → SetActive(false).",  # noqa: E501
        )
    ]


def detect_csp006_new_waitforseconds(content: str, file_path: str) -> List[Issue]:
    """CSP006: `yield return new WaitForSeconds(x)` — allocates each yield.

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


# ── Best practices (CSB*) — batch 2 ───────────────────────────────────


def detect_csb003_catch_exception_broad(content: str, file_path: str) -> List[Issue]:
    """CSB003: `catch (Exception)` without filter — swallows specific errors.

    Allowed when the catch body either rethrows (`throw;`) or logs the
    exception (`LogException` / `LogError` / `Console.WriteLine`). Anything
    else is considered overly broad and worth flagging.
    """
    out: List[Issue] = []
    pattern = re.compile(r"\bcatch\s*\(\s*(?:System\.)?Exception\s+(\w+)\s*\)\s*\{")
    for m in pattern.finditer(content):
        brace = m.end() - 1
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
                message="`catch (Exception)` without rethrow or logging — masks bugs.",
                fix_suggestion="Catch a specific exception type, or `Debug.LogException(ex)` and rethrow.",  # noqa: E501
            )
        )
    return out


def detect_csb005_async_void(content: str, file_path: str) -> List[Issue]:
    """CSB005: `async void` method — exceptions crash the process.

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
                message=f"async void method '{name}' — uncaught exceptions crash the process.",  # noqa: E501
                fix_suggestion="Return `async Task` (or `async UniTask` in Unity) so callers can await and observe errors.",  # noqa: E501
            )
        )
    return out


def detect_csb006_magic_number(content: str, file_path: str) -> List[Issue]:
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
                # Inside brackets — small literal indices are typical
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
                    message=f"Magic number {val} in expression — extract to a named constant.",  # noqa: E501
                    fix_suggestion=f"Replace with `private const float MyMeaningfulName = {val};` (or appropriate type).",  # noqa: E501
                )
            )
            break  # one issue per line keeps the report compact
    return out


# ── Security (CSS*) — batch 2 ─────────────────────────────────────────


def detect_css003_http_url(content: str, file_path: str) -> List[Issue]:
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


def detect_css004_playerprefs_secret(content: str, file_path: str) -> List[Issue]:
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


# ── Maintainability (CSM*) — batch 2 ──────────────────────────────────


def detect_csm004_too_many_params(content: str, file_path: str) -> List[Issue]:
    """CSM004: method with > 5 parameters — bundle into a struct/options class."""
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
                message=f"Method '{m.group(1)}' has {len(params)} parameters — extract a parameter object.",  # noqa: E501
                fix_suggestion="Group related parameters into a `record` or `struct`; pass that instead.",  # noqa: E501
            )
        )
    return out


def detect_csm005_deep_nesting(content: str, file_path: str) -> List[Issue]:
    """CSM005: control-flow nesting depth ≥ 4 — extract guard clauses / helpers.

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
                    message=f"Method '{m.group(1)}' nests {max_depth - 1} levels deep — flatten with early returns or extract helpers.",  # noqa: E501
                    fix_suggestion="Replace nested if/else chains with early-return guard clauses, or move inner blocks into private methods.",  # noqa: E501
                )
            )
    return out
