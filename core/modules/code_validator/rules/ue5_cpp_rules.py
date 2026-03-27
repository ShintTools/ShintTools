# core/modules/code_validator/rules/ue5_cpp_rules.py
#
# Deterministic C++ rules for Unreal Engine 5.
# Each rule is a function that receives (content, file_path)
# and returns a list of issue dicts.
#
# Original rules:  find_object_in_tick, get_component_in_tick,
#                  infinite_loop_no_exit, runtime_asset_load
# Added (Raul):    CV001-CV015 (common UE5 C++ code smells)

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
        r"void\s+\w+::(?:Tick|Update)\s*\([^)]*\)\s*" r"\{([^}]*(?:\{[^}]*\}[^}]*)*)\}",
        re.DOTALL,
    )
    for tick_match in tick_pattern.finditer(content):
        tick_body = tick_match.group(1)
        if re.search(r"FindObjectOfType\s*<", tick_body):
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
        r"void\s+\w+::(?:Tick|Update)\s*\([^)]*\)\s*" r"\{([^}]*(?:\{[^}]*\}[^}]*)*)\}",
        re.DOTALL,
    )
    for tick_match in tick_pattern.finditer(content):
        tick_body = tick_match.group(1)
        if re.search(r"GetComponent(?:ByClass)?\s*[<(]", tick_body):
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
    for loop_match in loop_pattern.finditer(content):
        loop_body = loop_match.group(1)
        has_exit = re.search(r"\b(?:break|return|goto)\b", loop_body)
        if not has_exit:
            issues.append(
                {
                    "asset_path": file_path,
                    "severity": "error",
                    "rule_id": "infinite_loop_no_exit",
                    "message": (
                        "Infinite loop without break/return. " "Game thread will freeze"
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

    # Flag any load call that is outside an init function
    for load_match in load_matches:
        call_pos = load_match.start()
        inside_init = any(s <= call_pos <= e for s, e in init_ranges)
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


# RULES (CV001-CV015) — line-by-line and context-aware checks


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
    for line_no, source_line in enumerate(content.splitlines(), start=1):
        if re.search(r"\bnew\s+\w", source_line):
            issues.append(
                {
                    "asset_path": file_path,
                    "severity": "error",
                    "rule_id": "CV001",
                    "message": (
                        "Raw 'new' detected — use NewObject<T>() "
                        "or CreateDefaultSubobject<T>() instead."
                    ),
                    "line": line_no,
                }
            )
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
    for line_no, source_line in enumerate(content.splitlines(), start=1):
        if re.search(r"\bdelete\s+\w", source_line):
            issues.append(
                {
                    "asset_path": file_path,
                    "severity": "error",
                    "rule_id": "CV002",
                    "message": (
                        "Raw 'delete' detected — UObjects are garbage-collected; "
                        "manual delete will crash."
                    ),
                    "line": line_no,
                }
            )
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
    for line_no, source_line in enumerate(content.splitlines(), start=1):
        if re.search(r"\bstd::\w", source_line):
            issues.append(
                {
                    "asset_path": file_path,
                    "severity": "warning",
                    "rule_id": "CV003",
                    "message": (
                        "STL type detected — prefer UE equivalents "
                        "(TArray, TMap, FString, etc.)."
                    ),
                    "line": line_no,
                }
            )
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
    for line_no, source_line in enumerate(content.splitlines(), start=1):
        if re.search(r"\bprintf\s*\(", source_line):
            issues.append(
                {
                    "asset_path": file_path,
                    "severity": "warning",
                    "rule_id": "CV004",
                    "message": "printf() detected — use UE_LOG() instead.",
                    "line": line_no,
                }
            )
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
    for line_no, source_line in enumerate(content.splitlines(), start=1):
        if re.search(r"#include\s+<(?!stdint|limits|cmath|cassert)", source_line):
            issues.append(
                {
                    "asset_path": file_path,
                    "severity": "warning",
                    "rule_id": "CV005",
                    "message": "System header included — prefer UE module headers.",
                    "line": line_no,
                }
            )
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
        issues.append(
            {
                "asset_path": file_path,
                "severity": "warning",
                "rule_id": "CV006",
                "message": (
                    "Tick() body appears very large — "
                    "move logic to helpers or timers."
                ),
                "line": 0,
            }
        )
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
    for line_no, source_line in enumerate(content.splitlines(), start=1):
        if re.search(r"GEngine->AddOnScreenDebugMessage", source_line):
            issues.append(
                {
                    "asset_path": file_path,
                    "severity": "error",
                    "rule_id": "CV007",
                    "message": (
                        "GEngine debug message left in code — "
                        "remove before shipping."
                    ),
                    "line": line_no,
                }
            )
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
    for line_no, source_line in enumerate(content.splitlines(), start=1):
        if re.search(r"\bfloat\b\s+\w+\s*=\s*[0-9]+\.[0-9]+[^f]", source_line):
            issues.append(
                {
                    "asset_path": file_path,
                    "severity": "warning",
                    "rule_id": "CV008",
                    "message": (
                        "Float literal without 'f' suffix — "
                        "add 'f' (e.g. 1.0f) to avoid double promotion."
                    ),
                    "line": line_no,
                }
            )
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
    for line_no, source_line in enumerate(content.splitlines(), start=1):
        if re.search(r"UPROPERTY\([^)]*\)\s*\w+\s*\*\s*\w+\s*=\s*nullptr", source_line):
            issues.append(
                {
                    "asset_path": file_path,
                    "severity": "error",
                    "rule_id": "CV009",
                    "message": (
                        "UPROPERTY initialized to nullptr in declaration — "
                        "initialize in constructor body."
                    ),
                    "line": line_no,
                }
            )
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
    for line_no, source_line in enumerate(content.splitlines(), start=1):
        if re.search(r"\bGetWorld\(\)\s*->", source_line):
            issues.append(
                {
                    "asset_path": file_path,
                    "severity": "warning",
                    "rule_id": "CV010",
                    "message": (
                        "GetWorld() called without null-check — "
                        "guard with 'if (UWorld* W = GetWorld())'."
                    ),
                    "line": line_no,
                }
            )
    return issues


# CV011: UE_LOG Error inside Tick()
def detect_log_error_in_tick(content: str, file_path: str) -> List[Issue]:
    """
    Detects UE_LOG calls with Error verbosity inside Tick().
    Tick runs up to 60 times per second — logging an error every
    frame floods the output log and tanks performance.
    Move the log outside Tick or use a bool flag to log only once.
    """
    if not _is_source(file_path):
        return []

    issues = []
    tick_pattern = re.compile(
        r"void\s+\w+::(?:Tick|Update)\s*\([^)]*\)\s*" r"\{([^}]*(?:\{[^}]*\}[^}]*)*)\}",
        re.DOTALL,
    )
    for tick_match in tick_pattern.finditer(content):
        tick_body = tick_match.group(1)
        body_start_line = content[: tick_match.start(1)].count("\n") + 1
        for line_idx, body_line in enumerate(tick_body.splitlines()):
            if re.search(r"UE_LOG\s*\([^,]+,\s*Error\s*,", body_line):
                issues.append(
                    {
                        "asset_path": file_path,
                        "severity": "warning",
                        "rule_id": "CV011",
                        "message": (
                            "UE_LOG(Error) inside Tick() — logs every frame and "
                            "destroys performance. Use a flag to log only once."
                        ),
                        "line": body_start_line + line_idx,
                    }
                )
    return issues


# CV012: SpawnActor without null-check
def detect_spawnactor_no_check(content: str, file_path: str) -> List[Issue]:
    """
    Detects SpawnActor calls whose result is used on the very next
    non-empty line without a null-check guard.
    SpawnActor can return nullptr if the spawn fails (collision,
    invalid world, etc). Always check the result before use.
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

        for next_line in source_lines[line_no : line_no + 5]:
            stripped = next_line.strip()
            if not stripped:
                continue
            if re.search(rf"\b{re.escape(var_name)}\s*->", stripped):
                if not re.search(r"\bif\b", stripped):
                    issues.append(
                        {
                            "asset_path": file_path,
                            "severity": "error",
                            "rule_id": "CV012",
                            "message": (
                                f"SpawnActor result '{var_name}' used without "
                                "null-check — SpawnActor can return nullptr."
                            ),
                            "line": line_no,
                        }
                    )
            break  # Solo revisamos la primera linea no vacia

    return issues


# CV013: Cast<T> without null-check
def detect_cast_no_check(content: str, file_path: str) -> List[Issue]:
    """
    Detects Cast<T> calls whose result is used on the next
    non-empty line without a null-check guard.
    Cast<T> returns nullptr if the object is not of the expected
    type. Always check the result before dereferencing.
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

        for next_line in source_lines[line_no : line_no + 5]:
            stripped = next_line.strip()
            if not stripped:
                continue
            if re.search(rf"\b{re.escape(var_name)}\s*->", stripped):
                if not re.search(r"\bif\b", stripped):
                    issues.append(
                        {
                            "asset_path": file_path,
                            "severity": "error",
                            "rule_id": "CV013",
                            "message": (
                                f"Cast result '{var_name}' used without "
                                "null-check — Cast<T> returns nullptr if the "
                                "type does not match."
                            ),
                            "line": line_no,
                        }
                    )
            break  # Solo revisamos la primera linea no vacia

    return issues


# CV014: Function body exceeds 80 lines
def detect_long_function(content: str, file_path: str) -> List[Issue]:
    """
    Detects functions whose body exceeds 80 lines.
    Long functions are hard to read, test and maintain.
    Split them into smaller functions with clear responsibilities.
    """
    if not _is_cpp(file_path):
        return []

    issues = []
    source_lines = content.splitlines()
    total_lines = len(source_lines)

    func_pattern = re.compile(
        r"^\s*(?:[\w:<>*&]+\s+)+(\w+)\s*\([^;]*\)\s*(?:const\s*)?"
        r"(?:override\s*)?(?:noexcept\s*)?\{"
    )

    line_idx = 0
    while line_idx < total_lines:
        func_match = func_pattern.match(source_lines[line_idx])
        if func_match:
            func_name = func_match.group(1)
            start_line = line_idx + 1  # 1-indexed
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
                issues.append(
                    {
                        "asset_path": file_path,
                        "severity": "warning",
                        "rule_id": "CV014",
                        "message": (
                            f"Function '{func_name}' is {func_length} lines long "
                            "— split into smaller functions (max 80 lines)."
                        ),
                        "line": start_line,
                    }
                )
            line_idx = end_idx
        else:
            line_idx += 1

    return issues


# CV015: TODO / FIXME / HACK comments detected
def detect_todo_comments(content: str, file_path: str) -> List[Issue]:
    """
    Detects TODO, FIXME and HACK comments left in the code.
    These indicate unfinished work or temporary workarounds
    that should be tracked and resolved before shipping.
    """
    if not _is_cpp(file_path):
        return []

    issues = []
    for line_no, source_line in enumerate(content.splitlines(), start=1):
        if re.search(r"//.*\b(TODO|FIXME|HACK)\b", source_line, re.IGNORECASE):
            tag_match = re.search(r"\b(TODO|FIXME|HACK)\b", source_line, re.IGNORECASE)
            tag_found = tag_match.group(1).upper() if tag_match else "TODO"
            issues.append(
                {
                    "asset_path": file_path,
                    "severity": "info",
                    "rule_id": "CV015",
                    "message": (
                        f"{tag_found} comment detected — track and resolve "
                        "before shipping."
                    ),
                    "line": line_no,
                }
            )
    return issues


# RUNNER — executes ALL rules


def run_all_cpp_rules(content: str, file_path: str) -> List[Issue]:
    """
    Runs all deterministic C++ rules against the given
    file content and returns a merged list of issues.

    Original rules (4): find_object_in_tick, get_component_in_tick,
                        infinite_loop_no_exit, runtime_asset_load
    CV001-CV010: raw new/delete, STL, printf, system headers,
                 large Tick, GEngine debug, float suffix,
                 UPROPERTY nullptr, GetWorld no-check
    CV011-CV015: UE_LOG in Tick, SpawnActor no-check, Cast no-check,
                 long function, TODO/FIXME/HACK comments
    """
    issues: List[Issue] = []

    # Original context-aware rules
    issues += detect_find_object_in_tick(content, file_path)
    issues += detect_get_component_in_tick(content, file_path)
    issues += detect_infinite_loop(content, file_path)
    issues += detect_runtime_load(content, file_path)

    # CV001-CV010
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

    # CV011-CV015
    issues += detect_log_error_in_tick(content, file_path)
    issues += detect_spawnactor_no_check(content, file_path)
    issues += detect_cast_no_check(content, file_path)
    issues += detect_long_function(content, file_path)
    issues += detect_todo_comments(content, file_path)

    return issues
