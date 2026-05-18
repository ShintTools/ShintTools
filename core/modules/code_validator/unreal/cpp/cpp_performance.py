# core/modules/code_validator/rules/cpp/cpp_performance.py
#
# Performance rules (CP) for Unreal Engine 5 C++.
# Detects expensive operations in hot paths like Tick(),
# unnecessary copies, and misuse of FORCEINLINE.
#
# Rule index:
#   CP001  FindObjectOfType inside Tick
#   CP002  GetComponent inside Tick
#   CP003  Large Tick() body
#   CP004  UE_LOG Error inside Tick()
#   CP005  FPlatformProcess::Sleep on game thread
#   CP006  GetAllActorsOfClass inside Tick
#   CP007  bCanEverTick = true in constructor
#   CP008  Heavy math operations inside Tick
#   CP009  FString operations inside Tick
#   CP010  FORCEINLINE on non-trivial function
#   CP011  FString passed by value
#   CP012  TArray copied inside loop
#   CP013  NewObject called inside loop
#   CP015  ensure() inside Tick/Update
#   CP016  Manual CollectGarbage call
#   CP017  Empty Tick() override (only calls Super)
#   CP018  SpawnActor called inside Tick/Update
# Total: 17 rules

import re
from typing import List

from code_validator.unreal.cpp._cpp_helpers import (
    Issue,
    _char_pos_for_line,
    _extract_class_name,
    _get_line_number,
    _is_cpp,
    _is_fixable,
    _is_header,
    _is_source,
)


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
    issues: List[Issue] = []
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
                    "rule_id": "CP001",
                    "category": "Performance",
                    "message": (
                        "FindObjectOfType called inside Tick(). "
                        "Cache the reference in BeginPlay instead"
                    ),
                    "snippet": snippet_line,
                    "fix_suggestion": "Cache in BeginPlay instead of calling in Tick",
                    "is_auto_fixable": _is_fixable("CP001"),
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
    issues: List[Issue] = []
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
                    "rule_id": "CP002",
                    "category": "Performance",
                    "message": (
                        "GetComponent called inside Tick(). "
                        "Cache the reference in BeginPlay instead"
                    ),
                    "snippet": snippet_line,
                    "fix_suggestion": "Cache in BeginPlay instead of calling in Tick",
                    "is_auto_fixable": _is_fixable("CP002"),
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

    issues: List[Issue] = []
    tick_match = re.search(
        r"void\s+(\w+)::Tick\b.*\{[^}]{300,}",
        content,
        re.DOTALL,
    )
    if tick_match:
        class_name = tick_match.group(1)
        line_no = _get_line_number(content, tick_match.start())
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
                "rule_id": "CP003",
                "category": "Performance",
                "message": (
                    "Tick() body appears very large — "
                    "move logic to helpers or timers."
                ),
                "snippet": snippet_line,
                "fix_suggestion": ("Extract logic to helper functions or use timers"),
                "is_auto_fixable": _is_fixable("CP003"),
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

    issues: List[Issue] = []
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
                        "snippet": body_line.strip(),
                        "fix_suggestion": "Remove UE_LOG from Tick",
                        "is_auto_fixable": _is_fixable("CP004"),
                    }
                )
    return issues


# CP005: FPlatformProcess::Sleep on game thread
def detect_sleep_on_game_thread(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects FPlatformProcess::Sleep calls outside of worker
    threads. Sleeping on the game thread blocks rendering and
    input processing for the entire duration of the sleep.
    Use timers, async tasks or latent actions instead.
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()
    for line_no, source_line in enumerate(source_lines, start=1):
        if re.search(r"\bFPlatformProcess::Sleep\s*\(", source_line):
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": _extract_class_name(
                        content,
                        _char_pos_for_line(source_lines, line_no),
                    ),
                    "severity": "error",
                    "rule_id": "CP005",
                    "category": "Performance",
                    "message": (
                        "FPlatformProcess::Sleep on game thread — "
                        "blocks rendering. Use timers or async "
                        "tasks instead."
                    ),
                    "snippet": source_line.strip(),
                    "fix_suggestion": "Replace Sleep() with FTimerHandle",
                    "is_auto_fixable": _is_fixable("CP005"),
                }
            )
    return issues


# CP006: GetAllActorsOfClass inside Tick
def detect_get_all_actors_in_tick(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects GetAllActorsOfClass or GetAllActorsWithInterface
    calls inside Tick or Update. These iterate every actor
    in the scene every frame — one of the most expensive
    operations possible in UE5. Cache results in BeginPlay
    or use an event-driven approach instead.
    """
    if not _is_source(file_path):
        return []

    issues: List[Issue] = []
    tick_pattern = re.compile(
        r"void\s+(\w+)::(?:Tick|Update)\s*\([^)]*\)\s*"
        r"\{([^}]*(?:\{[^}]*\}[^}]*)*)\}",
        re.DOTALL,
    )
    for tick_match in tick_pattern.finditer(content):
        class_name = tick_match.group(1)
        tick_body = tick_match.group(2)
        actor_match = re.search(
            r"\bGetAllActors(?:OfClass|WithInterface)\s*[<(]",
            tick_body,
        )
        if actor_match:
            body_start = tick_match.start(2)
            line_no = _get_line_number(content, body_start + actor_match.start())
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
                    "class": class_name,
                    "severity": "error",
                    "rule_id": "CP006",
                    "category": "Performance",
                    "message": (
                        "GetAllActorsOfClass called inside "
                        "Tick() — iterates every actor every "
                        "frame. Cache results in BeginPlay or "
                        "use an event-driven approach."
                    ),
                    "snippet": snippet_line,
                    "fix_suggestion": "Cache in BeginPlay instead of calling in Tick",
                    "is_auto_fixable": _is_fixable("CP006"),
                }
            )
    return issues


# CP007: bCanEverTick = true in constructor
def detect_tick_enabled_in_constructor(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects PrimaryActorTick.bCanEverTick = true set in
    the constructor. Tick is disabled by default in UE5
    for good reason — every Actor with Tick enabled runs
    its Tick function every frame. Only enable it if the
    Actor genuinely needs per-frame updates. Use timers
    or events for infrequent updates instead.
    """
    if not _is_source(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    # Match constructor signature with or without opening brace on same line
    # Supports both K&R style: Foo::Foo() {
    # and Allman style:        Foo::Foo()
    #                          {
    constructor_sig_pattern = re.compile(r"\b(\w+)::\1\s*\([^)]*\)")
    in_constructor = False
    pending_ctor_open = False  # waiting for '{' on next line (Allman style)
    brace_depth = 0
    class_name = "Unknown"

    for line_no, source_line in enumerate(source_lines, start=1):
        # Check for constructor signature
        if not in_constructor:
            ctor_match = constructor_sig_pattern.search(source_line)
            if ctor_match:
                class_name = ctor_match.group(1)
                if "{" in source_line:
                    # K&R style — brace on same line
                    in_constructor = True
                    brace_depth = source_line.count("{") - source_line.count("}")
                    pending_ctor_open = False
                else:
                    # Allman style — wait for '{' on next line
                    pending_ctor_open = True
                continue

            if pending_ctor_open:
                if "{" in source_line:
                    in_constructor = True
                    pending_ctor_open = False
                    brace_depth = source_line.count("{") - source_line.count("}")
                else:
                    # Not a brace line — was not actually a constructor
                    pending_ctor_open = False
                continue

        if in_constructor:
            brace_depth += source_line.count("{") - source_line.count("}")
            if brace_depth <= 0:
                in_constructor = False
                continue

            if re.search(
                r"\bPrimaryActorTick\.bCanEverTick\s*=\s*true",
                source_line,
            ):
                issues.append(
                    {
                        "asset_path": file_path,
                        "line": line_no,
                        "class": class_name,
                        "severity": "warning",
                        "rule_id": "CP007",
                        "category": "Performance",
                        "message": (
                            "Tick enabled in constructor — "
                            "disable it if per-frame updates "
                            "are not needed. Use timers or "
                            "events for infrequent logic."
                        ),
                        "snippet": source_line.strip(),
                        "fix_suggestion": "Set bCanEverTick = false",
                        "is_auto_fixable": _is_fixable("CP007"),
                    }
                )
    return issues


# CP008: Heavy math operations inside Tick
def detect_heavy_math_in_tick(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects expensive math calls (Sqrt, Sin, Cos, Atan2,
    Pow) inside Tick or Update. These are not free on CPU
    and should be cached or moved outside the hot path.
    Precompute values in BeginPlay or use lookup tables.
    """
    if not _is_source(file_path):
        return []

    issues: List[Issue] = []
    tick_pattern = re.compile(
        r"void\s+(\w+)::(?:Tick|Update)\s*\([^)]*\)\s*"
        r"\{([^}]*(?:\{[^}]*\}[^}]*)*)\}",
        re.DOTALL,
    )
    # Heavy math functions to detect
    heavy_math_pattern = re.compile(
        r"\bFMath::" r"(?:Sqrt|Sin|Cos|Tan|Atan2|Pow|Exp|Log)\s*\("
    )

    for tick_match in tick_pattern.finditer(content):
        class_name = tick_match.group(1)
        tick_body = tick_match.group(2)
        math_match = heavy_math_pattern.search(tick_body)
        if math_match:
            body_start = tick_match.start(2)
            line_no = _get_line_number(content, body_start + math_match.start())
            source_lines = content.splitlines()
            snippet_line = (
                source_lines[line_no - 1].strip()
                if line_no <= len(source_lines)
                else ""
            )
            func_name = math_match.group(0).strip("(")
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": class_name,
                    "severity": "warning",
                    "rule_id": "CP008",
                    "category": "Performance",
                    "message": (
                        f"Expensive math '{func_name}' called "
                        "inside Tick() — precompute in "
                        "BeginPlay or cache the result."
                    ),
                    "snippet": snippet_line,
                    "fix_suggestion": "Cache this calculation in BeginPlay",
                    "is_auto_fixable": _is_fixable("CP008"),
                }
            )
    return issues


# CP009: FString operations inside Tick
def detect_string_ops_in_tick(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects FString concatenation or FString::Printf calls
    inside Tick or Update. FString operations allocate heap
    memory every frame, causing GC pressure and frame spikes.
    Move string operations outside Tick or cache the result.
    """
    if not _is_source(file_path):
        return []

    issues: List[Issue] = []
    tick_pattern = re.compile(
        r"void\s+(\w+)::(?:Tick|Update)\s*\([^)]*\)\s*"
        r"\{([^}]*(?:\{[^}]*\}[^}]*)*)\}",
        re.DOTALL,
    )
    string_op_pattern = re.compile(
        r"\bFString\s*\+=" r"|\bFString::Printf\s*\(" r"|\bFString::Format\s*\("
    )

    for tick_match in tick_pattern.finditer(content):
        class_name = tick_match.group(1)
        tick_body = tick_match.group(2)
        str_match = string_op_pattern.search(tick_body)
        if str_match:
            body_start = tick_match.start(2)
            line_no = _get_line_number(content, body_start + str_match.start())
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
                    "class": class_name,
                    "severity": "warning",
                    "rule_id": "CP009",
                    "category": "Performance",
                    "message": (
                        "FString operation inside Tick() — "
                        "allocates heap memory every frame. "
                        "Cache the result or move outside Tick."
                    ),
                    "snippet": snippet_line,
                    "fix_suggestion": "Cache string operation in BeginPlay",
                    "is_auto_fixable": _is_fixable("CP009"),
                }
            )
    return issues


# CP010: FORCEINLINE on non-trivial function
def detect_forceinline_large_function(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects FORCEINLINE used on functions with more than
    5 lines in their body. FORCEINLINE expands all code
    into the calling function — on large functions this
    causes code bloat, increased build times and can hurt
    instruction cache performance.
    Epic Coding Standard: 'Be conservative in your use
    of FORCEINLINE.'
    """
    if not _is_header(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()
    total_lines = len(source_lines)

    # Threshold for what is considered non-trivial
    # Configurable: adjust if your studio uses larger inlines
    _MAX_INLINE_LINES: int = 5

    forceinline_pattern = re.compile(r"\bFORCEINLINE\b")

    line_idx = 0
    while line_idx < total_lines:
        source_line = source_lines[line_idx]
        if not forceinline_pattern.search(source_line):
            line_idx += 1
            continue

        func_line_no = line_idx + 1

        # Find the opening brace
        brace_depth = 0
        body_start_idx = line_idx
        found_brace = False

        for search_idx in range(line_idx, min(line_idx + 5, total_lines)):
            brace_depth += source_lines[search_idx].count("{") - source_lines[
                search_idx
            ].count("}")
            if brace_depth > 0:
                body_start_idx = search_idx
                found_brace = True
                break

        if not found_brace:
            line_idx += 1
            continue

        # Count lines in the function body
        end_idx = body_start_idx + 1
        while end_idx < total_lines and brace_depth > 0:
            brace_depth += source_lines[end_idx].count("{") - source_lines[
                end_idx
            ].count("}")
            end_idx += 1

        func_length = end_idx - body_start_idx

        if func_length > _MAX_INLINE_LINES:
            # Extract function name
            name_match = re.search(r"\b(\w+)\s*\(", source_line)
            func_name = name_match.group(1) if name_match else "Unknown"
            issues.append(
                {
                    "asset_path": file_path,
                    "line": func_line_no,
                    "class": _extract_class_name(
                        content,
                        _char_pos_for_line(source_lines, func_line_no),
                    ),
                    "severity": "warning",
                    "rule_id": "CP010",
                    "category": "Performance",
                    "message": (
                        f"FORCEINLINE on '{func_name}' which "
                        f"is {func_length} lines — use "
                        "FORCEINLINE only for trivial "
                        f"accessors (max {_MAX_INLINE_LINES} "
                        "lines)."
                    ),
                    "snippet": source_line.strip(),
                    "fix_suggestion": "Replace FORCEINLINE with inline",
                    "is_auto_fixable": _is_fixable("CP010"),
                }
            )
        line_idx = end_idx
    return issues


# CP011: FString passed by value instead of const reference
def detect_fstring_by_value(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects function parameters where FString is passed by value.
    FString contains heap-allocated data; passing by value copies
    the entire buffer. Use const FString& for input parameters.
    """
    if not _is_header(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    # Pattern: function parameter with FString not followed by & or *
    # Matches: void Func(FString Name, ...) but not void Func(const FString& Name)
    param_pattern = re.compile(
        r"(?:void|bool|int32|float|FString|FName|FVector|"
        r"FRotator|FTransform|AActor\*|UObject\*|\w+)\s+"
        r"\w+\s*\([^)]*\bFString\s+(\w+)\s*[,)]"
    )

    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()
        if stripped.startswith("//"):
            continue
        # Skip if line contains const FString& (correct usage)
        if "const FString&" in source_line or "FString&" in source_line:
            continue

        param_match = param_pattern.search(source_line)
        if param_match:
            var_name = param_match.group(1)
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": _extract_class_name(
                        content,
                        _char_pos_for_line(source_lines, line_no),
                    ),
                    "severity": "warning",
                    "rule_id": "CP011",
                    "category": "Performance",
                    "message": (
                        f"FString '{var_name}' passed by value — "
                        "use 'const FString&' to avoid heap copy."
                    ),
                    "snippet": source_line.strip(),
                    "fix_suggestion": "Pass FString by const reference",
                    "is_auto_fixable": _is_fixable("CP011"),
                }
            )

    return issues


# CP012: TArray copied inside loop
def detect_tarray_copy_in_loop(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects TArray being copied (not referenced) inside a loop.
    Copying a TArray allocates new heap memory on every iteration.
    Use const TArray<T>& for read-only access.
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []

    # Find loop bodies
    loop_pattern = re.compile(
        r"(?:for|while)\s*\([^)]*\)\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}",
        re.DOTALL,
    )

    # Inside loop: TArray<Type> VarName = (copy assignment)
    copy_pattern = re.compile(r"\bTArray\s*<[^>]+>\s+(\w+)\s*=\s*(?!MoveTemp)")

    for loop_match in loop_pattern.finditer(content):
        loop_body = loop_match.group(1)
        copy_match = copy_pattern.search(loop_body)

        if copy_match:
            var_name = copy_match.group(1)
            line_no = _get_line_number(
                content,
                loop_match.start(1) + copy_match.start(),
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
                    "severity": "error",
                    "rule_id": "CP012",
                    "category": "Performance",
                    "message": (
                        f"TArray '{var_name}' copied inside loop — "
                        "use const TArray<T>& to avoid heap "
                        "allocation every iteration."
                    ),
                    "snippet": snippet_line,
                    "fix_suggestion": "Use const TArray reference in loop",
                    "is_auto_fixable": _is_fixable("CP012"),
                }
            )

    return issues


# CP013: NewObject called inside loop
def detect_new_object_in_loop(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects NewObject<T>() calls inside loops. Creating UObjects
    is expensive and triggers garbage collector bookkeeping.
    Pre-allocate objects before the loop or use object pooling.
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []

    loop_pattern = re.compile(
        r"(?:for|while)\s*\([^)]*\)\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}",
        re.DOTALL,
    )

    for loop_match in loop_pattern.finditer(content):
        loop_body = loop_match.group(1)
        newobj_match = re.search(r"\bNewObject\s*<", loop_body)

        if newobj_match:
            line_no = _get_line_number(
                content,
                loop_match.start(1) + newobj_match.start(),
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
                    "rule_id": "CP013",
                    "category": "Performance",
                    "message": (
                        "NewObject<T>() called inside loop — "
                        "pre-allocate objects or use pooling."
                    ),
                    "snippet": snippet_line,
                    "fix_suggestion": "Pre-allocate outside the loop",
                    "is_auto_fixable": _is_fixable("CP013"),
                }
            )

    return issues


# CP015: ensure() inside Tick/Update
def detect_ensure_in_tick(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects ensure() calls within Tick() or Update() functions.

    ensure() evaluates its condition every frame, adding measurable overhead
    in hot paths. The autofix wraps the call with
    `#if !UE_BUILD_SHIPPING ... #endif`, Epic's official pattern
    for validation in hot paths: maintains validation in development builds
    and eliminates the overhead in Shipping.
    """
    if not _is_source(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    # Traditional regex with body matching limited to 1 level of nesting.
    # This is the maximum Python re can do without a real parser. The plugin
    # with Tree-sitter will perform exact function_body matching.
    tick_pattern = re.compile(
        r"void\s+(\w+)::(?:Tick|Update)\s*\([^)]*\)\s*"
        r"\{([^}]*(?:\{[^}]*\}[^}]*)*)\}",
        re.DOTALL,
    )

    for tick_match in tick_pattern.finditer(content):
        class_name = tick_match.group(1)
        tick_body = tick_match.group(2)
        body_start = tick_match.start(2)

        # Find ALL occurrences of ensure() in the body.
        for m in re.finditer(r"\bensure\s*\(", tick_body):
            # Filter out variants we do NOT want to touch.
            tail = tick_body[m.start() : m.start() + 32]
            if (
                tail.startswith("ensureAlways")
                or tail.startswith("ensureMsgf")
                or tail.startswith("ensureAlwaysMsgf")
            ):
                continue

            abs_pos = body_start + m.start()
            line_no = _get_line_number(content, abs_pos)
            line_idx = line_no - 1

            if line_idx >= len(source_lines):
                continue

            snippet_line = source_lines[line_idx].strip()
            if snippet_line.startswith("//"):
                continue

            # Idempotence: if already inside a guard #if !UE_BUILD_SHIPPING
            # before, do not report. Scan backwards looking for the last
            # relevant preprocessor directive without crossing an #endif.
            already_guarded = False
            for back in range(line_idx - 1, -1, -1):
                ln = source_lines[back].strip()
                if ln.startswith("#endif"):
                    break
                if ln.startswith("#if") and "UE_BUILD_SHIPPING" in ln and "!" in ln:
                    already_guarded = True
                    break
            if already_guarded:
                continue

            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": class_name,
                    "severity": "warning",
                    "rule_id": "CP015",
                    "category": "Performance",
                    "message": (
                        "ensure() in Tick() evaluates the condition "
                        "every frame — wrap with "
                        "#if !UE_BUILD_SHIPPING to eliminate the "
                        "cost in Shipping builds."
                    ),
                    "snippet": snippet_line,
                    "fix_suggestion": (
                        "#if !UE_BUILD_SHIPPING\n" f"    {snippet_line}\n" "#endif"
                    ),
                    "is_auto_fixable": True,
                }
            )

    return issues


# CP016: Manual CollectGarbage call
def detect_garbage_collect_call(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects manual CollectGarbage() calls. Forcing garbage
    collection causes frame hitches and is almost never needed.
    Let UE5 manage GC automatically or use incremental GC.
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()
        if stripped.startswith("//"):
            continue

        if re.search(r"\bCollectGarbage\s*\(", source_line):
            # Skip if inside test file
            if "test" in file_path.lower():
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
                    "rule_id": "CP016",
                    "category": "Performance",
                    "message": (
                        "Manual CollectGarbage() call — causes "
                        "frame hitches. Let UE5 manage GC or "
                        "use ForceGarbageCollection with care."
                    ),
                    "snippet": source_line.strip(),
                    "fix_suggestion": "Remove manual CollectGarbage() call",
                    "is_auto_fixable": _is_fixable("CP016"),
                }
            )

    return issues


# CP017: Empty Tick() override — only calls Super or is empty
def detect_empty_tick_override(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects Tick() overrides that are empty or only call
    Super::Tick(DeltaTime) without adding any logic.
    An empty Tick costs ~0.1ms per actor per frame due to
    the virtual call overhead and tick registration. If the
    actor doesn't need per-frame updates, remove the Tick
    override and set bCanEverTick = false in the constructor.
    """
    if not _is_source(file_path):
        return []

    issues: List[Issue] = []

    # Match Tick implementations with their full body
    tick_pattern = re.compile(
        r"void\s+(\w+)::Tick\s*\(\s*float\s+(\w+)\s*\)\s*"
        r"\{([^}]*(?:\{[^}]*\}[^}]*)*)\}",
        re.DOTALL,
    )

    for tick_match in tick_pattern.finditer(content):
        class_name = tick_match.group(1)
        param_name = tick_match.group(2)
        body = tick_match.group(3).strip()

        # Strip comments from the body for analysis
        body_no_comments = re.sub(r"//[^\n]*", "", body).strip()
        body_no_comments = re.sub(
            r"/\*.*?\*/", "", body_no_comments, flags=re.DOTALL
        ).strip()

        # Empty body
        is_empty = not body_no_comments

        # Body that only contains Super::Tick(DeltaTime);
        is_super_only = bool(
            re.fullmatch(
                r"Super::Tick\s*\(\s*" + re.escape(param_name) + r"\s*\)\s*;",
                body_no_comments,
            )
        )

        if is_empty or is_super_only:
            line_no = _get_line_number(content, tick_match.start())
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": class_name,
                    "severity": "warning",
                    "rule_id": "CP017",
                    "category": "Performance",
                    "message": (
                        f"{class_name}::Tick() is empty or only "
                        "calls Super — costs ~0.1ms per actor "
                        "per frame. Remove Tick override and set "
                        "bCanEverTick = false in the constructor."
                    ),
                    "snippet": (f"void {class_name}::Tick(float " f"{param_name})"),
                    "fix_suggestion": ("Comment out empty Tick override"),
                    "is_auto_fixable": _is_fixable("CP017"),
                }
            )

    return issues


# CP018: SpawnActor called inside Tick/Update
def detect_spawn_actor_in_tick(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects SpawnActor calls inside Tick or Update functions.
    Spawning an actor every frame creates thousands of objects
    per minute, exhausts memory, and overwhelms the garbage
    collector. Move spawning to BeginPlay, events, or timers.
    Also catches SpawnActorDeferred.
    """
    if not _is_source(file_path):
        return []

    issues: List[Issue] = []
    tick_pattern = re.compile(
        r"void\s+(\w+)::(?:Tick|Update)\s*\([^)]*\)\s*"
        r"\{([^}]*(?:\{[^}]*\}[^}]*)*)\}",
        re.DOTALL,
    )

    spawn_pattern = re.compile(r"\bSpawnActor(?:Deferred)?\s*<")

    for tick_match in tick_pattern.finditer(content):
        class_name = tick_match.group(1)
        tick_body = tick_match.group(2)

        # Skip if body contains comment-only spawn mentions
        spawn_match = spawn_pattern.search(tick_body)
        if not spawn_match:
            continue

        # Verify the spawn is not inside a comment
        body_start = tick_match.start(2)
        abs_pos = body_start + spawn_match.start()
        line_no = _get_line_number(content, abs_pos)
        source_lines = content.splitlines()

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
                "rule_id": "CP018",
                "category": "Performance",
                "message": (
                    "SpawnActor called inside Tick() — "
                    "creates a new actor every frame "
                    "(3600/min at 60fps). Move spawning "
                    "to BeginPlay, events, or timers."
                ),
                "snippet": line_text,
                "fix_suggestion": ("Move SpawnActor to BeginPlay or a timer"),
                "is_auto_fixable": False,
            }
        )

    return issues
