# core/modules/code_validator/rules/cpp/cpp_security.py
#
# Security rules (CS) for Unreal Engine 5 C++.
# Detects null-pointer dereferences, unchecked casts,
# division by zero, insecure protocols, and hardcoded secrets.
#
# Rule index:
#   CS001  GetWorld() without null-check
#   CS002  SpawnActor without null-check
#   CS003  Cast<T> without null-check
#   CS004  Division without zero-check
#   CS005  TArray access without bounds check
#   CS006  GetOwner() without null-check
#   CS007  OtherActor in overlap without null-check
#   CS008  TWeakObjectPtr without IsValid()
#   CS011  HTTP insecure (http:// instead of https://)
#   CS012  Hardcoded password or API key
# Total: 10 rules

import re
from typing import List

from code_validator.rules._cpp_helpers import (
    Issue,
    _char_pos_for_line,
    _code_part,
    _extract_class_name,
    _is_comment_line,
    _is_cpp,
    _is_fixable,
    _is_source,
)


# CS001: GetWorld() without null-check
def detect_getworld_no_check(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects GetWorld()-> calls without a null-check.
    GetWorld() can return nullptr in editor utilities,
    commandlets, or during shutdown. Always guard with
    'if (UWorld* W = GetWorld())' before dereferencing.

    Lookback: scans the preceding 10 lines for safe
    guard patterns to avoid false positives.
    """
    if not _is_source(file_path):
        return []

    _LOOKBACK = 10

    # Patterns that prove GetWorld() was already guarded
    _GUARD_RE = re.compile(
        r"if\s*\(\s*(?:UWorld\s*\*\s*\w+\s*=\s*)?GetWorld\(\)"
        r"|"
        r"(?:UWorld\s*\*\s*\w+\s*=\s*GetWorld\(\))"
    )

    issues: List[Issue] = []
    source_lines = content.splitlines()
    in_block_comment = False
    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()
        if in_block_comment:
            if "*/" in source_line:
                in_block_comment = False
            continue
        if "/*" in stripped:
            before_comment = stripped[: stripped.find("/*")]
            after_open = stripped[stripped.find("/*") + 2 :]
            if "*/" not in after_open:
                in_block_comment = True
                stripped = before_comment.strip()
                if not stripped:
                    continue
            else:
                stripped = (
                    before_comment + after_open[after_open.find("*/") + 2 :]
                ).strip()
        if _is_comment_line(stripped):
            continue
        code = _code_part(source_line)
        if not re.search(r"\bGetWorld\(\)\s*->", code):
            continue

        # Lookback: check preceding lines for a guard
        start = max(0, line_no - 1 - _LOOKBACK)
        preceding = " ".join(source_lines[start : line_no - 1])
        if _GUARD_RE.search(preceding):
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
                "rule_id": "CS001",
                "category": "Security",
                "message": (
                    "GetWorld() called without null-check — "
                    "guard with "
                    "'if (UWorld* W = GetWorld())'."
                ),
                "snippet": stripped,
                "fix_suggestion": "Add null-check for GetWorld()",
                "is_auto_fixable": _is_fixable("CS001"),
            }
        )
    return issues


# CS002: SpawnActor without null-check
def detect_spawnactor_no_check(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects SpawnActor calls whose result is used on the very
    next non-empty line without a null-check guard.
    SpawnActor can return nullptr if the spawn fails.
    Always check the result before use.
    """
    if not _is_source(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    for line_no, source_line in enumerate(source_lines, start=1):
        if not re.search(r"\bSpawnActor\s*<", source_line):
            continue

        var_match = re.search(r"\b(\w+)\s*=\s*\S+SpawnActor\s*<", source_line)
        if not var_match:
            continue

        var_name = var_match.group(1)
        class_name = _extract_class_name(
            content,
            _char_pos_for_line(source_lines, line_no),
        )

        for offset, next_line in enumerate(
            source_lines[line_no : line_no + 5], start=1
        ):
            stripped = next_line.strip()
            if not stripped:
                continue
            if re.search(rf"\b{re.escape(var_name)}\s*->", stripped):
                prev_code = ""
                for prev_idx in range(
                    line_no + offset - 2,
                    max(line_no - 1, -1),
                    -1,
                ):
                    prev_stripped = (
                        source_lines[prev_idx].strip() if prev_idx >= 0 else ""
                    )
                    if prev_stripped:
                        prev_code = _code_part(prev_stripped).rstrip()
                        break
                is_continuation = bool(re.search(r"[(&|]{1,2}\s*$", prev_code))
                if not re.search(r"\bif\b", stripped) and not is_continuation:
                    # Report on the USAGE line
                    usage_line_no = line_no + offset
                    issues.append(
                        {
                            "asset_path": file_path,
                            "line": usage_line_no,
                            "class": class_name,
                            "severity": "error",
                            "rule_id": "CS002",
                            "category": "Security",
                            "message": (
                                f"SpawnActor result "
                                f"'{var_name}'"
                                " used without null-check"
                                " — SpawnActor can return"
                                " nullptr."
                            ),
                            "snippet": stripped,
                            "fix_suggestion": (
                                "Add null-check for " "SpawnActor result"
                            ),
                            "is_auto_fixable": _is_fixable("CS002"),
                        }
                    )
            break

    return issues


# CS003: Cast<T> without null-check
def detect_cast_no_check(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects Cast<T> calls whose result is used on the next
    non-empty line without a null-check guard.
    Cast<T> returns nullptr if the object is not of the
    expected type. Always check the result before dereferencing.
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    for line_no, source_line in enumerate(source_lines, start=1):
        if not re.search(r"\bCast\s*<", source_line):
            continue

        var_match = re.search(r"\b(\w+)\s*=\s*Cast\s*<", source_line)
        if not var_match:
            continue

        var_name = var_match.group(1)
        class_name = _extract_class_name(
            content,
            _char_pos_for_line(source_lines, line_no),
        )

        for offset, next_line in enumerate(
            source_lines[line_no : line_no + 5], start=1
        ):
            stripped = next_line.strip()
            if not stripped:
                continue
            if re.search(rf"\b{re.escape(var_name)}\s*->", stripped):
                prev_code = ""
                for prev_idx in range(
                    line_no + offset - 2,
                    max(line_no - 1, -1),
                    -1,
                ):
                    prev_stripped = (
                        source_lines[prev_idx].strip() if prev_idx >= 0 else ""
                    )
                    if prev_stripped:
                        prev_code = _code_part(prev_stripped).rstrip()
                        break
                is_continuation = bool(re.search(r"[(&|]{1,2}\s*$", prev_code))
                if not re.search(r"\bif\b", stripped) and not is_continuation:
                    # Report on the USAGE line
                    usage_line_no = line_no + offset
                    issues.append(
                        {
                            "asset_path": file_path,
                            "line": usage_line_no,
                            "class": class_name,
                            "severity": "error",
                            "rule_id": "CS003",
                            "category": "Security",
                            "message": (
                                f"Cast result '{var_name}'"
                                " used without null-check"
                                " — Cast<T> returns "
                                "nullptr if type does "
                                "not match."
                            ),
                            "snippet": stripped,
                            "fix_suggestion": ("Add null-check for " "Cast result"),
                            "is_auto_fixable": _is_fixable("CS003"),
                        }
                    )
            break

    return issues


# CS004: Division without zero-check
def detect_division_no_zero_check(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects float or int division where the divisor is a
    variable without a preceding zero-check guard.
    Dividing by zero crashes the game. Always verify the
    divisor is non-zero before dividing.
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()
        if stripped.startswith("//") or stripped.startswith("#"):
            continue
        # Skip lines with string literals containing paths
        if re.search(r'TEXT\s*\(|"[^"]*[/\\][^"]*"', source_line):
            continue
        # Match: something = something / variable
        div_match = re.search(r"\b\w+\s*/\s*([A-Za-z_]\w*)\b", source_line)
        if not div_match:
            continue

        divisor = div_match.group(1)
        # Skip known safe divisors
        if divisor in {"2", "100", "255"}:
            continue

        # Check if there is a zero-check for this variable
        # in the 5 lines before the division
        start_idx = max(0, line_no - 6)
        preceding = " ".join(source_lines[start_idx : line_no - 1])
        has_check = re.search(
            rf"\b{re.escape(divisor)}\s*[!=]=\s*0"
            rf"|\bFMath::IsNearlyZero\s*\(\s*{re.escape(divisor)}",
            preceding,
        )
        if not has_check:
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": _extract_class_name(
                        content,
                        _char_pos_for_line(source_lines, line_no),
                    ),
                    "severity": "warning",
                    "rule_id": "CS004",
                    "category": "Security",
                    "message": (
                        f"Division by '{divisor}' without "
                        "zero-check — use "
                        "FMath::IsNearlyZero() or check "
                        f"'{divisor} != 0' before dividing."
                    ),
                    "snippet": source_line.strip(),
                    "fix_suggestion": "Add zero-division check",
                    "is_auto_fixable": _is_fixable("CS004"),
                }
            )
    return issues


# CS005: TArray access without bounds check
def detect_array_no_bounds_check(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects TArray subscript access (Array[i]) where no
    IsValidIndex() check appears in the preceding lines.
    Out-of-bounds access on a TArray crashes immediately
    in Debug builds and causes undefined behaviour in
    Shipping. Use IsValidIndex(i) before accessing.

    Lookback window: 15 lines (configurable).
    Loop variables (i, j, k, idx, Index) are only skipped
    when the enclosing for-loop iterates with .Num() of
    the SAME array. Block comments are handled correctly.
    """
    if not _is_cpp(file_path):
        return []

    _LOOKBACK = 15

    issues: List[Issue] = []
    source_lines = content.splitlines()
    in_block_comment = False

    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()

        # Block comment tracking
        if in_block_comment:
            if "*/" in source_line:
                in_block_comment = False
            continue
        if "/*" in stripped:
            after_open = stripped[stripped.find("/*") + 2 :]
            if "*/" not in after_open:
                in_block_comment = True
                continue

        if stripped.startswith("//"):
            continue

        # Match: ArrayVar[SomeVariable] — skip numeric literals
        access_match = re.search(
            r"\b(\w+)\s*\[\s*([A-Za-z_]\w*)\s*\]",
            source_line,
        )
        if not access_match:
            continue

        array_name = access_match.group(1)
        index_var = access_match.group(2)

        # Skip C/C++ keywords and common non-array identifiers
        _SKIP_ARRAYS = {
            "if",
            "for",
            "while",
            "switch",
            "return",
            "sizeof",
            "alignof",
            "decltype",
        }
        if array_name in _SKIP_ARRAYS:
            continue

        # Loop variables are safe ONLY if the enclosing for-loop
        # uses .Num() of the same array as its bound.
        _LOOP_VARS = {"i", "j", "k", "idx", "Index"}
        if index_var in _LOOP_VARS:
            start = max(0, line_no - 1 - _LOOKBACK)
            preceding = " ".join(source_lines[start : line_no - 1])
            safe_loop = re.search(
                rf"for\s*\(.*{re.escape(index_var)}\s*"
                rf".*{re.escape(array_name)}\s*\.\s*Num\(\)",
                preceding,
            )
            if safe_loop:
                continue

        # Check preceding lines for IsValidIndex or Num() guard
        start_idx = max(0, line_no - 1 - _LOOKBACK)
        preceding = " ".join(source_lines[start_idx : line_no - 1])

        # Also check the current line (inline guard pattern)
        preceding_plus = preceding + " " + source_line

        has_check = re.search(
            rf"\b{re.escape(array_name)}\s*\.\s*IsValidIndex\s*"
            rf"\(\s*{re.escape(index_var)}",
            preceding_plus,
        )
        if has_check:
            continue

        # Also accept: if (index_var < Array.Num())
        has_num_guard = re.search(
            rf"\b{re.escape(index_var)}\s*<\s*"
            rf"{re.escape(array_name)}\s*\.\s*Num\(\)",
            preceding_plus,
        )
        if has_num_guard:
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
                "rule_id": "CS005",
                "category": "Security",
                "message": (
                    f"TArray '{array_name}' accessed at "
                    f"index '{index_var}' without "
                    "IsValidIndex() check — will crash "
                    "if index is out of bounds."
                ),
                "snippet": source_line.strip(),
                "fix_suggestion": ("Add bounds check with IsValidIndex()"),
                "is_auto_fixable": _is_fixable("CS005"),
            }
        )
    return issues


# CS006: GetOwner() without null-check
def detect_getowner_no_check(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects GetOwner()-> calls without a null-check guard.
    GetOwner() returns nullptr for Actors that have no owner,
    during shutdown, or in editor utilities. Always guard
    with 'if (AActor* Owner = GetOwner())' before use.
    """
    if not _is_source(file_path):
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
        if re.search(r"\bGetOwner\(\)\s*->", code):
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": _extract_class_name(
                        content,
                        _char_pos_for_line(source_lines, line_no),
                    ),
                    "severity": "warning",
                    "rule_id": "CS006",
                    "category": "Security",
                    "message": (
                        "GetOwner() called without null-check "
                        "— guard with "
                        "'if (AActor* Owner = GetOwner())'."
                    ),
                    "snippet": stripped,
                    "fix_suggestion": ("Add null-check for GetOwner()"),
                    "is_auto_fixable": _is_fixable("CS006"),
                }
            )
    return issues


# CS007: OtherActor used in overlap without null-check
def detect_overlap_actor_no_check(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects OnComponentBeginOverlap or OnActorBeginOverlap
    implementations that use OtherActor directly without a
    null-check. Overlap events can fire with a nullptr
    OtherActor during level streaming or actor destruction.
    Always guard with 'if (OtherActor)' before use.
    """
    if not _is_source(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    # Find overlap function bodies
    overlap_pattern = re.compile(
        r"void\s+\w+::On(?:Component|Actor)Begin" r"(?:Overlap|Hit)\s*\([^)]*\)\s*\{",
    )

    in_overlap_func = False
    brace_depth = 0
    func_start_line = 0

    for line_no, source_line in enumerate(source_lines, start=1):
        if overlap_pattern.search(source_line):
            in_overlap_func = True
            brace_depth = source_line.count("{") - source_line.count("}")
            func_start_line = line_no
            continue

        if in_overlap_func:
            brace_depth += source_line.count("{") - source_line.count("}")
            if brace_depth <= 0:
                in_overlap_func = False
                continue

            # Flag OtherActor-> without a preceding if check
            if re.search(r"\bOtherActor\s*->", source_line):
                # Check if there's a null-check in the function
                func_lines = source_lines[func_start_line : line_no - 1]
                preceding = " ".join(func_lines)
                has_check = re.search(
                    r"\bif\s*\(\s*(?:Other|OtherActor)\b",
                    preceding,
                )
                if not has_check:
                    issues.append(
                        {
                            "asset_path": file_path,
                            "line": line_no,
                            "class": _extract_class_name(
                                content,
                                _char_pos_for_line(source_lines, line_no),
                            ),
                            "severity": "warning",
                            "rule_id": "CS007",
                            "category": "Security",
                            "message": (
                                "OtherActor used in overlap "
                                "callback without null-check "
                                "— guard with "
                                "'if (OtherActor)' first."
                            ),
                            "snippet": source_line.strip(),
                            "fix_suggestion": ("Add null-check for OtherActor"),
                            "is_auto_fixable": _is_fixable("CS007"),
                        }
                    )
    return issues


# CS008: TWeakObjectPtr dereferenced without IsValid()
def detect_weak_ptr_no_check(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects TWeakObjectPtr variables dereferenced with .Get()
    or -> without a preceding IsValid() check.
    TWeakObjectPtr can become invalid at any time if the
    referenced UObject is garbage collected. Always check
    IsValid() before dereferencing.
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    # Find TWeakObjectPtr variable declarations
    weak_ptr_pattern = re.compile(r"\bTWeakObjectPtr\s*<[^>]+>\s*(\w+)\s*[;=]")

    # Collect all weak ptr variable names in the file
    weak_ptr_vars: List[str] = []
    for source_line in source_lines:
        weak_match = weak_ptr_pattern.search(source_line)
        if weak_match:
            weak_ptr_vars.append(weak_match.group(1))

    if not weak_ptr_vars:
        return issues

    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()
        if stripped.startswith("//"):
            continue

        for var_name in weak_ptr_vars:
            # Detect .Get() or -> dereference
            if not re.search(
                rf"\b{re.escape(var_name)}" rf"\s*(?:\.Get\(\)|->)",
                source_line,
            ):
                continue

            # Check preceding 5 lines for IsValid()
            start_idx = max(0, line_no - 6)
            preceding = " ".join(source_lines[start_idx : line_no - 1])
            has_check = re.search(
                rf"\b{re.escape(var_name)}" rf"\s*\.\s*IsValid\s*\(\)",
                preceding,
            )
            if not has_check:
                issues.append(
                    {
                        "asset_path": file_path,
                        "line": line_no,
                        "class": _extract_class_name(
                            content,
                            _char_pos_for_line(source_lines, line_no),
                        ),
                        "severity": "error",
                        "rule_id": "CS008",
                        "category": "Security",
                        "message": (
                            f"TWeakObjectPtr '{var_name}' "
                            "dereferenced without IsValid() "
                            "check — the object may have "
                            "been garbage collected."
                        ),
                        "snippet": source_line.strip(),
                        "fix_suggestion": ("Check IsValid() before " "dereferencing"),
                        "is_auto_fixable": _is_fixable("CS008"),
                    }
                )
    return issues


# CS011: HTTP request using http:// instead of https://
def detect_http_insecure(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects HTTP requests using http:// instead of https://.
    Unencrypted connections expose data to interception.
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()
        if stripped.startswith("//"):
            continue

        # Match http:// in string literals (not https://)
        if re.search(r'["\']http://[^"\']+["\']', source_line):
            # Skip localhost which is often acceptable
            if "localhost" in source_line or "127.0.0.1" in source_line:
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
                    "rule_id": "CS011",
                    "category": "Security",
                    "message": (
                        "Insecure http:// URL — use https://"
                        " to encrypt data in transit."
                    ),
                    "snippet": source_line.strip(),
                    "fix_suggestion": ("Replace http:// with https://"),
                    "is_auto_fixable": _is_fixable("CS011"),
                }
            )

    return issues


# CS012: Hardcoded password or API key
def detect_hardcoded_secret(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects hardcoded passwords, API keys, or secrets in code.
    Secrets should be stored in config files or environment
    variables, never in source code.
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    # Patterns that suggest hardcoded secrets
    secret_patterns = [
        (
            r'\bPassword\s*=\s*TEXT\s*\(\s*"[^"]+"\s*\)',
            "password",
        ),
        (
            r'\bApiKey\s*=\s*TEXT\s*\(\s*"[^"]+"\s*\)',
            "API key",
        ),
        (
            r'\bSecret\s*=\s*TEXT\s*\(\s*"[^"]+"\s*\)',
            "secret",
        ),
        (
            r'\bToken\s*=\s*TEXT\s*\(\s*"[^"]+"\s*\)',
            "token",
        ),
        (
            r'\bPrivateKey\s*=\s*TEXT\s*\(\s*"[^"]+"\s*\)',
            "private key",
        ),
    ]

    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()
        if stripped.startswith("//"):
            continue

        for pattern, secret_type in secret_patterns:
            if re.search(pattern, source_line, re.IGNORECASE):
                issues.append(
                    {
                        "asset_path": file_path,
                        "line": line_no,
                        "class": _extract_class_name(
                            content,
                            _char_pos_for_line(source_lines, line_no),
                        ),
                        "severity": "error",
                        "rule_id": "CS012",
                        "category": "Security",
                        "message": (
                            f"Hardcoded {secret_type} "
                            "detected — store secrets in "
                            "config or environment "
                            "variables, never in source "
                            "code."
                        ),
                        "snippet": source_line.strip(),
                        "fix_suggestion": ("Comment out hardcoded secret"),
                        "is_auto_fixable": _is_fixable("CS012"),
                    }
                )
                break

    return issues
