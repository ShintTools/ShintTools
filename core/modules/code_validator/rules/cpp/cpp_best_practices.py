# core/modules/code_validator/rules/cpp/cpp_best_practices.py
#
# Best Practices rules (CB001-CB032) for Unreal Engine 5 C++.
# Detects anti-patterns, unsafe constructs, and deviations
# from Epic's coding standard.
#
# Rule Index:
#   CB001: Infinite loop without exit condition
#   CB002: Synchronous asset load outside init
#   CB003: Raw 'new' detected
#   CB004: Raw 'delete' detected
#   CB005: STL type usage
#   CB006: printf usage
#   CB007: System header included
#   CB008: Float literal without 'f' suffix
#   CB009: UPROPERTY initialized to nullptr in declaration
#   CB010: Magic number literal
#   CB011: Empty if-body (dead branch)
#   CB012: C-style cast
#   CB013: Nullptr dereference risk
#   CB014: Hardcoded absolute path
#   CB015: Auto without obvious type
#   CB016: String concatenation in loop
#   CB017: Public member without UPROPERTY
#   CB018: Raw C array (use TArray)
#   CB019: Non-virtual destructor on polymorphic class
#   CB020: FString used for identifier (prefer FName)
#   CB021: Lambda with implicit capture [&] or [=]
#   CB022: ensure() without Always variant
#   CB023: Virtual function without override keyword
#   CB024: BeginPlay without Super:: call
#   CB025: UFUNCTION BlueprintCallable without Category
#   CB026: UPROPERTY(ExposeOnSpawn) without default value
#   CB028: SetTimer with lambda capturing 'this'
#   CB029: UE_LOG Verbose without shipping guard
#   CB030: String literal in UPROPERTY without TEXT()
#   CB031: BlueprintPure function with side effects
#   CB032: const reference in UPROPERTY
#   CB033: EndPlay without Super:: call
#   CB034: Raw pointer in UPROPERTY (use TObjectPtr)
#   CB035: UPROPERTY EditAnywhere without Category

import re
from typing import List

from code_validator.rules.cpp._cpp_helpers import (
    Issue,
    _char_pos_for_line,
    _code_part,
    _extract_class_name,
    _get_line_number,
    _is_comment_line,
    _is_cpp,
    _is_fixable,
    _is_header,
    _is_source,
)


# CB001: Infinite loop without exit condition
def detect_infinite_loop(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects while(true) or for(;;) loops without a break,
    return or goto statement inside the body.
    These will freeze the game thread indefinitely.
    """
    issues: List[Issue] = []
    loop_pattern = re.compile(
        r"(?:while\s*\(\s*true\s*\)|for\s*\(\s*;;\s*\))"
        r"\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}",
        re.DOTALL,
    )
    for loop_match in loop_pattern.finditer(content):
        loop_body = loop_match.group(1)
        has_exit = re.search(r"\b(?:break|return|goto)\b", loop_body)
        if not has_exit:
            line_no = _get_line_number(content, loop_match.start())
            class_name = _extract_class_name(content, loop_match.start())
            snippet_line = (
                content.splitlines()[line_no - 1].strip()
                if line_no <= len(content.splitlines())
                else ""
            )
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": class_name,
                    "severity": "error",
                    "rule_id": "CB001",
                    "category": "Best Practices",
                    "message": (
                        "Infinite loop without break/return. " "Game thread will freeze"
                    ),
                    "snippet": snippet_line,
                    "fix_suggestion": "Comment out dangerous infinite loop",
                    "is_auto_fixable": _is_fixable("CB001"),
                }
            )
    return issues


# CB002: Synchronous asset load outside init
def detect_runtime_load(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects synchronous asset loading calls outside of
    initialization functions like BeginPlay or Constructor.
    These cause frame hitches at runtime. Use async
    loading via FStreamableManager instead.
    """
    issues: list[Issue] = []
    load_pattern = re.compile(
        r"\b(?:StaticLoadObject|LoadObject|" r"FSoftObjectPath|RequestSyncLoad)\s*[<(]"
    )
    init_pattern = re.compile(
        r"void\s+\w+::" r"(?:BeginPlay|Constructor|PostInitializeComponents)" r"\s*\("
    )
    load_matches = list(load_pattern.finditer(content))
    if not load_matches:
        return issues

    # Find the character ranges of all init functions
    init_ranges = []
    for init_match in init_pattern.finditer(content):
        range_start = init_match.start()
        brace_depth = 0
        for char_idx, char in enumerate(content[range_start:]):
            if char == "{":
                brace_depth += 1
            elif char == "}":
                brace_depth -= 1
                if brace_depth == 0:
                    init_ranges.append((range_start, range_start + char_idx))
                    break

    # Flag any load call outside an init function
    for load_match in load_matches:
        call_pos = load_match.start()
        inside_init = any(s <= call_pos <= e for s, e in init_ranges)
        if not inside_init:
            line_no = _get_line_number(content, call_pos)
            class_name = _extract_class_name(content, call_pos)
            snippet_line = (
                content.splitlines()[line_no - 1].strip()
                if line_no <= len(content.splitlines())
                else ""
            )
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": class_name,
                    "severity": "warning",
                    "rule_id": "CB002",
                    "category": "Best Practices",
                    "message": (
                        "Synchronous asset load outside "
                        "BeginPlay/Constructor. "
                        "Use async loading instead"
                    ),
                    "snippet": snippet_line,
                    "fix_suggestion": "Comment out synchronous load call",
                    "is_auto_fixable": _is_fixable("CB002"),
                }
            )
    return issues


# CB003: Raw 'new' detected
def detect_raw_new(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects raw 'new' keyword usage. In UE5, objects should
    be created with NewObject<T>() or
    CreateDefaultSubobject<T>(). Raw new bypasses the garbage
    collector and causes memory leaks.
    """
    if not _is_cpp(file_path):
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
        if re.search(r"\bnew\s+\w", code):
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": _extract_class_name(
                        content,
                        _char_pos_for_line(source_lines, line_no),
                    ),
                    "severity": "error",
                    "rule_id": "CB003",
                    "category": "Best Practices",
                    "message": (
                        "Raw 'new' detected — use NewObject<T>()"
                        " or CreateDefaultSubobject<T>() instead."
                    ),
                    "snippet": source_line.strip(),
                    "fix_suggestion": "Replace raw new with NewObject<T>(this)",
                    "is_auto_fixable": _is_fixable("CB003"),
                }
            )
    return issues


# CB004: Raw 'delete' detected
def detect_raw_delete(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects raw 'delete' keyword usage. UObjects are managed
    by UE5's garbage collector. Calling delete on them causes
    crashes.
    """
    if not _is_cpp(file_path):
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
        if re.search(r"\bdelete\s+\w", code):
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": _extract_class_name(
                        content,
                        _char_pos_for_line(source_lines, line_no),
                    ),
                    "severity": "error",
                    "rule_id": "CB004",
                    "category": "Best Practices",
                    "message": (
                        "Raw 'delete' detected — UObjects are "
                        "garbage-collected; manual delete will "
                        "crash."
                    ),
                    "snippet": source_line.strip(),
                    "fix_suggestion": "Comment out raw delete",
                    "is_auto_fixable": _is_fixable("CB004"),
                }
            )
    return issues


# CB005: STL type usage
def detect_stl_usage(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects usage of std:: types. UE5 has its own containers
    (TArray, TMap, FString) that integrate with the engine's
    memory management, serialization and reflection systems.
    """
    if not _is_cpp(file_path):
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
        if re.search(r"\bstd::\w", code):
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": _extract_class_name(
                        content,
                        _char_pos_for_line(source_lines, line_no),
                    ),
                    "severity": "warning",
                    "rule_id": "CB005",
                    "category": "Best Practices",
                    "message": (
                        "STL type detected — prefer UE "
                        "equivalents (TArray, TMap, FString...)."
                    ),
                    "snippet": source_line.strip(),
                    "fix_suggestion": "Replace STL type with UE5 equivalent",
                    "is_auto_fixable": _is_fixable("CB005"),
                }
            )
    return issues


# CB006: printf usage
def detect_printf(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects printf() calls. UE5 uses UE_LOG() for logging,
    which supports log categories, verbosity levels, and
    integrates with the output log window in the editor.
    """
    if not _is_cpp(file_path):
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
        if re.search(r"\bprintf\s*\(", code):
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": _extract_class_name(
                        content,
                        _char_pos_for_line(source_lines, line_no),
                    ),
                    "severity": "warning",
                    "rule_id": "CB006",
                    "category": "Best Practices",
                    "message": ("printf() detected — use UE_LOG() " "instead."),
                    "snippet": source_line.strip(),
                    "fix_suggestion": "Replace printf with UE_LOG",
                    "is_auto_fixable": _is_fixable("CB006"),
                }
            )
    return issues


# CB007: System header included
def detect_system_headers(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects #include of system headers (angle brackets).
    UE5 has its own module system; prefer UE module headers.
    Exceptions: stdint, limits, cmath, cassert.
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []
    for line_no, source_line in enumerate(content.splitlines(), start=1):
        if re.search(
            r"#include\s+<(?!stdint|limits|cmath|cassert)",
            source_line,
        ):
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": "Unknown",
                    "severity": "warning",
                    "rule_id": "CB007",
                    "category": "Best Practices",
                    "message": (
                        "System header included — " "prefer UE module headers."
                    ),
                    "snippet": source_line.strip(),
                    "fix_suggestion": "Comment out non-UE system header",
                    "is_auto_fixable": _is_fixable("CB007"),
                }
            )
    return issues


# CB008: Float literal without 'f' suffix
def detect_float_no_suffix(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects float variables assigned a decimal literal without
    the 'f' suffix (e.g. 1.0 instead of 1.0f). Without the
    suffix, the compiler treats the literal as a double,
    causing an implicit promotion that wastes CPU cycles.
    """
    if not _is_cpp(file_path):
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
        # Use code-only portion so patterns inside // comments are ignored
        code = _code_part(source_line)
        # Pattern: float declaration assigned a decimal literal without 'f' suffix.
        # Negative lookahead so 1.0f, 1.0e5, etc. are not re-flagged.
        if re.search(
            r"\bfloat\b\s+\w+\s*=\s*[0-9]+\.[0-9]+(?![fe])",
            code,
        ):
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": _extract_class_name(
                        content,
                        _char_pos_for_line(source_lines, line_no),
                    ),
                    "severity": "warning",
                    "rule_id": "CB008",
                    "category": "Best Practices",
                    "message": (
                        "Float literal without 'f' suffix — "
                        "add 'f' (e.g. 1.0f) to avoid double "
                        "promotion."
                    ),
                    "snippet": source_line.strip(),
                    "fix_suggestion": "Add f suffix to float literal",
                    "is_auto_fixable": _is_fixable("CB008"),
                }
            )
    return issues


# CB009: UPROPERTY initialized to nullptr in declaration
def detect_uproperty_nullptr(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects UPROPERTY pointers initialized to nullptr directly
    in the declaration. In UE5, UPROPERTY members should be
    initialized in the constructor body so the reflection
    system and CDO handle them properly.
    """
    if not _is_header(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()
    for line_no, source_line in enumerate(source_lines, start=1):
        if re.search(
            r"UPROPERTY\([^)]*\)\s*\w+\s*\*\s*\w+\s*=" r"\s*nullptr",
            source_line,
        ):
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": _extract_class_name(
                        content,
                        _char_pos_for_line(source_lines, line_no),
                    ),
                    "severity": "error",
                    "rule_id": "CB009",
                    "category": "Best Practices",
                    "message": (
                        "UPROPERTY initialized to nullptr in "
                        "declaration — initialize in constructor "
                        "body."
                    ),
                    "snippet": source_line.strip(),
                    "fix_suggestion": "Remove = nullptr from declaration",
                    "is_auto_fixable": _is_fixable("CB009"),
                }
            )
    return issues


# CB010: Magic number literal
def detect_magic_numbers(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects numeric literals used directly in expressions
    without being assigned to a named constant.
    Magic numbers reduce readability and make the code hard
    to maintain. Extract them to named constexpr constants.
    Skips 0, 1, -1 and values inside array declarations.
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    # Matches a bare numeric literal in an expression context.
    # Excludes: 0, 1, -1, array sizes, loop counters.
    magic_pattern = re.compile(
        r"(?<![A-Za-z0-9_])"
        r"(?<!\.)"
        r"(-?\b(?:[2-9]\d*|1\d+)\b(?:\.\d+)?f?)"
        r"(?!\s*\])"
        r"(?![A-Za-z0-9_])"
    )

    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()
        # Skip comments, includes, define lines
        if stripped.startswith("//") or stripped.startswith("#"):
            continue
        # Skip constexpr / const declarations — they ARE the named constant
        if re.search(r"\bconstexpr\b|\bconst\b.*=", stripped):
            continue

        magic_match = magic_pattern.search(stripped)
        if magic_match:
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": _extract_class_name(
                        content,
                        _char_pos_for_line(source_lines, line_no),
                    ),
                    "severity": "warning",
                    "rule_id": "CB010",
                    "category": "Best Practices",
                    "message": (
                        f"Magic number '{magic_match.group(1)}' — "
                        "extract to a named constexpr constant."
                    ),
                    "snippet": source_line.strip(),
                    "fix_suggestion": "Extract to named constexpr constant",
                    "is_auto_fixable": _is_fixable("CB010"),
                }
            )
    return issues


# CB011: Empty if-body (dead branch)
def detect_empty_if_body(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects if-statements with an empty body {}.
    Empty branches are dead code — they either indicate
    unfinished logic or a forgotten implementation.
    Remove the branch or add the intended logic.
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    for line_no, source_line in enumerate(source_lines, start=1):
        # Detect: if (...) followed by opening brace on same or next line,
        # then immediately a closing brace with nothing in between.
        if not re.search(r"\bif\s*\(", source_line):
            continue

        # Check same-line empty body: if (...) {}
        if re.search(r"\bif\s*\([^)]*\)\s*\{\s*\}", source_line):
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": _extract_class_name(
                        content,
                        _char_pos_for_line(source_lines, line_no),
                    ),
                    "severity": "warning",
                    "rule_id": "CB011",
                    "category": "Best Practices",
                    "message": (
                        "Empty if-body detected — remove the "
                        "branch or add the intended logic."
                    ),
                    "snippet": source_line.strip(),
                    "fix_suggestion": "Remove empty if-body (dead code)",
                    "is_auto_fixable": _is_fixable("CB011"),
                }
            )
            continue

        # Check multi-line empty body: if (...)\n{\n}
        if line_no + 2 <= len(source_lines):
            next_line = source_lines[line_no].strip()
            after_next = source_lines[line_no + 1].strip()
            if next_line == "{" and after_next == "}":
                issues.append(
                    {
                        "asset_path": file_path,
                        "line": line_no,
                        "class": _extract_class_name(
                            content,
                            _char_pos_for_line(source_lines, line_no),
                        ),
                        "severity": "warning",
                        "rule_id": "CB011",
                        "category": "Best Practices",
                        "message": (
                            "Empty if-body detected — remove the "
                            "branch or add the intended logic."
                        ),
                        "snippet": source_line.strip(),
                        "fix_suggestion": "Remove empty if-body (dead code)",
                        "is_auto_fixable": _is_fixable("CB011"),
                    }
                )
    return issues


# CB012: C-style cast
def detect_c_style_cast(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects C-style casts like (int32)value or (float)x.
    In UE5, prefer static_cast<T>(), Cast<T>() for UObjects,
    or StaticCast<T>() for checked casts. C-style casts bypass
    type safety checks and hide bugs.
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    # Detection: (TypeName) followed by a word character.
    # Use lookahead (?=\s*\w) so the variable's first character is NOT consumed,
    # which previously caused the fix to lose it.
    _CAST_TYPES = (
        r"int8|int16|int32|int64|uint8|uint16|uint32|uint64"
        r"|float|double|bool|char|TCHAR|SIZE_T"
    )
    cast_detect = re.compile(r"\(\s*(?:" + _CAST_TYPES + r")\s*\)(?=\s*\w)")

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
        cast_match = cast_detect.search(code)
        if cast_match:
            # Extract type name for the message
            type_match = re.search(r"\(\s*(\w+)\s*\)", cast_match.group(0))
            type_name = type_match.group(1) if type_match else "T"
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": _extract_class_name(
                        content,
                        _char_pos_for_line(source_lines, line_no),
                    ),
                    "severity": "warning",
                    "rule_id": "CB012",
                    "category": "Best Practices",
                    "message": (
                        f"C-style cast to '{type_name}' — use "
                        "static_cast<T>() or Cast<T>() instead."
                    ),
                    "snippet": stripped,
                    "fix_suggestion": "Use static_cast instead of C-style cast",
                    "is_auto_fixable": _is_fixable("CB012"),
                }
            )
    return issues


# CB013: Nullptr dereference risk
def detect_nullptr_deref(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects pointers assigned nullptr that are then dereferenced
    on the next non-empty line without a null-check guard.
    Dereferencing nullptr crashes the game immediately.
    Always check pointers before use.
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    for line_no, source_line in enumerate(source_lines, start=1):
        # Find: Type* VarName = nullptr;
        null_assign = re.search(
            r"\b(\w+)\s*\*\s*(\w+)\s*=\s*nullptr\s*;",
            source_line,
        )
        if not null_assign:
            continue

        var_name = null_assign.group(2)

        # Check the next 5 non-empty lines for unguarded dereference
        for offset, next_line in enumerate(
            source_lines[line_no : line_no + 5], start=1
        ):
            next_stripped = next_line.strip()
            if not next_stripped:
                continue
            if re.search(rf"\b{re.escape(var_name)}\s*->", next_stripped):
                prev_code = ""
                for prev_idx in range(line_no + offset - 2, max(line_no - 1, -1), -1):
                    prev_stripped = (
                        source_lines[prev_idx].strip() if prev_idx >= 0 else ""
                    )
                    if prev_stripped:
                        prev_code = _code_part(prev_stripped).rstrip()
                        break
                is_continuation = bool(re.search(r"[(&|]{1,2}\s*$", prev_code))
                if not re.search(r"\bif\b", next_stripped) and not is_continuation:
                    # Report on the USAGE line so fix replaces the right line
                    usage_line_no = line_no + offset
                    issues.append(
                        {
                            "asset_path": file_path,
                            "line": usage_line_no,
                            "class": _extract_class_name(
                                content,
                                _char_pos_for_line(source_lines, line_no),
                            ),
                            "severity": "error",
                            "rule_id": "CB013",
                            "category": "Best Practices",
                            "message": (
                                f"'{var_name}' assigned nullptr "
                                "and dereferenced without null-"
                                "check — will crash at runtime."
                            ),
                            "snippet": next_stripped,
                            "fix_suggestion": "Add null-check before dereference",
                            "is_auto_fixable": _is_fixable("CB013"),
                        }
                    )
            break
    return issues


# CB014: Hardcoded absolute path
def detect_hardcoded_path(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects hardcoded absolute paths in string literals.
    Hardcoded paths break cross-platform builds and team
    collaboration. Use FPaths helpers (FPaths::ProjectDir(),
    FPaths::GameDir()) or relative paths instead.
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()
    # Matches Windows or Unix absolute paths inside TEXT("...") or "..."
    path_pattern = re.compile(
        r'TEXT\s*\(\s*"(?:[A-Za-z]:\\|/(?:home|usr|var|tmp|Users)'
        r')[^"]*"\s*\)'
        r'|"(?:[A-Za-z]:\\|/(?:home|usr|var|tmp|Users))[^"]*"'
    )

    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()
        if stripped.startswith("//"):
            continue
        if path_pattern.search(source_line):
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": _extract_class_name(
                        content,
                        _char_pos_for_line(source_lines, line_no),
                    ),
                    "severity": "warning",
                    "rule_id": "CB014",
                    "category": "Best Practices",
                    "message": (
                        "Hardcoded absolute path detected — "
                        "use FPaths::ProjectDir() or relative "
                        "paths instead."
                    ),
                    "snippet": source_line.strip(),
                    "fix_suggestion": "Use FPaths or config instead",
                    "is_auto_fixable": _is_fixable("CB014"),
                }
            )
    return issues


# CB015: Auto without obvious type
def detect_auto_without_obvious_type(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects use of 'auto' where the assigned type is not
    immediately obvious from the right-hand side.
    Auto is acceptable for iterators and complex template
    types, but hurts readability when the type is unclear.
    Use explicit types where possible.
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()
    # Flag 'auto' assignments where the RHS is a function call
    # (not a cast, not a literal, not a make_* call)
    auto_pattern = re.compile(
        r"\bauto\s+\w+\s*=\s*(?!.*(?:Cast\s*<|static_cast\s*<"
        r"|MakeShared\s*<|MakeUnique\s*<|NewObject\s*<"
        r"|TArray\s*<|TMap\s*<|std::make_))"
        r"\w[\w.:>]*\s*\("
    )

    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()
        if stripped.startswith("//"):
            continue
        if auto_pattern.search(source_line):
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": _extract_class_name(
                        content,
                        _char_pos_for_line(source_lines, line_no),
                    ),
                    "severity": "warning",
                    "rule_id": "CB015",
                    "category": "Best Practices",
                    "message": (
                        "'auto' used where type is not obvious "
                        "— use an explicit type for readability."
                    ),
                    "snippet": source_line.strip(),
                    "fix_suggestion": "Use explicit type for readability",
                    "is_auto_fixable": _is_fixable("CB015"),
                }
            )
    return issues


# CB016: String concatenation in loop
def detect_string_concat_in_loop(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects FString += or FString::Printf concatenation
    inside for/while loops. Each concatenation allocates
    a new FString — use TStringBuilder or FString::Reserve
    before the loop to avoid repeated allocations.
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []
    # Find for/while loop bodies and check for FString +=
    loop_pattern = re.compile(
        r"(?:for|while)\s*\([^)]*\)\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}",
        re.DOTALL,
    )

    for loop_match in loop_pattern.finditer(content):
        loop_body = loop_match.group(1)
        concat_match = re.search(
            r"\bFString\b.*\+=" r"|\+=\s*FString" r"|\bFString::Printf\b",
            loop_body,
        )
        if concat_match:
            line_no = _get_line_number(
                content,
                loop_match.start(1) + concat_match.start(),
            )
            source_lines = content.splitlines()
            snippet_line = (
                source_lines[line_no - 1].strip()
                if line_no <= len(source_lines)
                else ""
            )
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": _extract_class_name(
                        content,
                        _char_pos_for_line(source_lines, line_no),
                    ),
                    "severity": "warning",
                    "rule_id": "CB016",
                    "category": "Best Practices",
                    "message": (
                        "FString concatenation inside loop — "
                        "use TStringBuilder or FString::Reserve "
                        "before the loop to avoid allocations."
                    ),
                    "snippet": snippet_line,
                    "fix_suggestion": "Use TStringBuilder or Reserve",
                    "is_auto_fixable": _is_fixable("CB016"),
                }
            )
    return issues


# CB017: Public member without UPROPERTY
def detect_public_member_without_uproperty(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects public member variables in UCLASS headers that
    lack a UPROPERTY macro. Without UPROPERTY, the variable
    is invisible to the GC, the editor, and Blueprint.
    Add UPROPERTY() with appropriate specifiers.
    """
    if not _is_header(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()
    in_public_section = False

    # Basic UE5 primitive and common types to flag
    member_pattern = re.compile(
        r"^\s*(?:float|int32|int64|bool|uint8|FString|FName"
        r"|FVector|FRotator|FTransform|TArray|TMap)\s+\w+\s*;"
    )

    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()

        if stripped.startswith("public:"):
            in_public_section = True
        elif stripped.startswith("protected:") or stripped.startswith("private:"):
            in_public_section = False

        if not in_public_section:
            continue
        if stripped.startswith("//"):
            continue

        # Check if the previous non-empty line has UPROPERTY
        prev_line = ""
        for prev_idx in range(line_no - 2, max(line_no - 5, -1), -1):
            prev_stripped = source_lines[prev_idx].strip()
            if prev_stripped:
                prev_line = prev_stripped
                break

        if member_pattern.match(source_line):
            if not prev_line.startswith("UPROPERTY"):
                issues.append(
                    {
                        "asset_path": file_path,
                        "line": line_no,
                        "class": _extract_class_name(
                            content,
                            _char_pos_for_line(source_lines, line_no),
                        ),
                        "severity": "warning",
                        "rule_id": "CB017",
                        "category": "Best Practices",
                        "message": (
                            f"Public member '{stripped}' lacks "
                            "UPROPERTY — invisible to GC, editor "
                            "and Blueprint."
                        ),
                        "snippet": source_line.strip(),
                        "fix_suggestion": "Add UPROPERTY() macro",
                        "is_auto_fixable": _is_fixable("CB017"),
                    }
                )
    return issues


# CB018: Raw C array (use TArray)
def detect_raw_c_array(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects raw C-style array declarations (e.g. int32 Arr[10]).
    Raw arrays have fixed size, no bounds checking, and don't
    integrate with UE5 serialization or Blueprint.
    Use TArray<T> instead.
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()
    # Matches: TypeName VarName[size];
    array_pattern = re.compile(
        r"\b(?:int8|int16|int32|int64|uint8|uint16|uint32|uint64"
        r"|float|double|bool|char|TCHAR|FString|FName)\s+"
        r"(\w+)\s*\[\s*\d+\s*\]\s*;"
    )

    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()
        if stripped.startswith("//"):
            continue
        array_match = array_pattern.search(source_line)
        if array_match:
            var_name = array_match.group(1)
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": _extract_class_name(
                        content,
                        _char_pos_for_line(source_lines, line_no),
                    ),
                    "severity": "warning",
                    "rule_id": "CB018",
                    "category": "Best Practices",
                    "message": (
                        f"Raw C array '{var_name}[]' — use "
                        "TArray<T> for bounds checking and "
                        "UE5 serialization support."
                    ),
                    "snippet": source_line.strip(),
                    "fix_suggestion": "Replace raw C array with TArray",
                    "is_auto_fixable": _is_fixable("CB018"),
                }
            )
    return issues


# CB019: Non-virtual destructor on polymorphic class
def detect_non_virtual_destructor(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects non-virtual destructors in classes that inherit
    from AActor or UObject. If a derived class is deleted
    through a base pointer, a non-virtual destructor causes
    undefined behaviour and memory leaks.
    Declare the destructor as virtual.
    """
    if not _is_header(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    # Check if file contains a class inheriting from AActor/UObject
    is_actor_class = any(
        re.search(
            r"class\s+\w+\s*:\s*public\s+(?:AActor|UObject|APawn"
            r"|ACharacter|AGameMode|UActorComponent)",
            line,
        )
        for line in source_lines
    )
    if not is_actor_class:
        return []

    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()
        if stripped.startswith("//"):
            continue
        # Match destructor declaration without virtual keyword
        if re.search(r"^\s*~\w+\s*\(\s*\)\s*;", source_line):
            if not re.search(r"\bvirtual\b", source_line):
                issues.append(
                    {
                        "asset_path": file_path,
                        "line": line_no,
                        "class": _extract_class_name(
                            content,
                            _char_pos_for_line(source_lines, line_no),
                        ),
                        "severity": "warning",
                        "rule_id": "CB019",
                        "category": "Best Practices",
                        "message": (
                            "Non-virtual destructor on a "
                            "polymorphic UE5 class — declare "
                            "it as 'virtual ~ClassName();' to "
                            "prevent memory leaks."
                        ),
                        "snippet": source_line.strip(),
                        "fix_suggestion": "Add virtual to destructor",
                        "is_auto_fixable": _is_fixable("CB019"),
                    }
                )
    return issues


# CB020: FString used for identifier (prefer FName)
def detect_fstring_as_identifier(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects FString member variables whose name suggests
    they are used as identifiers or tags (e.g. PlayerTag,
    ActorId, SocketName). FName is more efficient for
    comparisons and lookups — it is hashed and case-
    insensitive. Use FName or FGameplayTag instead.
    """
    if not _is_header(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()
    # Variable names that suggest identifier/tag usage
    identifier_pattern = re.compile(
        r"\bFString\s+(\w*(?:Tag|Id|Name|Key|Socket|" r"Category|Label|Slot)\w*)\s*;",
        re.IGNORECASE,
    )

    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()
        if stripped.startswith("//"):
            continue
        id_match = identifier_pattern.search(source_line)
        if id_match:
            var_name = id_match.group(1)
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": _extract_class_name(
                        content,
                        _char_pos_for_line(source_lines, line_no),
                    ),
                    "severity": "warning",
                    "rule_id": "CB020",
                    "category": "Best Practices",
                    "message": (
                        f"'{var_name}' looks like an identifier "
                        "— use FName or FGameplayTag instead "
                        "of FString for efficient comparisons."
                    ),
                    "snippet": source_line.strip(),
                    "fix_suggestion": "Use FName instead of FString",
                    "is_auto_fixable": _is_fixable("CB020"),
                }
            )
    return issues


# CB021: Lambda with implicit capture [&] or [=]
def detect_lambda_implicit_capture(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects lambdas using implicit capture [&] or [=].
    Epic Coding Standard: 'Explicit captures should be used
    rather than automatic capture ([&] and [=]). This is
    important for readability, maintainability, safety,
    and performance reasons.'
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    # Matches [&] or [=] at start of lambda capture
    capture_pattern = re.compile(r"\[\s*([&=])\s*\]")

    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()
        if stripped.startswith("//"):
            continue

        capture_match = capture_pattern.search(source_line)
        if capture_match:
            capture_type = (
                "by reference" if capture_match.group(1) == "&" else "by value"
            )
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": _extract_class_name(
                        content,
                        _char_pos_for_line(source_lines, line_no),
                    ),
                    "severity": "warning",
                    "rule_id": "CB021",
                    "category": "Best Practices",
                    "message": (
                        f"Lambda captures all {capture_type} with "
                        f"[{capture_match.group(1)}] — use explicit "
                        "captures for safety and readability."
                    ),
                    "snippet": source_line.strip(),
                    "fix_suggestion": "Use explicit capture list [this]",
                    "is_auto_fixable": _is_fixable("CB021"),
                }
            )

    return issues


# CB022: ensure() without Always variant
def detect_ensure_not_always(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects ensure() calls that could use ensureAlways().

    ensure() only fires once per session; subsequent failures are
    silently ignored. ensureAlways() reports each failure.

    The autofix replaces `ensure(` with `ensureAlways(` on the exact
    line. The detector excludes variants that should NOT be transformed
    (ensureAlways, ensureMsgf, ensureAlwaysMsgf) to guarantee idempotence
    of the fix — if the detector reported a line containing `ensureAlways(`,
    the fixer's replace_text would produce `ensureAlwaysAlways(` and break
    compilation.
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    # Negative lookbehind: matches `ensure(` ONLY if not preceded
    # by letter/digit/underscore. This avoids matching substrings like
    # `my_ensure(` or the prefix of `ensureAlways(` via substring
    # scanning.
    ensure_re = re.compile(r"(?<![A-Za-z0-9_])ensure\s*\(")

    for line_no, source_line in enumerate(source_lines, start=1):
        code_line = _code_part(source_line)
        stripped = code_line.strip()
        if not stripped or stripped.startswith("//"):
            continue

        m = ensure_re.search(code_line)
        if not m:
            continue

        # Extra defensive exclusion: if the line already contains
        # ensureAlways or ensureMsgf anywhere, we skip it
        # (rare cases of multiple macros on the same line).
        if "ensureAlways" in code_line or "ensureMsgf" in code_line:
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
                "rule_id": "CB022",
                "category": "Best Practices",
                "message": (
                    "ensure() only fires once per session — use "
                    "ensureAlways() if each failure should be reported."
                ),
                "snippet": source_line.strip(),
                "fix_suggestion": source_line.replace(
                    "ensure(", "ensureAlways(", 1
                ).strip(),
                "is_auto_fixable": True,
            }
        )

    return issues


# CB023: Virtual function without override keyword
def detect_missing_override(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects virtual function declarations in derived classes
    that lack the override keyword. Epic Coding Standard
    requires override for all overridden virtual functions
    to catch signature mismatches at compile time.
    """
    if not _is_header(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    # Check if file contains a derived class
    has_inheritance = any(
        re.search(r"class\s+\w+\s*:\s*public", line) for line in source_lines
    )
    if not has_inheritance:
        return []

    # Pattern: virtual ReturnType FuncName(...) — we check for 'override' absence
    # explicitly after matching rather than relying on a lookahead, because the
    # optional (?:const\s*)? group causes the lookahead to be evaluated at the
    # wrong position when const is absent, producing false positives.
    virtual_pattern = re.compile(
        r"\bvirtual\s+[\w:<>*&]+\s+(\w+)\s*\([^)]*\)\s*(?:const\s*)?"
    )

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

        virtual_match = virtual_pattern.search(source_line)
        if not virtual_match:
            continue

        # Skip: pure virtual, destructors, already has override/final
        if "= 0" in source_line or "~" in source_line:
            continue
        if "override" in source_line or "final" in source_line:
            continue
        # Skip multi-line declarations where the closing ) is on a later line
        # (the fix would append " override;" to an incomplete declaration)
        if ")" not in source_line:
            continue

        func_name = virtual_match.group(1)

        issues.append(
            {
                "asset_path": file_path,
                "line": line_no,
                "class": _extract_class_name(
                    content,
                    _char_pos_for_line(source_lines, line_no),
                ),
                "severity": "warning",
                "rule_id": "CB023",
                "category": "Best Practices",
                "message": (
                    f"Virtual function '{func_name}' lacks "
                    "override keyword — add 'override' to "
                    "catch signature mismatches."
                ),
                "snippet": stripped,
                "fix_suggestion": "Add override keyword",
                "is_auto_fixable": _is_fixable("CB023"),
            }
        )

    return issues


# CB024: BeginPlay without Super:: call
def detect_missing_super_beginplay(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects BeginPlay implementations that don't call
    Super::BeginPlay(). Forgetting Super breaks the
    initialization chain and causes subtle bugs.
    """
    if not _is_source(file_path):
        return []

    issues: List[Issue] = []

    # Find BeginPlay implementations
    beginplay_pattern = re.compile(
        r"void\s+(\w+)::BeginPlay\s*\(\s*\)\s*" r"\{([^}]*(?:\{[^}]*\}[^}]*)*)\}",
        re.DOTALL,
    )

    for bp_match in beginplay_pattern.finditer(content):
        class_name = bp_match.group(1)
        body = bp_match.group(2)

        if "Super::BeginPlay" not in body:
            line_no = _get_line_number(content, bp_match.start())
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": class_name,
                    "severity": "error",
                    "rule_id": "CB024",
                    "category": "Best Practices",
                    "message": (
                        f"{class_name}::BeginPlay() does not call "
                        "Super::BeginPlay() — this breaks the "
                        "initialization chain."
                    ),
                    "snippet": f"void {class_name}::BeginPlay()",
                    "fix_suggestion": "Add Super::BeginPlay() call",
                    "is_auto_fixable": _is_fixable("CB024"),
                }
            )

    return issues


# CB025: UFUNCTION BlueprintCallable without Category
def detect_ufunction_missing_category(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects UFUNCTION(BlueprintCallable) without a Category.
    Without a category, the function appears under 'Uncategorized'
    in the Blueprint action menu, making it hard to find.
    """
    if not _is_header(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()
        if not stripped.startswith("UFUNCTION"):
            continue

        if "BlueprintCallable" in source_line:
            if "Category" not in source_line:
                issues.append(
                    {
                        "asset_path": file_path,
                        "line": line_no,
                        "class": _extract_class_name(
                            content,
                            _char_pos_for_line(source_lines, line_no),
                        ),
                        "severity": "warning",
                        "rule_id": "CB025",
                        "category": "Best Practices",
                        "message": (
                            "BlueprintCallable without Category — "
                            'add Category="YourCategory" for '
                            "discoverability in Blueprint."
                        ),
                        "snippet": source_line.strip(),
                        "fix_suggestion": "Add Category to UFUNCTION",
                        "is_auto_fixable": _is_fixable("CB025"),
                    }
                )

    return issues


# CB026: UPROPERTY(ExposeOnSpawn) without default value
def detect_exposed_on_spawn_no_default(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects UPROPERTY(ExposeOnSpawn) without a default value in the
    declaration. If the spawner forgets to set the value, it will
    remain garbage / uninitialized.

    The autofix inserts `= <default>` before the `;` based on the
    detected type (int32 → 0, bool → false, UObject* → nullptr, etc.).
    Inserting a default is idempotent with the constructor: if the
    constructor already sets it, that value wins (default init runs
    first). If not, it prevents garbage values.
    """
    if not _is_header(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    # Regex for the field_declaration following UPROPERTY(ExposeOnSpawn).
    # Captures: type (permissive, includes nested templates), name, suffix.
    field_re = re.compile(
        r"^\s*([A-Za-z_][A-Za-z0-9_:<>,\s\*&]*?)\s+"
        r"([A-Za-z_]\w*)\s*(\[[^\]]*\])?\s*"
        r"(=\s*[^;]+)?;"
    )

    for line_no, source_line in enumerate(source_lines, start=1):
        if "ExposeOnSpawn" not in source_line:
            continue
        # It is always UPROPERTY(...ExposeOnSpawn...). The field_declaration
        # is on the NEXT line (Epic convention) or two lines below
        # if there is a comment.
        next_idx = line_no  # 0-indexed next line
        while next_idx < len(source_lines):
            candidate = source_lines[next_idx]
            stripped = candidate.strip()
            if not stripped or stripped.startswith("//"):
                next_idx += 1
                continue
            break
        else:
            continue

        candidate = source_lines[next_idx]
        m = field_re.match(candidate)
        if not m:
            continue

        type_token = m.group(1).strip()
        default_expr = m.group(4)

        if default_expr is not None:
            # Already has default, nothing to do.
            continue

        # Infer safe default by type.
        default_value = _infer_default_for_type(type_token)
        if default_value is None:
            # Unknown type — we don't risk an autofix.
            continue

        fix_line = candidate.rstrip()
        if fix_line.endswith(";"):
            fix_line_noSemi = fix_line[:-1].rstrip()
            fix_preview = f"{fix_line_noSemi} = {default_value};"
        else:
            fix_preview = fix_line

        issues.append(
            {
                "asset_path": file_path,
                "line": next_idx + 1,  # field line, not UPROPERTY
                "class": _extract_class_name(
                    content,
                    _char_pos_for_line(source_lines, next_idx + 1),
                ),
                "severity": "warning",
                "rule_id": "CB026",
                "category": "Best Practices",
                "message": (
                    "ExposeOnSpawn without default value — will remain "
                    "uninitialized if the spawner doesn't set it."
                ),
                "snippet": candidate.strip(),
                "fix_suggestion": fix_preview.strip(),
                "is_auto_fixable": True,
            }
        )

    return issues


def _infer_default_for_type(type_token: str) -> "str | None":
    """
    Returns the default-safe initialization literal for a given C++/UE type,
    or None if we cannot guarantee safety.
    """
    t = type_token.strip()

    # Remove const / volatile / refs / redundant internal whitespace.
    t = re.sub(r"\b(const|volatile|mutable)\b", "", t).strip()
    t = re.sub(r"\s+", " ", t)

    # Raw pointers and TObjectPtr — nullptr is safe.
    if t.endswith("*"):
        return "nullptr"
    if t.startswith("TObjectPtr<") or t.startswith("TWeakObjectPtr<"):
        return "nullptr"
    if t.startswith("TSoftObjectPtr<") or t.startswith("TSoftClassPtr<"):
        return "nullptr"
    if t.startswith("TSubclassOf<"):
        return "nullptr"

    # Numeric types.
    numeric_types = {
        "int8",
        "int16",
        "int32",
        "int64",
        "uint8",
        "uint16",
        "uint32",
        "uint64",
        "float",
        "double",
        "int",
        "short",
        "long",
        "size_t",
        "SIZE_T",
    }
    if t in numeric_types:
        return "0"

    # Bool.
    if t == "bool":
        return "false"

    # UE types with "official" default initialization.
    ue_zero_defaults = {
        "FVector": "FVector::ZeroVector",
        "FVector2D": "FVector2D::ZeroVector",
        "FVector4": "FVector4(ForceInitToZero)",
        "FRotator": "FRotator::ZeroRotator",
        "FQuat": "FQuat::Identity",
        "FTransform": "FTransform::Identity",
        "FLinearColor": "FLinearColor::White",
        "FColor": "FColor::White",
    }
    if t in ue_zero_defaults:
        return ue_zero_defaults[t]

    # Containers — default construct to empty. But they don't need
    # an initializer because the default constructor does the right thing.
    # We return None to indicate "don't touch it" (avoids false positives
    # on containers).
    if t.startswith(("TArray<", "TMap<", "TSet<", "TQueue<")):
        return None
    if t in {"FString", "FName", "FText"}:
        return None

    return None


# CB028: SetTimer with lambda capturing 'this'
def detect_timer_lambda_raw_this(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects SetTimer with lambda capturing `this` directly.
    If the object is destroyed before the timer fires, it crashes.

    The autofix wraps the lambda with
    FTimerDelegate::CreateWeakLambda(this, <original lambda>). This is an
    official overload of SetTimer and CreateWeakLambda only adds a
    validity check of the UObject — it doesn't change lambda semantics,
    just prevents the crash that this rule is trying to avoid.
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    # Look for the start of a SetTimer call. After the `(`
    # scan until we find `[` with `this` or `&` or `=`.
    settimer_re = re.compile(r"\bSetTimer\w*\s*\(")

    for line_no, source_line in enumerate(source_lines, start=1):
        code_line = _code_part(source_line)
        if code_line.lstrip().startswith("//"):
            continue

        m = settimer_re.search(code_line)
        if not m:
            continue

        # Combine up to ~4 lines to support multi-line SetTimer.
        window = "\n".join(
            source_lines[line_no - 1 : min(line_no + 3, len(source_lines))]
        )

        # Skip if already using a safe pattern.
        if (
            "CreateWeakLambda" in window
            or "FTimerDelegate::CreateUObject" in window
            or "TWeakObjectPtr" in window
        ):
            continue

        # Needs a lambda that captures this/&/= within the SetTimer.
        if not re.search(r"\[\s*(?:this|&|=)[^\]]*\]\s*\(", window):
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
                "rule_id": "CB028",
                "category": "Best Practices",
                "message": (
                    "Timer lambda captures 'this' directly — crash "
                    "if the object is destroyed before firing. Use "
                    "FTimerDelegate::CreateWeakLambda(this, ...)."
                ),
                "snippet": source_line.strip(),
                "fix_suggestion": (
                    "FTimerDelegate::CreateWeakLambda(this, [this](){ ... })"
                ),
                "is_auto_fixable": True,
            }
        )

    return issues


# CB029: UE_LOG Verbose without shipping guard
def detect_log_verbose_shipping(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects UE_LOG with Verbose or VeryVerbose level without being inside
    a `#if !UE_BUILD_SHIPPING` guard.

    The autofix wraps the statement in
    `#if !UE_BUILD_SHIPPING ... #endif`. Although UE5 already strips
    Verbose/VeryVerbose at compilation level by default, explicitly wrapping
    is still Epic's recommended practice because it also eliminates the cost
    of string formatting (implicit FString::Printf) in Shipping.
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    # Manual state machine to track whether we are inside a
    # #if !UE_BUILD_SHIPPING ... #endif. Supports basic nesting.
    shipping_guard_stack = 0

    log_re = re.compile(r"\bUE_LOG\s*\(\s*\w+\s*,\s*(Verbose|VeryVerbose)\s*,")

    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()

        if stripped.startswith("#if"):
            if "!UE_BUILD_SHIPPING" in stripped or "UE_BUILD_SHIPPING" not in stripped:
                # Only increment if it's a real !UE_BUILD_SHIPPING.
                if "!UE_BUILD_SHIPPING" in stripped:
                    shipping_guard_stack += 1
        elif stripped.startswith("#endif"):
            if shipping_guard_stack > 0:
                shipping_guard_stack -= 1

        if shipping_guard_stack > 0:
            continue

        if stripped.startswith("//"):
            continue

        if log_re.search(source_line):
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": _extract_class_name(
                        content,
                        _char_pos_for_line(source_lines, line_no),
                    ),
                    "severity": "info",
                    "rule_id": "CB029",
                    "category": "Best Practices",
                    "message": (
                        "UE_LOG Verbose without shipping guard — wrap "
                        "in #if !UE_BUILD_SHIPPING to eliminate "
                        "string formatting from the final build."
                    ),
                    "snippet": source_line.strip(),
                    "fix_suggestion": (
                        "#if !UE_BUILD_SHIPPING\n"
                        f"    {source_line.strip()}\n"
                        "#endif"
                    ),
                    "is_auto_fixable": True,
                }
            )

    return issues


# CB030: String literal in UPROPERTY without TEXT()
def detect_string_literal_no_text_macro(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects string literals in UPROPERTY default values without
    the TEXT() macro. TEXT() ensures proper Unicode handling
    across platforms.
    """
    if not _is_header(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()
    in_uproperty = False

    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()

        if stripped.startswith("UPROPERTY"):
            in_uproperty = True
            continue

        if in_uproperty:
            # Check for string assignment without TEXT()
            if re.search(r'=\s*"[^"]+"\s*;', source_line):
                if 'TEXT("' not in source_line:
                    issues.append(
                        {
                            "asset_path": file_path,
                            "line": line_no,
                            "class": _extract_class_name(
                                content,
                                _char_pos_for_line(source_lines, line_no),
                            ),
                            "severity": "warning",
                            "rule_id": "CB030",
                            "category": "Best Practices",
                            "message": (
                                "String literal without TEXT() macro — "
                                'use TEXT("...") for Unicode safety.'
                            ),
                            "snippet": source_line.strip(),
                            "fix_suggestion": "Wrap string literal with TEXT()",
                            "is_auto_fixable": _is_fixable("CB030"),
                        }
                    )
            in_uproperty = False

    return issues


# CB031: BlueprintPure function with side effects
def detect_blueprint_pure_side_effects(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects UFUNCTION(BlueprintPure) that modifies member
    variables. Pure functions must not have side effects —
    Blueprint may cache results or call them out of order.
    """
    if not _is_header(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    for line_no, source_line in enumerate(source_lines, start=1):
        if "BlueprintPure" not in source_line:
            continue
        if not source_line.strip().startswith("UFUNCTION"):
            continue

        # Get the function signature (next non-empty line)
        func_line_no = line_no + 1
        while func_line_no <= len(source_lines):
            func_line = source_lines[func_line_no - 1].strip()
            if func_line and not func_line.startswith("//"):
                break
            func_line_no += 1

        if func_line_no > len(source_lines):
            continue

        func_line = source_lines[func_line_no - 1]

        # Static member functions cannot be const in C++ (no 'this'
        # pointer). Skip CB031 for them entirely — adding 'const' would
        # produce invalid code ("static member function cannot have
        # 'const' qualifier"). Inspect the signature line and, as a
        # safety net, the immediate non-comment line above it in case
        # 'static' is written on its own line.
        is_static = bool(re.search(r"\bstatic\b", func_line))
        if not is_static:
            prev_idx = func_line_no - 2  # 0-based index of previous line
            while prev_idx >= 0:
                prev_line = source_lines[prev_idx].strip()
                if not prev_line or prev_line.startswith("//"):
                    prev_idx -= 1
                    continue
                # Only the immediate previous non-comment line, and
                # ignore the UFUNCTION macro line itself.
                if not prev_line.startswith("UFUNCTION") and re.search(
                    r"\bstatic\b", prev_line
                ):
                    is_static = True
                break
        if is_static:
            continue

        # Check if function is const (pure functions should be const)
        if ") const" not in func_line and ")const" not in func_line:
            # Extract function name
            func_match = re.search(r"\s+(\w+)\s*\(", func_line)
            func_name = func_match.group(1) if func_match else "function"
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": _extract_class_name(
                        content,
                        _char_pos_for_line(source_lines, line_no),
                    ),
                    "severity": "error",
                    "rule_id": "CB031",
                    "category": "Best Practices",
                    "message": (
                        f"BlueprintPure function '{func_name}' is not "
                        "const — pure functions must not have side "
                        "effects. Add 'const' or remove BlueprintPure."
                    ),
                    "snippet": func_line.strip(),
                    "fix_suggestion": "Add const qualifier to function",
                    "is_auto_fixable": _is_fixable("CB031"),
                }
            )

    return issues


# CB032: const reference in UPROPERTY
def detect_const_ref_uproperty(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects UPROPERTY with const references. References cannot
    be serialized by UE5 — use pointers or value types instead.
    """
    if not _is_header(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()
    prev_was_uproperty = False

    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()

        if stripped.startswith("UPROPERTY"):
            prev_was_uproperty = True
            continue

        if prev_was_uproperty:
            prev_was_uproperty = False
            if re.search(r"\bconst\s+\w+\s*&", source_line):
                issues.append(
                    {
                        "asset_path": file_path,
                        "line": line_no,
                        "class": _extract_class_name(
                            content,
                            _char_pos_for_line(source_lines, line_no),
                        ),
                        "severity": "error",
                        "rule_id": "CB032",
                        "category": "Best Practices",
                        "message": (
                            "UPROPERTY with const reference — "
                            "references cannot be serialized. "
                            "Use pointer or value type."
                        ),
                        "snippet": source_line.strip(),
                        "fix_suggestion": "Remove const reference from UPROPERTY",
                        "is_auto_fixable": _is_fixable("CB032"),
                    }
                )

    return issues


# CB033: EndPlay without Super::EndPlay() call
def detect_missing_super_endplay(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects EndPlay implementations that don't call
    Super::EndPlay(EndPlayReason). Forgetting Super breaks
    the teardown chain — timers, delegates and component
    cleanup will not run, causing crashes or leaks.
    """
    if not _is_source(file_path):
        return []

    issues: List[Issue] = []

    # EndPlay signature: void ClassName::EndPlay(const EEndPlayReason::Type X)
    endplay_pattern = re.compile(
        r"void\s+(\w+)::EndPlay\s*\("
        r"[^)]*EEndPlayReason::Type\s+(\w+)"
        r"[^)]*\)\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}",
        re.DOTALL,
    )

    for ep_match in endplay_pattern.finditer(content):
        class_name = ep_match.group(1)
        param_name = ep_match.group(2)
        body = ep_match.group(3)

        if "Super::EndPlay" not in body:
            line_no = _get_line_number(content, ep_match.start())
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": class_name,
                    "severity": "error",
                    "rule_id": "CB033",
                    "category": "Best Practices",
                    "message": (
                        f"{class_name}::EndPlay() does not call "
                        f"Super::EndPlay({param_name}) — this "
                        "breaks the teardown chain (timers, "
                        "delegates, component cleanup)."
                    ),
                    "snippet": (
                        f"void {class_name}::EndPlay("
                        f"const EEndPlayReason::Type "
                        f"{param_name})"
                    ),
                    "fix_suggestion": (f"Add Super::EndPlay({param_name}) call"),
                    "is_auto_fixable": _is_fixable("CB033"),
                }
            )

    return issues


# CB034: Raw pointer in UPROPERTY — use TObjectPtr<T> (UE5.1+)
def detect_raw_pointer_in_uproperty(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects UPROPERTY-decorated members that use raw pointers
    (e.g. 'AMyActor* Ref') instead of TObjectPtr<T>.
    Since UE5.1, Epic recommends TObjectPtr for all UPROPERTY
    raw pointers — it enables lazy loading, access tracking,
    and future editor tooling. This rule only fires in headers
    where UPROPERTY is on the preceding line, guaranteeing zero
    false positives on non-reflected members.

    Skips: TArray<T*>, TMap, TSet (container element pointers
    are NOT migratable to TObjectPtr), and TSubclassOf/
    TSoftObjectPtr/TWeakObjectPtr which are already smart refs.
    """
    if not _is_header(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    # Match: UE5ClassName* VarName; (or ClassName* VarName = ...)
    # Captures the type and variable name. Requires uppercase-start
    # class name to avoid matching primitive types.
    _RAW_PTR_RE = re.compile(
        r"^\s*(?:class\s+)?" r"([A-Z]\w+)\s*\*\s+(\w+)" r"\s*(?:=\s*[^;]*)?;"
    )

    # Types that are already smart references — skip
    _SMART_REFS = {
        "TObjectPtr",
        "TSubclassOf",
        "TSoftObjectPtr",
        "TSoftClassPtr",
        "TWeakObjectPtr",
        "TSharedPtr",
        "TUniquePtr",
    }

    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()
        if stripped.startswith("//"):
            continue

        # Only fire when UPROPERTY is on the preceding non-empty line
        prev_line = ""
        for prev_idx in range(line_no - 2, max(line_no - 4, -1), -1):
            prev_stripped = source_lines[prev_idx].strip()
            if prev_stripped:
                prev_line = prev_stripped
                break

        if not prev_line.startswith("UPROPERTY"):
            continue

        # Skip lines that already use smart references
        if any(smart in stripped for smart in _SMART_REFS):
            continue

        # Skip container element pointers (TArray<T*>, TMap, TSet)
        if re.search(r"TArray|TMap|TSet", stripped):
            continue

        ptr_match = _RAW_PTR_RE.match(source_line)
        if not ptr_match:
            continue

        class_type = ptr_match.group(1)
        var_name = ptr_match.group(2)

        issues.append(
            {
                "asset_path": file_path,
                "line": line_no,
                "class": _extract_class_name(
                    content,
                    _char_pos_for_line(source_lines, line_no),
                ),
                "severity": "warning",
                "rule_id": "CB034",
                "category": "Best Practices",
                "message": (
                    f"UPROPERTY raw pointer '{class_type}* "
                    f"{var_name}' — use "
                    f"TObjectPtr<{class_type}> for lazy "
                    "loading and access tracking (UE5.1+)."
                ),
                "snippet": source_line.strip(),
                "fix_suggestion": (
                    f"Replace '{class_type}*' with " f"'TObjectPtr<{class_type}>'"
                ),
                "is_auto_fixable": _is_fixable("CB034"),
            }
        )

    return issues


# CB035: UPROPERTY EditAnywhere without Category
def detect_uproperty_missing_category(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects UPROPERTY with EditAnywhere or EditDefaultsOnly
    that lacks a Category specifier. Without Category, the
    property appears under 'Default' in the Details panel,
    making it hard to organize in complex actors.
    """
    if not _is_header(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()
        if not stripped.startswith("UPROPERTY"):
            continue

        # Only flag EditAnywhere / EditDefaultsOnly
        has_edit = "EditAnywhere" in source_line or "EditDefaultsOnly" in source_line
        if not has_edit:
            continue

        # Already has Category — skip
        if "Category" in source_line:
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
                "rule_id": "CB035",
                "category": "Best Practices",
                "message": (
                    "UPROPERTY with editor-visible specifier "
                    "but no Category — property will appear "
                    "under 'Default' in the Details panel."
                ),
                "snippet": source_line.strip(),
                "fix_suggestion": ('Add Category="Default" to UPROPERTY'),
                "is_auto_fixable": _is_fixable("CB035"),
            }
        )

    return issues
