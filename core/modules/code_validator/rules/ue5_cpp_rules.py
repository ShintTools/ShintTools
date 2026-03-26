# core/modules/code_validator/rules/ue5_cpp_rules.py
#
# Deterministic C++ rules for Unreal Engine 5.
# Each rule is a function that receives (content, file_path)
# and returns a list of issue dicts.
#
# Original rules:  find_object_in_tick, get_component_in_tick,
#                  infinite_loop_no_exit, runtime_asset_load
# Added (Raul):   CV001–CV010 (common UE5 C++ code smells)

import re
from pathlib import Path
from typing import Dict, List

# Type alias for issue dictionary
Issue = Dict


# ORIGINAL RULES — context-aware (analyse function bodies)

# RULE: FindObjectOfType inside Tick
def detect_find_object_in_tick(content: str, file_path: str) -> List[Issue]:
    """
    Detects calls to FindObjectOfType inside Tick or Update.
    This searches all scene objects every frame, destroying
    performance. Cache the reference in BeginPlay instead.
    """
    issues = []
    tick_pattern = re.compile(
        r"void\s+\w+::(?:Tick|Update)\s*\([^)]*\)\s*"
        r"\{([^}]*(?:\{[^}]*\}[^}]*)*)\}",
        re.DOTALL,
    )
    for match in tick_pattern.finditer(content):
        body = match.group(1)
        if re.search(r"FindObjectOfType\s*<", body):
            issues.append(
                {
                    "asset_path": file_path,
                    "severity": "error",
                    "rule_id": "find_object_in_tick",
                    "message": (
                        "FindObjectOfType called inside Tick(). "
                        "Cache the reference in BeginPlay instead"
                    ),
                }
            )
    return issues


# RULE: GetComponent inside Tick
def detect_get_component_in_tick(content: str, file_path: str) -> List[Issue]:
    """
    Detects calls to GetComponent or GetComponentByClass
    inside Tick or Update. The component should be cached
    in BeginPlay, not retrieved every frame.
    """
    issues = []
    tick_pattern = re.compile(
        r"void\s+\w+::(?:Tick|Update)\s*\([^)]*\)\s*"
        r"\{([^}]*(?:\{[^}]*\}[^}]*)*)\}",
        re.DOTALL,
    )
    for match in tick_pattern.finditer(content):
        body = match.group(1)
        if re.search(r"GetComponent(?:ByClass)?\s*[<(]", body):
            issues.append(
                {
                    "asset_path": file_path,
                    "severity": "error",
                    "rule_id": "get_component_in_tick",
                    "message": (
                        "GetComponent called inside Tick(). "
                        "Cache the reference in BeginPlay instead"
                    ),
                }
            )
    return issues


# RULE: Infinite loop without exit condition
def detect_infinite_loop(content: str, file_path: str) -> List[Issue]:
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
    for match in loop_pattern.finditer(content):
        body = match.group(1)
        has_exit = re.search(r"\b(?:break|return|goto)\b", body)
        if not has_exit:
            issues.append(
                {
                    "asset_path": file_path,
                    "severity": "error",
                    "rule_id": "infinite_loop_no_exit",
                    "message": (
                        "Infinite loop without break/return. "
                        "Game thread will freeze"
                    ),
                }
            )
    return issues


# RULE: Synchronous asset load outside init
def detect_runtime_load(content: str, file_path: str) -> List[Issue]:
    """
    Detects synchronous asset loading calls outside of
    initialization functions like BeginPlay or Constructor.
    These cause frame hitches at runtime. Use async
    loading via FStreamableManager instead.
    """
    issues: list[Issue] = []
    load_pattern = re.compile(
        r"\b(?:StaticLoadObject|LoadObject|"
        r"FSoftObjectPath|RequestSyncLoad)\s*[<(]"
    )
    init_functions = re.compile(
        r"void\s+\w+::"
        r"(?:BeginPlay|Constructor|PostInitializeComponents)"
        r"\s*\("
    )
    load_matches = list(load_pattern.finditer(content))
    if not load_matches:
        return issues

    # Find the character ranges of all init functions
    init_ranges = []
    for init_match in init_functions.finditer(content):
        start = init_match.start()
        depth = 0
        for i, ch in enumerate(content[start:]):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    init_ranges.append((start, start + i))
                    break

    # Flag any load call that is outside an init function
    for load_match in load_matches:
        pos = load_match.start()
        inside_init = any(s <= pos <= e for s, e in init_ranges)
        if not inside_init:
            issues.append(
                {
                    "asset_path": file_path,
                    "severity": "warning",
                    "rule_id": "runtime_asset_load",
                    "message": (
                        "Synchronous asset load outside "
                        "BeginPlay/Constructor. "
                        "Use async loading instead"
                    ),
                }
            )
    return issues



# RULES (CV001–CV010) — line-by-line regex checks


# Helper: only run on C++ files
_CPP_EXT = {".cpp", ".h", ".hpp", ".cc"}


def _is_cpp(file_path: str) -> bool:
    return Path(file_path).suffix.lower() in _CPP_EXT


def _is_header(file_path: str) -> bool:
    return Path(file_path).suffix.lower() in {".h", ".hpp"}


def _is_source(file_path: str) -> bool:
    return Path(file_path).suffix.lower() in {".cpp", ".cc"}


# CV001: Raw 'new' detected
def detect_raw_new(content: str, file_path: str) -> List[Issue]:
    """
    Detects raw 'new' keyword usage. In UE5, objects should be
    created with NewObject<T>() or CreateDefaultSubobject<T>().
    Raw new bypasses the garbage collector and causes memory leaks.
    """
    if not _is_cpp(file_path):
        return []

    issues = []
    for line_no, line in enumerate(content.splitlines(), start=1):
        if re.search(r"\bnew\s+\w", line):
            issues.append({
                "asset_path": file_path,
                "severity": "error",
                "rule_id": "CV001",
                "message": "Raw 'new' detected — use NewObject<T>() or CreateDefaultSubobject<T>() instead.",
                "line": line_no,
            })
    return issues


# CV002: Raw 'delete' detected
def detect_raw_delete(content: str, file_path: str) -> List[Issue]:
    """
    Detects raw 'delete' keyword usage. UObjects are managed by
    UE5's garbage collector. Calling delete on them causes crashes.
    """
    if not _is_cpp(file_path):
        return []

    issues = []
    for line_no, line in enumerate(content.splitlines(), start=1):
        if re.search(r"\bdelete\s+\w", line):
            issues.append({
                "asset_path": file_path,
                "severity": "error",
                "rule_id": "CV002",
                "message": "Raw 'delete' detected — UObjects are garbage-collected; manual delete will crash.",
                "line": line_no,
            })
    return issues


# CV003: STL type usage
def detect_stl_usage(content: str, file_path: str) -> List[Issue]:
    """
    Detects usage of std:: types. UE5 has its own containers
    (TArray, TMap, FString) that integrate with the engine's
    memory management, serialization and reflection systems.
    """
    if not _is_cpp(file_path):
        return []

    issues = []
    for line_no, line in enumerate(content.splitlines(), start=1):
        if re.search(r"\bstd::\w", line):
            issues.append({
                "asset_path": file_path,
                "severity": "warning",
                "rule_id": "CV003",
                "message": "STL type detected — prefer UE equivalents (TArray, TMap, FString, etc.).",
                "line": line_no,
            })
    return issues


# CV004: printf usage
def detect_printf(content: str, file_path: str) -> List[Issue]:
    """
    Detects printf() calls. UE5 uses UE_LOG() for logging,
    which supports log categories, verbosity levels, and
    integrates with the output log window in the editor.
    """
    if not _is_cpp(file_path):
        return []

    issues = []
    for line_no, line in enumerate(content.splitlines(), start=1):
        if re.search(r"\bprintf\s*\(", line):
            issues.append({
                "asset_path": file_path,
                "severity": "warning",
                "rule_id": "CV004",
                "message": "printf() detected — use UE_LOG() instead.",
                "line": line_no,
            })
    return issues


# CV005: System header included
def detect_system_headers(content: str, file_path: str) -> List[Issue]:
    """
    Detects #include of system headers (angle brackets).
    UE5 has its own module system; prefer UE module headers
    over system headers. Exceptions: stdint, limits, cmath, cassert.
    """
    if not _is_cpp(file_path):
        return []

    issues = []
    for line_no, line in enumerate(content.splitlines(), start=1):
        if re.search(r"#include\s+<(?!stdint|limits|cmath|cassert)", line):
            issues.append({
                "asset_path": file_path,
                "severity": "warning",
                "rule_id": "CV005",
                "message": "System header included — prefer UE module headers.",
                "line": line_no,
            })
    return issues


# CV006: Large Tick() body
def detect_large_tick(content: str, file_path: str) -> List[Issue]:
    """
    Detects Tick() functions with a body longer than 300 characters.
    Large Tick() bodies are a code smell — move logic to helper
    functions or use timers to avoid doing too much every frame.
    """
    if not _is_source(file_path):
        return []

    issues = []
    if re.search(r"\bTick\b.*\{[^}]{300,}", content, re.DOTALL):
        issues.append({
            "asset_path": file_path,
            "severity": "warning",
            "rule_id": "CV006",
            "message": "Tick() body appears very large — move logic to helpers or timers.",
            "line": 0,
        })
    return issues


# CV007: GEngine debug message left in code
def detect_debug_message(content: str, file_path: str) -> List[Issue]:
    """
    Detects GEngine->AddOnScreenDebugMessage calls.
    These are useful during development but must be removed
    before shipping — they cause visual noise and slight
    performance overhead in release builds.
    """
    if not _is_cpp(file_path):
        return []

    issues = []
    for line_no, line in enumerate(content.splitlines(), start=1):
        if re.search(r"GEngine->AddOnScreenDebugMessage", line):
            issues.append({
                "asset_path": file_path,
                "severity": "error",
                "rule_id": "CV007",
                "message": "GEngine debug message left in code — remove before shipping.",
                "line": line_no,
            })
    return issues


# CV008: Float literal without 'f' suffix
def detect_float_no_suffix(content: str, file_path: str) -> List[Issue]:
    """
    Detects float variables assigned a decimal literal without
    the 'f' suffix (e.g. 1.0 instead of 1.0f). Without the suffix,
    the compiler treats the literal as a double, causing an
    implicit promotion that wastes CPU cycles.
    """
    if not _is_cpp(file_path):
        return []

    issues = []
    for line_no, line in enumerate(content.splitlines(), start=1):
        if re.search(r"\bfloat\b\s+\w+\s*=\s*[0-9]+\.[0-9]+[^f]", line):
            issues.append({
                "asset_path": file_path,
                "severity": "warning",
                "rule_id": "CV008",
                "message": "Float literal without 'f' suffix — add 'f' (e.g. 1.0f) to avoid double promotion.",
                "line": line_no,
            })
    return issues


# CV009: UPROPERTY initialized to nullptr in declaration
def detect_uproperty_nullptr(content: str, file_path: str) -> List[Issue]:
    """
    Detects UPROPERTY pointers initialized to nullptr directly
    in the declaration. In UE5, UPROPERTY members should be
    initialized in the constructor body so the reflection
    system and CDO (Class Default Object) handle them properly.
    """
    if not _is_header(file_path):
        return []

    issues = []
    for line_no, line in enumerate(content.splitlines(), start=1):
        if re.search(r"UPROPERTY\([^)]*\)\s*\w+\s*\*\s*\w+\s*=\s*nullptr", line):
            issues.append({
                "asset_path": file_path,
                "severity": "error",
                "rule_id": "CV009",
                "message": "UPROPERTY initialized to nullptr in declaration — initialize in constructor body.",
                "line": line_no,
            })
    return issues


# CV010: GetWorld() without null-check
def detect_getworld_no_check(content: str, file_path: str) -> List[Issue]:
    """
    Detects GetWorld()-> calls without a null-check.
    GetWorld() can return nullptr in editor utilities,
    commandlets, or during shutdown. Always guard with
    'if (UWorld* W = GetWorld())' before dereferencing.
    """
    if not _is_source(file_path):
        return []

    issues = []
    for line_no, line in enumerate(content.splitlines(), start=1):
        if re.search(r"\bGetWorld\(\)\s*->", line):
            issues.append({
                "asset_path": file_path,
                "severity": "warning",
                "rule_id": "CV010",
                "message": "GetWorld() called without null-check — guard with 'if (UWorld* W = GetWorld())'.",
                "line": line_no,
            })
    return issues



# RUNNER — executes ALL rules


def run_all_cpp_rules(content: str, file_path: str) -> List[Issue]:
    """
    Runs all deterministic C++ rules against the given
    file content and returns a merged list of issues.

    Original rules (4):
        find_object_in_tick, get_component_in_tick,
        infinite_loop_no_exit, runtime_asset_load

    Raúl's rules (10):
        CV001–CV010
    """
    issues = []

    # Original Context-aware rules
    issues += detect_find_object_in_tick(content, file_path)
    issues += detect_get_component_in_tick(content, file_path)
    issues += detect_infinite_loop(content, file_path)
    issues += detect_runtime_load(content, file_path)

    # Raul's Rules (CV001–CV010)
    issues += detect_raw_new(content, file_path)
    issues += detect_raw_delete(content, file_path)
    issues += detect_stl_usage(content, file_path)
    issues += detect_printf(content, file_path)
    issues += detect_system_headers(content, file_path)
    issues += detect_large_tick(content, file_path)
    issues += detect_debug_message(content, file_path)
    issues += detect_float_no_suffix(content, file_path)
    issues += detect_uproperty_nullptr(content, file_path)
    issues += detect_getworld_no_check(content, file_path)

    return issues
