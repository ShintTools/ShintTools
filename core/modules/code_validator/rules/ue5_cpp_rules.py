# core/modules/code_validator/rules/ue5_cpp_rules.py
#
# Deterministic C++ rules for Unreal Engine 5.
# Each rule is a function that receives (content, file_path)
# and returns a list of issue dicts.
#
# Each issue contains:
#   asset_path  — file where the issue was found
#   line        — line number (1-indexed, 0 if not applicable)
#   class       — UE5 class name from the function signature
#   severity    — error | warning | info
#   rule_id     — unique rule identifier
#   category    — Performance | Best Practices | Security
#                 | Maintainability
#   message     — human-readable description
#
# ── Rule index ────────────────────────────────────────
#
# PERFORMANCE (CP)
#   CP001 — FindObjectOfType inside Tick
#   CP002 — GetComponent inside Tick
#   CP003 — Large Tick() body
#   CP004 — UE_LOG Error inside Tick
#
# BEST PRACTICES (CB)
#   CB001 — Infinite loop without exit condition
#   CB002 — Synchronous asset load outside init
#   CB003 — Raw 'new'
#   CB004 — Raw 'delete'
#   CB005 — STL type usage
#   CB006 — printf usage
#   CB007 — System header included
#   CB008 — Float literal without 'f' suffix
#   CB009 — UPROPERTY initialized to nullptr
#
# SECURITY (SC)
#   CS001 — GetWorld() without null-check
#   CS002 — SpawnActor without null-check
#   CS003 — Cast<T> without null-check
#
# MAINTAINABILITY (MT)
#   CM001 — GEngine debug message left in code
#   CM002 — Function body exceeds 80 lines
#   CM003 — TODO / FIXME / HACK comments
# ──────────────────────────────────────────────────────

import re
from pathlib import Path
from typing import Dict, List

# Type alias for issue dictionary
Issue = Dict

# ── HELPERS ───────────────────────────────────────────

# Extensions considered C++ files
_CPP_EXT = {".cpp", ".h", ".hpp", ".cc"}


def _is_cpp(file_path: str) -> bool:
    """Returns True if the file is any kind of C++ file."""
    return Path(file_path).suffix.lower() in _CPP_EXT


def _is_header(file_path: str) -> bool:
    """Returns True if the file is a C++ header."""
    return Path(file_path).suffix.lower() in {".h", ".hpp"}


def _is_source(file_path: str) -> bool:
    """Returns True if the file is a C++ source file."""
    return Path(file_path).suffix.lower() in {".cpp", ".cc"}


def _extract_class_name(content: str, pos: int) -> str:
    """
    Extracts the UE5 class name from the nearest function
    signature before position pos in the content.
    Looks for pattern: ReturnType AClassName::FunctionName
    Returns 'Unknown' if no class signature is found.
    """
    snippet = content[:pos]
    class_matches = re.findall(r"\b([A-Z]\w+)::\w+\s*\(", snippet)
    return class_matches[-1] if class_matches else "Unknown"


def _get_line_number(content: str, pos: int) -> int:
    """
    Returns the 1-indexed line number for a character
    position in the content string.
    """
    return content[:pos].count("\n") + 1


def _char_pos_for_line(lines: list, line_no: int) -> int:
    """
    Returns the character position in the full content
    for the start of line_no (1-indexed).
    Used to extract class name for line-by-line rules.
    """
    return sum(len(line) + 1 for line in lines[: line_no - 1])


# ── PERFORMANCE (CP) ──────────────────────────────────


# CP001: FindObjectOfType inside Tick
def detect_find_object_in_tick(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects calls to FindObjectOfType inside Tick or Update.
    This searches all scene objects every frame, destroying
    performance. Cache the reference in BeginPlay instead.
    """
    issues = []
    tick_pattern = re.compile(
        r"void\s+(\w+)::(?:Tick|Update)\s*\([^)]*\)\s*"
        r"\{([^}]*(?:\{[^}]*\}[^}]*)*)\}",
        re.DOTALL,
    )
    for tick_match in tick_pattern.finditer(content):
        class_name = tick_match.group(1)
        tick_body = tick_match.group(2)
        find_match = re.search(r"FindObjectOfType\s*<", tick_body)
        if find_match:
            body_start = tick_match.start(2)
            line_no = _get_line_number(content, body_start + find_match.start())
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": class_name,
                    "severity": "error",
                    "rule_id": "CP001",
                    "category": "Performance",
                    "message": (
                        "FindObjectOfType called inside Tick(). "
                        "Cache the reference in BeginPlay instead"
                    ),
                }
            )
    return issues


# CP002: GetComponent inside Tick
def detect_get_component_in_tick(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects calls to GetComponent or GetComponentByClass
    inside Tick or Update. The component should be cached
    in BeginPlay, not retrieved every frame.
    """
    issues = []
    tick_pattern = re.compile(
        r"void\s+(\w+)::(?:Tick|Update)\s*\([^)]*\)\s*"
        r"\{([^}]*(?:\{[^}]*\}[^}]*)*)\}",
        re.DOTALL,
    )
    for tick_match in tick_pattern.finditer(content):
        class_name = tick_match.group(1)
        tick_body = tick_match.group(2)
        comp_match = re.search(r"GetComponent(?:ByClass)?\s*[<(]", tick_body)
        if comp_match:
            body_start = tick_match.start(2)
            line_no = _get_line_number(content, body_start + comp_match.start())
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": class_name,
                    "severity": "error",
                    "rule_id": "CP002",
                    "category": "Performance",
                    "message": (
                        "GetComponent called inside Tick(). "
                        "Cache the reference in BeginPlay instead"
                    ),
                }
            )
    return issues


# CP003: Large Tick() body
def detect_large_tick(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects Tick() functions with a body longer than 300
    characters. Large Tick() bodies are a code smell — move
    logic to helper functions or use timers.
    """
    if not _is_source(file_path):
        return []

    issues = []
    tick_match = re.search(
        r"void\s+(\w+)::Tick\b.*\{[^}]{300,}",
        content,
        re.DOTALL,
    )
    if tick_match:
        class_name = tick_match.group(1)
        line_no = _get_line_number(content, tick_match.start())
        issues.append(
            {
                "asset_path": file_path,
                "line": line_no,
                "class": class_name,
                "severity": "warning",
                "rule_id": "CP003",
                "category": "Performance",
                "message": (
                    "Tick() body appears very large — "
                    "move logic to helpers or timers."
                ),
            }
        )
    return issues


# CP004: UE_LOG Error inside Tick()
def detect_log_error_in_tick(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects UE_LOG calls with Error verbosity inside Tick().
    Tick runs up to 60 times per second — logging an error
    every frame floods the output log and tanks performance.
    Move the log outside Tick or use a bool flag to log once.
    """
    if not _is_source(file_path):
        return []

    issues = []
    tick_pattern = re.compile(
        r"void\s+(\w+)::(?:Tick|Update)\s*\([^)]*\)\s*"
        r"\{([^}]*(?:\{[^}]*\}[^}]*)*)\}",
        re.DOTALL,
    )
    for tick_match in tick_pattern.finditer(content):
        class_name = tick_match.group(1)
        tick_body = tick_match.group(2)
        body_start_line = content[: tick_match.start(2)].count("\n") + 1
        for line_idx, body_line in enumerate(tick_body.splitlines()):
            if re.search(r"UE_LOG\s*\([^,]+,\s*Error\s*,", body_line):
                issues.append(
                    {
                        "asset_path": file_path,
                        "line": body_start_line + line_idx,
                        "class": class_name,
                        "severity": "warning",
                        "rule_id": "CP004",
                        "category": "Performance",
                        "message": (
                            "UE_LOG(Error) inside Tick() — logs "
                            "every frame and destroys performance."
                            " Use a flag to log only once."
                        ),
                    }
                )
    return issues


# ── BEST PRACTICES (CB) ───────────────────────────────


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
    issues = []
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

    issues = []
    source_lines = content.splitlines()
    for line_no, source_line in enumerate(source_lines, start=1):
        if re.search(r"\bnew\s+\w", source_line):
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

    issues = []
    source_lines = content.splitlines()
    for line_no, source_line in enumerate(source_lines, start=1):
        if re.search(r"\bdelete\s+\w", source_line):
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

    issues = []
    source_lines = content.splitlines()
    for line_no, source_line in enumerate(source_lines, start=1):
        if re.search(r"\bstd::\w", source_line):
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

    issues = []
    source_lines = content.splitlines()
    for line_no, source_line in enumerate(source_lines, start=1):
        if re.search(r"\bprintf\s*\(", source_line):
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

    issues = []
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

    issues = []
    source_lines = content.splitlines()
    for line_no, source_line in enumerate(source_lines, start=1):
        if re.search(
            r"\bfloat\b\s+\w+\s*=\s*[0-9]+\.[0-9]+[^f]",
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
                    "severity": "warning",
                    "rule_id": "CB008",
                    "category": "Best Practices",
                    "message": (
                        "Float literal without 'f' suffix — "
                        "add 'f' (e.g. 1.0f) to avoid double "
                        "promotion."
                    ),
                }
            )
    return issues


# CB09: UPROPERTY initialized to nullptr in declaration
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

    issues = []
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
                }
            )
    return issues


# ── SECURITY (CS) ─────────────────────────────────────


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
    """
    if not _is_source(file_path):
        return []

    issues = []
    source_lines = content.splitlines()
    for line_no, source_line in enumerate(source_lines, start=1):
        if re.search(r"\bGetWorld\(\)\s*->", source_line):
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

    issues = []
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

        for next_line in source_lines[line_no : line_no + 5]:
            stripped = next_line.strip()
            if not stripped:
                continue
            if re.search(rf"\b{re.escape(var_name)}\s*->", stripped):
                if not re.search(r"\bif\b", stripped):
                    issues.append(
                        {
                            "asset_path": file_path,
                            "line": line_no,
                            "class": class_name,
                            "severity": "error",
                            "rule_id": "CS002",
                            "category": "Security",
                            "message": (
                                f"SpawnActor result '{var_name}'"
                                " used without null-check — "
                                "SpawnActor can return nullptr."
                            ),
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

    issues = []
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

        for next_line in source_lines[line_no : line_no + 5]:
            stripped = next_line.strip()
            if not stripped:
                continue
            if re.search(rf"\b{re.escape(var_name)}\s*->", stripped):
                if not re.search(r"\bif\b", stripped):
                    issues.append(
                        {
                            "asset_path": file_path,
                            "line": line_no,
                            "class": class_name,
                            "severity": "error",
                            "rule_id": "CS003",
                            "category": "Security",
                            "message": (
                                f"Cast result '{var_name}' used "
                                "without null-check — Cast<T> "
                                "returns nullptr if type does not"
                                " match."
                            ),
                        }
                    )
            break

    return issues


# ── MAINTAINABILITY (CM) ──────────────────────────────


# CM001: GEngine debug message left in code
def detect_debug_message(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects GEngine->AddOnScreenDebugMessage calls.
    These are useful during development but must be removed
    before shipping — they cause visual noise and slight
    performance overhead in release builds.
    """
    if not _is_cpp(file_path):
        return []

    issues = []
    source_lines = content.splitlines()
    for line_no, source_line in enumerate(source_lines, start=1):
        if re.search(r"GEngine->AddOnScreenDebugMessage", source_line):
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": _extract_class_name(
                        content,
                        _char_pos_for_line(source_lines, line_no),
                    ),
                    "severity": "error",
                    "rule_id": "CM001",
                    "category": "Maintainability",
                    "message": (
                        "GEngine debug message left in code — "
                        "remove before shipping."
                    ),
                }
            )
    return issues


# CM002: Function body exceeds 80 lines
def detect_long_function(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects functions whose body exceeds 80 lines.
    Long functions are hard to read, test and maintain.
    Split them into smaller functions with clear
    responsibilities.
    """
    if not _is_cpp(file_path):
        return []

    issues = []
    source_lines = content.splitlines()
    total_lines = len(source_lines)

    func_pattern = re.compile(
        r"^\s*(?:[\w:<>*&]+\s+)+(\w+)\s*\([^;]*\)\s*"
        r"(?:const\s*)?(?:override\s*)?(?:noexcept\s*)?\{"
    )

    line_idx = 0
    while line_idx < total_lines:
        func_match = func_pattern.match(source_lines[line_idx])
        if func_match:
            func_name = func_match.group(1)
            start_line = line_idx + 1
            brace_depth = source_lines[line_idx].count("{") - source_lines[
                line_idx
            ].count("}")
            end_idx = line_idx + 1

            while end_idx < total_lines and brace_depth > 0:
                brace_depth += source_lines[end_idx].count("{") - source_lines[
                    end_idx
                ].count("}")
                end_idx += 1

            func_length = end_idx - line_idx
            if func_length > 80:
                class_name = _extract_class_name(
                    content,
                    _char_pos_for_line(source_lines, start_line),
                )
                issues.append(
                    {
                        "asset_path": file_path,
                        "line": start_line,
                        "class": class_name,
                        "severity": "warning",
                        "rule_id": "CM002",
                        "category": "Maintainability",
                        "message": (
                            f"Function '{func_name}' is "
                            f"{func_length} lines long — split "
                            "into smaller functions (max 80)."
                        ),
                    }
                )
            line_idx = end_idx
        else:
            line_idx += 1

    return issues


# CM003: TODO / FIXME / HACK comments detected
def detect_todo_comments(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects TODO, FIXME and HACK comments left in the code.
    These indicate unfinished work or temporary workarounds
    that should be tracked and resolved before shipping.
    """
    if not _is_cpp(file_path):
        return []

    issues = []
    source_lines = content.splitlines()
    for line_no, source_line in enumerate(source_lines, start=1):
        if re.search(
            r"//.*\b(TODO|FIXME|HACK)\b",
            source_line,
            re.IGNORECASE,
        ):
            tag_match = re.search(
                r"\b(TODO|FIXME|HACK)\b",
                source_line,
                re.IGNORECASE,
            )
            tag_found = tag_match.group(1).upper() if tag_match else "TODO"
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": _extract_class_name(
                        content,
                        _char_pos_for_line(source_lines, line_no),
                    ),
                    "severity": "info",
                    "rule_id": "CM003",
                    "category": "Maintainability",
                    "message": (
                        f"{tag_found} comment detected — track "
                        "and resolve before shipping."
                    ),
                }
            )
    return issues


# ── RUNNER ────────────────────────────────────────────


def run_all_cpp_rules(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Runs all deterministic C++ rules against the given
    file content and returns a merged list of issues.

    Performance (CP):      CP001, CP002, CP003, CP004
    Best Practices (CB):   CB001-CB009
    Security (CS):         CS001, CS002, CS003
    Maintainability (CM):  CM001, CM002, CM003
    """
    issues: List[Issue] = []

    # Performance
    issues += detect_find_object_in_tick(content, file_path)
    issues += detect_get_component_in_tick(content, file_path)
    issues += detect_large_tick(content, file_path)
    issues += detect_log_error_in_tick(content, file_path)

    # Best Practices
    issues += detect_infinite_loop(content, file_path)
    issues += detect_runtime_load(content, file_path)
    issues += detect_raw_new(content, file_path)
    issues += detect_raw_delete(content, file_path)
    issues += detect_stl_usage(content, file_path)
    issues += detect_printf(content, file_path)
    issues += detect_system_headers(content, file_path)
    issues += detect_float_no_suffix(content, file_path)
    issues += detect_uproperty_nullptr(content, file_path)

    # Security
    issues += detect_getworld_no_check(content, file_path)
    issues += detect_spawnactor_no_check(content, file_path)
    issues += detect_cast_no_check(content, file_path)

    # Maintainability
    issues += detect_debug_message(content, file_path)
    issues += detect_long_function(content, file_path)
    issues += detect_todo_comments(content, file_path)

    return issues
