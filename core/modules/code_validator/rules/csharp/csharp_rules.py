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


# ─────────────────────────────────────────────────────────────────────────
# Batch 3 — 32 additional detectors
# ─────────────────────────────────────────────────────────────────────────


# ── Performance (CSP*) — batch 3 ──────────────────────────────────────


def detect_csp003_heavy_math_in_update(content: str, file_path: str) -> List[Issue]:
    """CSP003: expensive Mathf calls inside Update — CPU overhead every frame."""
    body = _update_body(content)
    if not body:
        return []
    region = content[body[0] : body[1]]
    m = re.search(
        r"\bMathf\.(?:Sqrt|Sin|Cos|Tan|Asin|Acos|Atan|Atan2|Pow|Exp|Log)\s*\(",
        region,
    )
    if not m:
        return []
    fn_match = re.search(r"Mathf\.(\w+)", region[m.start() :])
    fn_name = fn_match.group(1) if fn_match else "Sqrt/Sin/Pow"
    line = _line_number(content, body[0] + m.start())
    return [
        _emit(
            file_path,
            line,
            content,
            rule_id="CSP003",
            category="Performance",
            severity="warning",
            message=f"Mathf.{fn_name} called inside Update — transcendental math is expensive every frame.",  # noqa: E501
            fix_suggestion="Cache the result when inputs don't change every frame, or precompute a lookup table.",  # noqa: E501
        )
    ]


def detect_csp007_string_ops_in_update(content: str, file_path: str) -> List[Issue]:
    """CSP007: string allocation inside Update — GC pressure every frame."""
    body = _update_body(content)
    if not body:
        return []
    region = content[body[0] : body[1]]
    m = re.search(
        r'(?:string\.Format|String\.Format|string\.Concat|\$"[^"]*"'
        r'|"[^"]+"\s*\+\s*\w|\w+\s*\+\s*"[^"]+")',
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
            rule_id="CSP007",
            category="Performance",
            severity="warning",
            message="String allocation inside Update generates heap garbage every frame.",  # noqa: E501
            fix_suggestion="Cache static strings, use StringBuilder, or avoid interpolation in per-frame paths.",  # noqa: E501
        )
    ]


def detect_csp008_large_update_body(content: str, file_path: str) -> List[Issue]:
    """CSP008: Update method body exceeds 50 lines — too much work per frame."""
    sig_re = r"\b(?:private|public|protected|internal)?\s*void\s+(?:Update|LateUpdate)\s*\(\s*\)"  # noqa: E501
    span = _find_method_body(content, sig_re)
    if not span:
        return []
    body_lines = content[span[0] : span[1]].count("\n")
    if body_lines < 50:
        return []
    return [
        _emit(
            file_path,
            span[2],
            content,
            rule_id="CSP008",
            category="Performance",
            severity="warning",
            message=f"Update/LateUpdate has {body_lines} lines — split heavy logic into helpers or move off the frame path.",  # noqa: E501
            fix_suggestion="Extract sub-tasks into private methods; move work that doesn't need to run every frame into Coroutines.",  # noqa: E501
        )
    ]


def detect_csp009_collection_copy_in_loop(content: str, file_path: str) -> List[Issue]:
    """CSP009: new List<T>(existing) or .ToList()/.ToArray() inside a loop — O(n) allocation per iteration."""  # noqa: E501
    out: List[Issue] = []
    loop_re = re.compile(r"\b(?:for|foreach|while)\s*\(")
    for loop in loop_re.finditer(content):
        brace_open = content.find("{", loop.end())
        if brace_open < 0 or brace_open - loop.end() > 200:
            continue
        depth, end = 0, brace_open
        for i in range(brace_open, len(content)):
            if content[i] == "{":
                depth += 1
            elif content[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        body_region = content[brace_open + 1 : end]
        m = re.search(
            r"new\s+(?:List|HashSet|Dictionary|Queue|Stack)\s*<[^>]+>\s*\(\s*\w",
            body_region,
        )
        if not m:
            m = re.search(
                r"\.\s*(?:ToList|ToArray|ToDictionary|ToHashSet)\s*\(\s*\)", body_region
            )
        if not m:
            continue
        line = _line_number(content, brace_open + 1 + m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="CSP009",
                category="Performance",
                severity="warning",
                message="Collection copy/allocation inside a loop — allocates on every iteration.",  # noqa: E501
                fix_suggestion="Create the collection once outside the loop and Clear()/reuse inside.",  # noqa: E501
            )
        )
    return out


def detect_csp010_new_object_in_loop(content: str, file_path: str) -> List[Issue]:
    """CSP010: `new T()` for a reference type inside a loop — managed heap allocation per iteration."""  # noqa: E501
    out: List[Issue] = []
    _VALUE_TYPES = frozenset(
        {
            "int",
            "float",
            "double",
            "long",
            "byte",
            "short",
            "uint",
            "bool",
            "Vector2",
            "Vector3",
            "Vector4",
            "Color",
            "Color32",
            "Rect",
            "Bounds",
            "Quaternion",
            "WaitForSeconds",
            "WaitForEndOfFrame",
            "WaitForFixedUpdate",
        }
    )
    loop_re = re.compile(r"\b(?:for|foreach|while)\s*\(")
    for loop in loop_re.finditer(content):
        brace_open = content.find("{", loop.end())
        if brace_open < 0 or brace_open - loop.end() > 200:
            continue
        depth, end = 0, brace_open
        for i in range(brace_open, len(content)):
            if content[i] == "{":
                depth += 1
            elif content[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        body_region = content[brace_open + 1 : end]
        m = re.search(r"\bnew\s+([A-Z]\w+)\s*\(", body_region)
        if not m or m.group(1) in _VALUE_TYPES:
            continue
        line = _line_number(content, brace_open + 1 + m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="CSP010",
                category="Performance",
                severity="warning",
                message=f"new {m.group(1)}() inside a loop allocates a managed object on each iteration.",  # noqa: E501
                fix_suggestion="Allocate outside the loop and reset state inside, or use an object pool.",  # noqa: E501
            )
        )
    return out


def detect_csp011_gc_collect(content: str, file_path: str) -> List[Issue]:
    """CSP011: explicit GC.Collect() call — forces a stop-the-world GC pause."""
    out: List[Issue] = []
    for m in re.finditer(r"\bGC\.Collect\s*\(", content):
        line = _line_number(content, m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="CSP011",
                category="Performance",
                severity="error",
                message="GC.Collect() forces a synchronous garbage collection — causes visible frame spikes.",  # noqa: E501
                fix_suggestion="Remove the call and let the GC run autonomously; profile with Unity Memory Profiler before forcing collection.",  # noqa: E501
            )
        )
    return out


def detect_csp012_debug_assert_in_update(content: str, file_path: str) -> List[Issue]:
    """CSP012: Debug.Assert inside Update — evaluates condition and formats message every frame."""  # noqa: E501
    body = _update_body(content)
    if not body:
        return []
    region = content[body[0] : body[1]]
    m = re.search(r"\bDebug\.Assert\s*\(", region)
    if not m:
        return []
    line = _line_number(content, body[0] + m.start())
    return [
        _emit(
            file_path,
            line,
            content,
            rule_id="CSP012",
            category="Performance",
            severity="warning",
            message="Debug.Assert inside Update evaluates its condition and formats the message every frame.",  # noqa: E501
            fix_suggestion="Wrap in `#if UNITY_EDITOR` or `#if DEBUG`, or move the assertion to Awake/Start.",  # noqa: E501
        )
    ]


# ── Best practices (CSB*) — batch 3 ────────────────────────────────────


def detect_csb004_infinite_loop(content: str, file_path: str) -> List[Issue]:
    """CSB004: while(true) or for(;;) without break/return/goto — hangs the game thread."""  # noqa: E501
    out: List[Issue] = []
    loop_re = re.compile(r"\b(?:while\s*\(\s*true\s*\)|for\s*\(\s*;\s*;\s*\))\s*\{")
    for loop in loop_re.finditer(content):
        brace_open = content.rfind("{", loop.start(), loop.end())
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
                message="Infinite loop without break/return — will hang the game thread if reached on the main thread.",  # noqa: E501
                fix_suggestion="Add a termination condition, or convert to a Coroutine with a loop condition and `yield return null`.",  # noqa: E501
            )
        )
    return out


def detect_csb009_missing_override(content: str, file_path: str) -> List[Issue]:
    """CSB009: Unity lifecycle method declared without override in a derived class — silently shadows the base."""  # noqa: E501
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
                    message=f"{m.group(1)}() shadows the base class implementation — add `override` to be explicit.",  # noqa: E501
                    fix_suggestion=f"Change to `protected override void {m.group(1)}()` and add `base.{m.group(1)}();`.",  # noqa: E501
                )
            )
    return out


def detect_csb010_hardcoded_path(content: str, file_path: str) -> List[Issue]:
    """CSB010: hardcoded absolute file-system path — breaks on other machines and platforms."""  # noqa: E501
    out: List[Issue] = []
    for m in re.finditer(
        r'"(?:[A-Za-z]:\\[^"\\]{3,}|/(?:home|Users|var|tmp|opt)/[^"]{3,})"',
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
                message="Hardcoded absolute path — will not work on other machines or platforms.",  # noqa: E501
                fix_suggestion="Use Application.dataPath, Application.persistentDataPath, or Path.Combine with relative segments.",  # noqa: E501
            )
        )
    return out


def detect_csb011_empty_if_body(content: str, file_path: str) -> List[Issue]:
    """CSB011: empty if body {} — likely a logic error or unfinished branch."""
    out: List[Issue] = []
    for m in re.finditer(r"\bif\s*\([^)]+\)\s*\{\s*\}", content):
        line = _line_number(content, m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="CSB011",
                category="BestPractices",
                severity="warning",
                message="Empty if body — likely an unfinished branch or accidental semicolon.",  # noqa: E501
                fix_suggestion="Add the intended code, invert the condition to remove dead branches, or delete the if block.",  # noqa: E501
            )
        )
    return out


def detect_csb012_event_not_unsubscribed(content: str, file_path: str) -> List[Issue]:
    """CSB012: event += subscription without matching -= in OnDestroy — listener memory leak."""  # noqa: E501
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
                message=f"Event `{event_name} +=` has no matching `-=` in OnDestroy — listener leak.",  # noqa: E501
                fix_suggestion=f"In OnDestroy: `{event_name} -= <HandlerName>;`",
            )
        )
    return out


def detect_csb013_log_outside_editor_guard(content: str, file_path: str) -> List[Issue]:
    """CSB013: Debug.Log outside #if UNITY_EDITOR guard — active in production builds."""  # noqa: E501
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
                    message="Debug.Log is active in production builds — wrap in #if UNITY_EDITOR or remove.",  # noqa: E501
                    fix_suggestion="#if UNITY_EDITOR\n    Debug.Log(...);\n#endif",
                )
            )
    return out


def detect_csb014_float_no_f_suffix(content: str, file_path: str) -> List[Issue]:
    """CSB014: float variable assigned a double literal (missing f suffix) — implicit narrowing conversion."""  # noqa: E501
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
                message="Float assigned a double literal (missing `f` suffix) — implicit narrowing conversion.",  # noqa: E501
                fix_suggestion="Append `f` to the literal (e.g. `1.5` → `1.5f`).",
            )
        )
    return out


def detect_csb015_empty_destructor(content: str, file_path: str) -> List[Issue]:
    """CSB015: empty destructor/finalizer — registers for GC finalization queue with no benefit."""  # noqa: E501
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


def detect_csb016_commented_out_code(content: str, file_path: str) -> List[Issue]:
    """CSB016: three or more consecutive commented-out code lines — dead code clutters the file."""  # noqa: E501
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
                    message=f"{count} consecutive commented-out code lines — remove dead code.",  # noqa: E501
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


# ── Security (CSS*) — batch 3 ──────────────────────────────────────────


def detect_css005_instantiate_no_check(content: str, file_path: str) -> List[Issue]:
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


def detect_css006_getcomponent_no_check(content: str, file_path: str) -> List[Issue]:
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


def detect_css007_direct_cast_no_check(content: str, file_path: str) -> List[Issue]:
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


def detect_css008_division_no_zero_check(content: str, file_path: str) -> List[Issue]:
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


def detect_css009_collision_no_null_check(content: str, file_path: str) -> List[Issue]:
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


# ── Unity-specific (UN*) — batch 3 ────────────────────────────────────


def detect_un009_coroutine_leak(content: str, file_path: str) -> List[Issue]:
    """UN009: StartCoroutine without StopCoroutine/StopAllCoroutines in OnDestroy — coroutine fires on destroyed object."""  # noqa: E501
    if not re.search(r"\bStartCoroutine\s*\(", content):
        return []
    ondestroy_span = _find_method_body(
        content, r"\b(?:override\s+)?void\s+OnDestroy\s*\(\s*\)"
    )
    ondestroy_body = (
        content[ondestroy_span[0] : ondestroy_span[1]] if ondestroy_span else ""
    )
    if re.search(r"\bStop(?:All)?Coroutines?\s*\(", ondestroy_body):
        return []
    m = re.search(r"\bStartCoroutine\s*\(", content)
    if not m:
        return []
    line = _line_number(content, m.start())
    return [
        _emit(
            file_path,
            line,
            content,
            rule_id="UN009",
            category="Performance",
            severity="warning",
            message="StartCoroutine with no StopAllCoroutines in OnDestroy — Coroutine may fire callbacks on a destroyed MonoBehaviour.",  # noqa: E501
            fix_suggestion="Add `StopAllCoroutines();` at the start of OnDestroy.",
        )
    ]


def detect_un010_physics_in_update(content: str, file_path: str) -> List[Issue]:
    """UN010: Rigidbody physics applied in Update — causes frame-rate-dependent jitter."""  # noqa: E501
    sig_re = r"\b(?:private|public|protected|internal)?\s*void\s+(?:Update|LateUpdate)\s*\(\s*\)"  # noqa: E501
    span = _find_method_body(content, sig_re)
    if not span:
        return []
    body = content[span[0] : span[1]]
    m = re.search(
        r"\b(?:\w+)\s*\.\s*(?:AddForce|AddTorque|velocity|angularVelocity|MovePosition|MoveRotation)\b",  # noqa: E501
        body,
        re.IGNORECASE,
    )
    if not m:
        return []
    line = _line_number(content, span[0] + m.start())
    return [
        _emit(
            file_path,
            line,
            content,
            rule_id="UN010",
            category="Performance",
            severity="warning",
            message="Rigidbody force/velocity set in Update — physics should run in FixedUpdate to avoid frame-rate jitter.",  # noqa: E501
            fix_suggestion="Move Rigidbody modifications to FixedUpdate(); scale forces with Time.fixedDeltaTime.",  # noqa: E501
        )
    ]


def detect_un011_transform_in_loop(content: str, file_path: str) -> List[Issue]:
    """UN011: transform.position/rotation written inside a loop — each write notifies the physics engine."""  # noqa: E501
    out: List[Issue] = []
    loop_re = re.compile(r"\b(?:for|foreach|while)\s*\(")
    for loop in loop_re.finditer(content):
        brace_open = content.find("{", loop.end())
        if brace_open < 0 or brace_open - loop.end() > 200:
            continue
        depth, end = 0, brace_open
        for i in range(brace_open, len(content)):
            if content[i] == "{":
                depth += 1
            elif content[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        body_region = content[brace_open + 1 : end]
        m = re.search(
            r"\btransform\s*\.\s*(?:position|rotation|localPosition|localScale|eulerAngles)\s*=",  # noqa: E501
            body_region,
        )
        if not m:
            continue
        line = _line_number(content, brace_open + 1 + m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="UN011",
                category="Performance",
                severity="warning",
                message="transform.position/rotation assigned inside a loop — each write triggers a physics sync notification.",  # noqa: E501
                fix_suggestion="Compute the final transform outside the loop and assign once; batch with TransformPoint for arrays.",  # noqa: E501
            )
        )
    return out


def detect_un013_missing_require_component(content: str, file_path: str) -> List[Issue]:
    """UN013: GetComponent<T> in Awake without [RequireComponent(typeof(T))] — dependency unchecked at edit-time."""  # noqa: E501
    awake_span = _find_method_body(
        content, r"\b(?:private|public|protected)?\s*void\s+Awake\s*\(\s*\)"
    )
    if not awake_span:
        return []
    awake_body = content[awake_span[0] : awake_span[1]]
    out: List[Issue] = []
    for m in re.finditer(r"\bGetComponent\s*<(\w+)>\s*\(\s*\)", awake_body):
        comp_type = m.group(1)
        if re.search(
            rf"\[RequireComponent\s*\(\s*typeof\s*\(\s*{re.escape(comp_type)}\s*\)",
            content[: awake_span[0]],
        ):
            continue
        line = _line_number(content, awake_span[0] + m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="UN013",
                category="BestPractices",
                severity="info",
                message=f"GetComponent<{comp_type}>() in Awake without [RequireComponent] — missing component causes silent null.",  # noqa: E501
                fix_suggestion=f"Add `[RequireComponent(typeof({comp_type}))]` above the class declaration.",  # noqa: E501
            )
        )
    return out


def detect_un014_dont_destroy_non_singleton(
    content: str, file_path: str
) -> List[Issue]:
    """UN014: DontDestroyOnLoad outside a singleton guard — duplicate instances accumulate on scene reload."""  # noqa: E501
    out: List[Issue] = []
    for m in re.finditer(r"\bDontDestroyOnLoad\s*\(", content):
        preceding = content[max(0, m.start() - 300) : m.start()]
        if re.search(r"\bif\s*\([^)]*\b_?[Ii]nstance\b[^)]*==\s*null", preceding):
            continue
        line = _line_number(content, m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="UN014",
                category="BestPractices",
                severity="warning",
                message="DontDestroyOnLoad called without a singleton guard — duplicates accumulate across scene loads.",  # noqa: E501
                fix_suggestion="Wrap in `if (instance == null) { instance = this; DontDestroyOnLoad(gameObject); } else { Destroy(gameObject); }`.",  # noqa: E501
            )
        )
    return out


def detect_un015_resources_load(content: str, file_path: str) -> List[Issue]:
    """UN015: Resources.Load usage — synchronous, loads assets into always-resident memory; prefer Addressables."""  # noqa: E501
    out: List[Issue] = []
    for m in re.finditer(r"\bResources\.(?:Load|LoadAll|LoadAsync)\s*[<(]", content):
        line = _line_number(content, m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="UN015",
                category="BestPractices",
                severity="info",
                message="Resources.Load bundles all assets unconditionally and loads synchronously — prefer Addressables for on-demand async loading.",  # noqa: E501
                fix_suggestion='Migrate to `Addressables.LoadAssetAsync<T>("key")` with `.Completed` callback or `await`.',  # noqa: E501
            )
        )
    return out


def detect_un016_scriptableobject_no_menu(content: str, file_path: str) -> List[Issue]:
    """UN016: ScriptableObject subclass without [CreateAssetMenu] — cannot be created from the Unity Editor."""  # noqa: E501
    so_match = re.search(r"\bclass\s+(\w+)\s*:\s*ScriptableObject\b", content)
    if not so_match:
        return []
    if re.search(r"\[CreateAssetMenu\b", content[: so_match.start()]):
        return []
    line = _line_number(content, so_match.start())
    return [
        _emit(
            file_path,
            line,
            content,
            rule_id="UN016",
            category="BestPractices",
            severity="info",
            message=f"ScriptableObject '{so_match.group(1)}' has no [CreateAssetMenu] — cannot be instantiated from Assets > Create.",  # noqa: E501
            fix_suggestion=f'Add `[CreateAssetMenu(fileName = "{so_match.group(1)}", menuName = "ScriptableObjects/{so_match.group(1)}")]` above the class.',  # noqa: E501
        )
    ]
