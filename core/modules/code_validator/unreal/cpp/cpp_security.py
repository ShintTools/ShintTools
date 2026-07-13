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
#   CS013  GetPlayerController() without null-check
#   CS014  GetGameInstance() without null-check
#   CS015  GetPlayerState() without null-check
#   CS016  Server RPC without WithValidation
#   CS017  Client RPC modifying replicated state
# Total: 15 rules

import re
from typing import List

from code_validator.unreal.cpp._cpp_helpers import (
    Issue,
    _char_pos_for_line,
    _code_part,
    _extract_class_name,
    _is_comment_line,
    _is_cpp,
    _is_fixable,
    _is_header,
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
                "severity": "info",
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

        # CastChecked<T> / ExactCast<T> are deliberately-checked idioms:
        # CastChecked asserts non-null internally (check()), so using the
        # result directly is the *correct* usage, not a missing null-check.
        # Never treat a checked cast as a defect.
        if re.search(r"\b(?:CastChecked|ExactCast)\s*<", source_line):
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
                            "severity": "warning",
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

    Detection: 15-line lookback. Loop variables (i, j, k,
    idx, Index) are only skipped when the enclosing for-loop
    iterates with .Num() of the SAME array.
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

        # Match: ArrayVar[<any non-empty expression>]
        # Captures identifiers, arithmetic (i+1), and calls
        # (GetIndex()). Skips numeric literals and string keys.
        access_match = re.search(
            r"\b(\w+)\s*\[\s*([^\]\n]+?)\s*\]",
            source_line,
        )
        if not access_match:
            continue

        array_name = access_match.group(1)
        index_expr = access_match.group(2).strip()

        # Skip pure numeric literals — those are compile-time
        # constants and the dev knows what they're doing.
        if re.fullmatch(r"\d+", index_expr):
            continue

        # Skip string keys (TMap lookups, not TArray access).
        if index_expr.startswith('"') or index_expr.startswith("'"):
            continue

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
        # uses .Num() of the same array as its bound. Only applies
        # when the index is a bare loop variable, not an expression.
        _LOOP_VARS = {"i", "j", "k", "idx", "Index"}
        if index_expr in _LOOP_VARS:
            start = max(0, line_no - 1 - _LOOKBACK)
            preceding = " ".join(source_lines[start : line_no - 1])
            safe_loop = re.search(
                rf"for\s*\(.*{re.escape(index_expr)}\s*"
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
            rf"\(\s*{re.escape(index_expr)}",
            preceding_plus,
        )
        if has_check:
            continue

        # Also accept: if (index_expr < Array.Num())
        has_num_guard = re.search(
            rf"{re.escape(index_expr)}\s*<\s*"
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
                "severity": "info",
                "rule_id": "CS005",
                "category": "Security",
                "message": (
                    f"TArray '{array_name}' accessed at "
                    f"index '{index_expr}' without "
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
                    "severity": "info",
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


# CS013: GetPlayerController() without null-check
def detect_player_controller_no_check(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects GetPlayerController()-> or GetController()->
    calls without a null-check guard.
    GetPlayerController() returns nullptr on dedicated servers,
    during level transitions, or when no local player exists
    (e.g. spectator-only mode). Always guard with
    'if (APlayerController* PC = ...)' before dereferencing.

    Lookback: scans the preceding 10 lines for safe
    guard patterns to avoid false positives.
    """
    if not _is_source(file_path):
        return []

    _LOOKBACK = 10

    # Patterns that prove the call was already guarded
    _GUARD_RE = re.compile(
        r"if\s*\(\s*(?:APlayerController\s*\*\s*\w+\s*=\s*)?"
        r"(?:GetPlayerController|GetController)\s*(?:<[^>]*>)?\s*\("
        r"|"
        r"(?:APlayerController\s*\*\s*\w+\s*=\s*"
        r"(?:GetPlayerController|GetController)\s*(?:<[^>]*>)?\s*\()"
    )

    _CALL_RE = re.compile(
        r"\b(?:GetPlayerController|GetController)" r"\s*(?:<[^>]*>)?\s*\([^)]*\)\s*->"
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
            after_open = stripped[stripped.find("/*") + 2 :]
            if "*/" not in after_open:
                in_block_comment = True
                continue
        if _is_comment_line(stripped):
            continue

        code = _code_part(source_line)
        if not _CALL_RE.search(code):
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
                "severity": "error",
                "rule_id": "CS013",
                "category": "Security",
                "message": (
                    "GetPlayerController() called without "
                    "null-check — returns nullptr on "
                    "dedicated servers and during level "
                    "transitions. Guard with "
                    "'if (APlayerController* PC = "
                    "GetPlayerController(0))'."
                ),
                "snippet": stripped,
                "fix_suggestion": ("Add null-check for GetPlayerController()"),
                "is_auto_fixable": _is_fixable("CS013"),
            }
        )
    return issues


# CS014: GetGameInstance() without null-check
def detect_game_instance_no_check(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects GetGameInstance()-> calls without a null-check.
    GetGameInstance() returns nullptr during engine shutdown,
    in commandlets, and in certain editor utilities.
    Always guard with
    'if (UGameInstance* GI = GetGameInstance())' before use.

    Lookback: scans the preceding 10 lines for safe
    guard patterns to avoid false positives.
    """
    if not _is_source(file_path):
        return []

    _LOOKBACK = 10

    _GUARD_RE = re.compile(
        r"if\s*\(\s*(?:UGameInstance\s*\*\s*\w+\s*=\s*)?"
        r"GetGameInstance\s*\("
        r"|"
        r"(?:UGameInstance\s*\*\s*\w+\s*=\s*"
        r"GetGameInstance\s*\()"
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
            after_open = stripped[stripped.find("/*") + 2 :]
            if "*/" not in after_open:
                in_block_comment = True
                continue
        if _is_comment_line(stripped):
            continue

        code = _code_part(source_line)
        if not re.search(r"\bGetGameInstance\s*\(\s*\)\s*->", code):
            continue

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
                "rule_id": "CS014",
                "category": "Security",
                "message": (
                    "GetGameInstance() called without "
                    "null-check — returns nullptr during "
                    "engine shutdown and in commandlets. "
                    "Guard with "
                    "'if (UGameInstance* GI = "
                    "GetGameInstance())'."
                ),
                "snippet": stripped,
                "fix_suggestion": ("Add null-check for GetGameInstance()"),
                "is_auto_fixable": _is_fixable("CS014"),
            }
        )
    return issues


# CS015: GetPlayerState() without null-check
def detect_player_state_no_check(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects GetPlayerState()-> calls without a null-check.
    GetPlayerState() returns nullptr before the player has
    fully joined (common in multiplayer), during seamless
    travel, and on dedicated servers for AI controllers.
    Always guard with
    'if (auto* PS = GetPlayerState<AMyPlayerState>())'
    before dereferencing.

    Lookback: scans the preceding 10 lines for safe
    guard patterns to avoid false positives.
    """
    if not _is_source(file_path):
        return []

    _LOOKBACK = 10

    _GUARD_RE = re.compile(
        r"if\s*\(\s*(?:auto\s*\*\s*\w+\s*=\s*)?"
        r"GetPlayerState\s*(?:<[^>]*>)?\s*\("
        r"|"
        r"(?:(?:auto|A\w+)\s*\*\s*\w+\s*=\s*"
        r"GetPlayerState\s*(?:<[^>]*>)?\s*\()"
    )

    _CALL_RE = re.compile(r"\bGetPlayerState\s*(?:<[^>]*>)?\s*\(\s*\)\s*->")

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
            after_open = stripped[stripped.find("/*") + 2 :]
            if "*/" not in after_open:
                in_block_comment = True
                continue
        if _is_comment_line(stripped):
            continue

        code = _code_part(source_line)
        if not _CALL_RE.search(code):
            continue

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
                "severity": "error",
                "rule_id": "CS015",
                "category": "Security",
                "message": (
                    "GetPlayerState() called without "
                    "null-check — returns nullptr before "
                    "player has fully joined in multiplayer "
                    "and on dedicated servers for AI. "
                    "Guard with "
                    "'if (auto* PS = "
                    "GetPlayerState<T>())'."
                ),
                "snippet": stripped,
                "fix_suggestion": ("Add null-check for GetPlayerState()"),
                "is_auto_fixable": _is_fixable("CS015"),
            }
        )
    return issues


# CS016: Server RPC without WithValidation
def detect_server_rpc_no_validate(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects UFUNCTION(Server, Reliable / Unreliable) declarations that
    lack WithValidation. Without a _Validate function, a malicious
    client can send arbitrary parameters to the server RPC. Epic
    recommends always using WithValidation for Server RPCs.

    Detection: checks both the UFUNCTION macro and the file body for
    a matching _Validate implementation to reduce false positives.
    """
    if not _is_header(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    # Regex: UFUNCTION(...Server...) without WithValidation
    server_rpc_re = re.compile(r"UFUNCTION\s*\([^)]*\bServer\b[^)]*\)")

    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()
        if stripped.startswith("//"):
            continue

        if not server_rpc_re.search(source_line):
            continue

        # Already has WithValidation — skip
        if "WithValidation" in source_line:
            continue

        # Get the function name from the next non-empty, non-comment line
        func_name = ""
        for next_idx in range(line_no, min(line_no + 3, len(source_lines))):
            next_line = source_lines[next_idx].strip()
            if not next_line or next_line.startswith("//"):
                continue
            func_match = re.search(r"\b(\w+)\s*\(", next_line)
            if func_match:
                func_name = func_match.group(1)
            break

        # Check if a _Validate function exists in the file
        validate_name = func_name + "_Validate" if func_name else ""
        has_validate = validate_name and validate_name in content

        if has_validate:
            continue

        issues.append(
            {
                "asset_path": file_path,
                "line": line_no,
                "class": _extract_class_name(
                    content,
                    _char_pos_for_line(source_lines, line_no),
                ),
                "severity": "error",
                "rule_id": "CS016",
                "category": "Security",
                "message": (
                    f"Server RPC '{func_name}' lacks "
                    "WithValidation — a malicious client "
                    "can send arbitrary parameters. Add "
                    "WithValidation and implement "
                    f"{func_name}_Validate()."
                ),
                "snippet": stripped,
                "fix_suggestion": (
                    "Add WithValidation to UFUNCTION and "
                    f"implement {func_name}_Validate()"
                ),
                "is_auto_fixable": False,
            }
        )

    return issues


# CS017: Client RPC modifying replicated state
def detect_client_rpc_modifies_replicated(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects Client RPC implementations that assign to variables
    known to be UPROPERTY(Replicated). Client RPCs run on the
    owning client — modifying replicated state from the client
    causes desync because the server's version overwrites it on
    the next replication tick.

    Detection: scans the header for UPROPERTY(Replicated*) variable
    names, then checks Client RPC bodies in the source for
    assignments to those variables.
    """
    if not _is_source(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    # Step 1: Find all replicated variable names from UPROPERTY
    # macros in this file (some projects put UPROPERTY in .cpp
    # for generated code; also handles combined .h/.cpp analysis).
    replicated_vars: set = set()
    uproperty_re = re.compile(r"UPROPERTY\s*\([^)]*\bReplicated\w*[^)]*\)")
    var_decl_re = re.compile(r"^\s*(?:[\w:<>*&]+\s+)+(\w+)\s*(?:=\s*[^;]*)?\s*;")

    for i, line in enumerate(source_lines):
        if uproperty_re.search(line):
            # Variable is on the next non-empty, non-comment line
            for j in range(i + 1, min(i + 4, len(source_lines))):
                candidate = source_lines[j].strip()
                if not candidate or candidate.startswith("//"):
                    continue
                var_match = var_decl_re.match(source_lines[j])
                if var_match:
                    replicated_vars.add(var_match.group(1))
                break

    if not replicated_vars:
        return issues

    # Step 2: Find Client RPC function bodies
    # Pattern: void ClassName::FuncName_Implementation(...)
    # where FuncName was declared with UFUNCTION(Client)
    client_impl_re = re.compile(
        r"void\s+(\w+)::(\w+_Implementation)\s*\([^)]*\)\s*"
        r"\{([^}]*(?:\{[^}]*\}[^}]*)*)\}",
        re.DOTALL,
    )

    # We also check if the function name starts with "Client"
    # (UE5 convention for client RPCs)
    for impl_match in client_impl_re.finditer(content):
        class_name = impl_match.group(1)
        func_name = impl_match.group(2)
        body = impl_match.group(3)

        # Only check functions that follow client RPC naming
        base_name = func_name.replace("_Implementation", "")
        if not base_name.startswith("Client"):
            continue

        # Check if body assigns to any replicated variable
        body_start = impl_match.start(3)
        for var_name in replicated_vars:
            assign_re = re.compile(rf"\b{re.escape(var_name)}\s*(?:=|\+=|-=|\*=|/=)")
            assign_match = assign_re.search(body)
            if not assign_match:
                continue

            abs_pos = body_start + assign_match.start()
            line_no = content[:abs_pos].count("\n") + 1

            # Check it's not inside a comment
            if line_no <= len(source_lines):
                line_text = source_lines[line_no - 1].strip()
                if line_text.startswith("//"):
                    continue
            else:
                line_text = ""

            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": class_name,
                    "severity": "error",
                    "rule_id": "CS017",
                    "category": "Security",
                    "message": (
                        f"Client RPC '{base_name}' modifies "
                        f"replicated variable '{var_name}' — "
                        "client-side writes to replicated "
                        "state cause desync. Only the server "
                        "should modify replicated variables."
                    ),
                    "snippet": line_text,
                    "fix_suggestion": (
                        f"Move '{var_name}' assignment to a "
                        "Server RPC or remove it from the "
                        "Client RPC"
                    ),
                    "is_auto_fixable": False,
                }
            )

    return issues
