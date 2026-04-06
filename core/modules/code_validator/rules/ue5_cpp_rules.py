# core/modules/code_validator/rules/ue5_cpp_rules.py
#
# Deterministic C++ rules for Unreal Engine 5.
# Each rule function receives (content, file_path)
# and returns a list of issue dicts.
#
# Issue fields: asset_path, line, class, severity,
#               rule_id, category, message,
#               snippet, fix_suggestion, is_auto_fixable
#
# ── Rule index ────────────────────────────────────────
# Performance (CP):     CP001-CP016  (16 rules)
# Best Practices (CB):  CB001-CB032  (32 rules)
# Security (CS):        CS001-CS012  (12 rules)
# Maintainability (CM): CM001-CM011  (11 rules)
# Total: 71 rules
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
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
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
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
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
                "fix_suggestion": "",
                "is_auto_fixable": False,
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
                        "fix_suggestion": "",
                        "is_auto_fixable": False,
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
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
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
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
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

    # Find constructor bodies
    constructor_pattern = re.compile(r"\b(\w+)::\1\s*\([^)]*\)\s*\{")
    in_constructor = False
    brace_depth = 0
    class_name = "Unknown"

    for line_no, source_line in enumerate(source_lines, start=1):
        ctor_match = constructor_pattern.search(source_line)
        if ctor_match and not in_constructor:
            in_constructor = True
            class_name = ctor_match.group(1)
            brace_depth = source_line.count("{") - source_line.count("}")
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
                        "fix_suggestion": (
                            source_line.replace("true", "false").strip()
                        ),
                        "is_auto_fixable": True,
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
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
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
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
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
                    "fix_suggestion": re.sub(
                        r"\bFORCEINLINE\b", "inline", source_line
                    ).strip(),
                    "is_auto_fixable": True,
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
                    "fix_suggestion": source_line.replace(
                        f"FString {var_name}",
                        f"const FString& {var_name}",
                    ).strip(),
                    "is_auto_fixable": True,
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
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
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
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
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
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
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
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
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
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
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
    for line_no, source_line in enumerate(source_lines, start=1):
        if re.search(r"\bnew\s+\w", source_line):
            # Build fix: replace "new Type(...)" with "NewObject<Type>(this)"
            fix = source_line.strip()
            new_match = re.search(
                r"\bnew\s+(\w+)\s*(?:\([^)]*\)|\[[^\]]*\])", source_line
            )
            if new_match:
                type_name = new_match.group(1)
                fix = re.sub(
                    r"\bnew\s+\w+\s*(?:\([^)]*\)|\[[^\]]*\])",
                    f"NewObject<{type_name}>(this)",
                    source_line,
                ).strip()
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
                    "fix_suggestion": fix,
                    "is_auto_fixable": True,
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
    for line_no, source_line in enumerate(source_lines, start=1):
        if re.search(r"\bdelete\s+\w", source_line):
            # Fix: comment out the delete line
            fix = (
                "// "
                + source_line.strip()
                + "  // REMOVED: UObjects are garbage-collected"
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
                    "rule_id": "CB004",
                    "category": "Best Practices",
                    "message": (
                        "Raw 'delete' detected — UObjects are "
                        "garbage-collected; manual delete will "
                        "crash."
                    ),
                    "snippet": source_line.strip(),
                    "fix_suggestion": fix,
                    "is_auto_fixable": True,
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
                    "snippet": source_line.strip(),
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
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
    for line_no, source_line in enumerate(source_lines, start=1):
        if re.search(r"\bprintf\s*\(", source_line):
            # Fix: replace printf(...) with UE_LOG(LogTemp, Log, ...)
            fix = re.sub(
                r"\bprintf\s*\(",
                "UE_LOG(LogTemp, Log, ",
                source_line,
            ).strip()
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
                    "fix_suggestion": fix,
                    "is_auto_fixable": True,
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
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
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
    for line_no, source_line in enumerate(source_lines, start=1):
        if re.search(
            r"\bfloat\b\s+\w+\s*=\s*[0-9]+\.[0-9]+[^f]",
            source_line,
        ):
            # Fix: add 'f' suffix to float literals missing it
            fix = re.sub(
                r"(\d+\.\d+)(?!f)",
                r"\1f",
                source_line,
            ).strip()
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
                    "fix_suggestion": fix,
                    "is_auto_fixable": True,
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
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
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
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
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
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
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
                        "fix_suggestion": "",
                        "is_auto_fixable": False,
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
    # Matches (TypeName)variable — avoids matching function calls
    cast_pattern = re.compile(
        r"\(\s*(?:int8|int16|int32|int64|uint8|uint16|uint32|uint64"
        r"|float|double|bool|char|TCHAR|SIZE_T)\s*\)\s*\w"
    )

    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()
        if stripped.startswith("//"):
            continue
        cast_match = cast_pattern.search(source_line)
        if cast_match:
            cast_text = cast_match.group(0).strip()
            # Suggest static_cast equivalent
            type_match = re.search(r"\(\s*(\w+)\s*\)", cast_text)
            type_name = type_match.group(1) if type_match else "T"
            fix = cast_pattern.sub(
                f"static_cast<{type_name}>(", source_line, count=1
            ).strip()
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
                        "C-style cast detected — use "
                        "static_cast<T>() or Cast<T>() instead."
                    ),
                    "snippet": source_line.strip(),
                    "fix_suggestion": fix,
                    "is_auto_fixable": True,
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
        for next_line in source_lines[line_no : line_no + 5]:
            next_stripped = next_line.strip()
            if not next_stripped:
                continue
            if re.search(rf"\b{re.escape(var_name)}\s*->", next_stripped):
                if not re.search(r"\bif\b", next_stripped):
                    issues.append(
                        {
                            "asset_path": file_path,
                            "line": line_no,
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
                            "snippet": source_line.strip(),
                            "fix_suggestion": "",
                            "is_auto_fixable": False,
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
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
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
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
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
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
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
                        "fix_suggestion": (
                            "UPROPERTY(EditAnywhere, BlueprintReadWrite)"
                            f"\n\t{stripped}"
                        ),
                        "is_auto_fixable": True,
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
            # Extract type and size for the suggestion
            type_match = re.search(
                r"\b(\w+)\s+" + re.escape(var_name) + r"\s*\[\s*(\d+)",
                source_line,
            )
            if type_match:
                elem_type = type_match.group(1)
                fix = f"TArray<{elem_type}> {var_name};"
            else:
                fix = ""
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
                    "fix_suggestion": fix,
                    "is_auto_fixable": bool(fix),
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
                        "fix_suggestion": re.sub(
                            r"~(\w+)",
                            r"virtual ~\1",
                            source_line,
                        ).strip(),
                        "is_auto_fixable": True,
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
                    "fix_suggestion": re.sub(
                        r"\bFString\b", "FName", source_line
                    ).strip(),
                    "is_auto_fixable": True,
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
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
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

    # Pattern: virtual ReturnType FuncName(...) without override
    virtual_pattern = re.compile(
        r"\bvirtual\s+[\w:<>*&]+\s+(\w+)\s*\([^)]*\)\s*" r"(?:const\s*)?(?!override)"
    )

    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()
        if stripped.startswith("//"):
            continue

        virtual_match = virtual_pattern.search(source_line)
        if virtual_match:
            # Skip pure virtual (= 0) and destructors
            if "= 0" in source_line or "~" in source_line:
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
                    "snippet": source_line.strip(),
                    "fix_suggestion": source_line.rstrip().rstrip(";") + " override;",
                    "is_auto_fixable": True,
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
                    "fix_suggestion": "Add Super::BeginPlay(); as first line",
                    "is_auto_fixable": False,
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
                        "fix_suggestion": "",
                        "is_auto_fixable": False,
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
                            "fix_suggestion": re.sub(
                                r'=\s*"([^"]+)"',
                                r'= TEXT("\1")',
                                source_line,
                            ).strip(),
                            "is_auto_fixable": True,
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
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
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
                        "fix_suggestion": "",
                        "is_auto_fixable": False,
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

    issues: List[Issue] = []
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
                    "snippet": source_line.strip(),
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
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
                            "snippet": source_line.strip(),
                            "fix_suggestion": "",
                            "is_auto_fixable": False,
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
                            "snippet": source_line.strip(),
                            "fix_suggestion": "",
                            "is_auto_fixable": False,
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
        if stripped.startswith("//"):
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
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
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
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()
        if stripped.startswith("//"):
            continue

        # Match: ArrayVar[SomeVariable] — skip literals like [0]
        access_match = re.search(
            r"\b(\w+)\s*\[\s*([A-Za-z_]\w*)\s*\]",
            source_line,
        )
        if not access_match:
            continue

        array_name = access_match.group(1)
        index_var = access_match.group(2)

        # Skip common loop variables that are typically safe
        if index_var in {"i", "j", "k", "idx", "Index"}:
            continue

        # Check preceding 5 lines for IsValidIndex
        start_idx = max(0, line_no - 6)
        preceding = " ".join(source_lines[start_idx : line_no - 1])
        has_check = re.search(
            rf"\b{re.escape(array_name)}\s*\.\s*IsValidIndex\s*"
            rf"\(\s*{re.escape(index_var)}",
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
                    "rule_id": "CS005",
                    "category": "Security",
                    "message": (
                        f"TArray '{array_name}' accessed at "
                        f"index '{index_var}' without "
                        "IsValidIndex() check — will crash "
                        "if index is out of bounds."
                    ),
                    "snippet": source_line.strip(),
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
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

    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()
        if stripped.startswith("//"):
            continue
        if re.search(r"\bGetOwner\(\)\s*->", source_line):
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
                    "snippet": source_line.strip(),
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
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
        r"void\s+\w+::On(?:Component|Actor)Begin(?:Overlap|" r"Hit)\s*\([^)]*\)\s*\{",
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
                # Check if there's a null-check in the function so far
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
                            "fix_suggestion": "",
                            "is_auto_fixable": False,
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
                rf"\b{re.escape(var_name)}\s*(?:\.Get\(\)|->)",
                source_line,
            ):
                continue

            # Check preceding 5 lines for IsValid()
            start_idx = max(0, line_no - 6)
            preceding = " ".join(source_lines[start_idx : line_no - 1])
            has_check = re.search(
                rf"\b{re.escape(var_name)}\s*\.\s*IsValid\s*\(\)",
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
                            "check — the object may have been "
                            "garbage collected."
                        ),
                        "snippet": source_line.strip(),
                        "fix_suggestion": "",
                        "is_auto_fixable": False,
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
                        "Insecure http:// URL — use https:// "
                        "to encrypt data in transit."
                    ),
                    "snippet": source_line.strip(),
                    "fix_suggestion": source_line.replace(
                        "http://", "https://"
                    ).strip(),
                    "is_auto_fixable": True,
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
        (r'\bPassword\s*=\s*TEXT\s*\(\s*"[^"]+"\s*\)', "password"),
        (r'\bApiKey\s*=\s*TEXT\s*\(\s*"[^"]+"\s*\)', "API key"),
        (r'\bSecret\s*=\s*TEXT\s*\(\s*"[^"]+"\s*\)', "secret"),
        (r'\bToken\s*=\s*TEXT\s*\(\s*"[^"]+"\s*\)', "token"),
        (r'\bPrivateKey\s*=\s*TEXT\s*\(\s*"[^"]+"\s*\)', "private key"),
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
                            f"Hardcoded {secret_type} detected — "
                            "store secrets in config or environment "
                            "variables, never in source code."
                        ),
                        "snippet": source_line.strip()[:60] + "...",
                        "fix_suggestion": "",
                        "is_auto_fixable": False,
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

    issues: List[Issue] = []
    source_lines = content.splitlines()
    for line_no, source_line in enumerate(source_lines, start=1):
        if re.search(r"GEngine->AddOnScreenDebugMessage", source_line):
            # Fix: comment out the debug message
            fix = "// " + source_line.strip() + "  // REMOVED: debug message"
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
                    "snippet": source_line.strip(),
                    "fix_suggestion": fix,
                    "is_auto_fixable": True,
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

    issues: List[Issue] = []
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
                snippet_line = (
                    source_lines[start_line - 1].strip()
                    if start_line <= len(source_lines)
                    else ""
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
                        "snippet": snippet_line,
                        "fix_suggestion": "",
                        "is_auto_fixable": False,
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

    issues: List[Issue] = []
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
                    "snippet": source_line.strip(),
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
                }
            )
    return issues


# CM004: File too long (> 500 lines)
def detect_file_too_long(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects source files exceeding the maximum line count.
    Large files are hard to navigate and usually indicate
    that a class has too many responsibilities.
    Split into smaller, focused files.
    Threshold defined in Tech Doc Section 12.1 (max_file_lines: 500).
    """
    if not _is_cpp(file_path):
        return []

    # Umbral de líneas por archivo — configurable por estudio en
    # shinttools.config.json bajo code_validator.max_file_lines.
    # 500 líneas es el valor por defecto del Tech Doc de ShintTools.
    _MAX_FILE_LINES: int = 500

    total_lines = len(content.splitlines())
    if total_lines <= _MAX_FILE_LINES:
        return []

    return [
        {
            "asset_path": file_path,
            "line": 1,
            "class": "Unknown",
            "severity": "warning",
            "rule_id": "CM005",
            "category": "Maintainability",
            "message": (
                f"File has {total_lines} lines "
                f"(max: {_MAX_FILE_LINES}) — split into "
                "smaller, focused files."
            ),
            "snippet": content.splitlines()[0].strip(),
            "fix_suggestion": "",
            "is_auto_fixable": False,
        }
    ]


# CM005: Too many function parameters (> 5)
def detect_too_many_parameters(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects functions with more parameters than the threshold.
    Functions with many parameters are harder to call correctly,
    test and maintain. Consider passing a dedicated struct instead.
    Epic Coding Standard: 'Avoid overly-long function parameter lists.'
    """
    if not _is_cpp(file_path):
        return []

    # Número máximo de parámetros por función — configurable por estudio.
    # 5 es el valor por defecto, usado como referencia en estudios AA.
    # Modifícalo en shinttools.config.json bajo
    # code_validator.max_function_parameters si tu estudio
    # usa una convención diferente (algunos permiten hasta 6 o 7).
    _MAX_PARAMS: int = 5

    issues: List[Issue] = []
    source_lines = content.splitlines()

    # Matches function declarations/definitions with a parameter list.
    # Captures: return type + name + full parameter list.
    func_pattern = re.compile(
        r"^\s*(?:[\w:<>*&~]+\s+)+(\w+)\s*\(([^;{}]*)\)\s*"
        r"(?:const\s*)?(?:override\s*)?(?:noexcept\s*)?"
        r"(?:\{|;)"
    )

    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()
        if stripped.startswith("//") or stripped.startswith("#"):
            continue

        func_match = func_pattern.match(source_line)
        if not func_match:
            continue

        func_name = func_match.group(1)
        param_list = func_match.group(2).strip()

        # Skip empty parameter lists and void
        if not param_list or param_list == "void":
            continue

        # Count parameters by splitting on commas, ignoring
        # commas inside template angle brackets e.g. TMap<K, V>
        depth = 0
        param_count = 1
        for char in param_list:
            if char in "<([":
                depth += 1
            elif char in ">)]":
                depth -= 1
            elif char == "," and depth == 0:
                param_count += 1

        if param_count <= _MAX_PARAMS:
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
                "rule_id": "CM006",
                "category": "Maintainability",
                "message": (
                    f"Function '{func_name}' has {param_count} "
                    f"parameters (max: {_MAX_PARAMS}) — consider "
                    "passing a dedicated struct instead."
                ),
                "snippet": source_line.strip(),
                "fix_suggestion": "",
                "is_auto_fixable": False,
            }
        )

    return issues


# CM006: Deep nesting (> 4 levels)
def detect_deep_nesting(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects code blocks nested more than 4 levels deep.
    Deep nesting makes code hard to read and indicates
    the function should be refactored.
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    _MAX_NESTING: int = 4
    brace_depth = 0
    reported_lines: set = set()

    for line_no, source_line in enumerate(source_lines, start=1):
        stripped = source_line.strip()
        if stripped.startswith("//"):
            continue

        # Count braces
        open_braces = source_line.count("{")
        close_braces = source_line.count("}")

        if open_braces > 0:
            brace_depth += open_braces
            if brace_depth > _MAX_NESTING and line_no not in reported_lines:
                reported_lines.add(line_no)
                issues.append(
                    {
                        "asset_path": file_path,
                        "line": line_no,
                        "class": _extract_class_name(
                            content,
                            _char_pos_for_line(source_lines, line_no),
                        ),
                        "severity": "warning",
                        "rule_id": "CM006",
                        "category": "Maintainability",
                        "message": (
                            f"Code nested {brace_depth} levels deep "
                            f"(max: {_MAX_NESTING}) — refactor to "
                            "reduce complexity."
                        ),
                        "snippet": source_line.strip(),
                        "fix_suggestion": "",
                        "is_auto_fixable": False,
                    }
                )

        brace_depth -= close_braces
        if brace_depth < 0:
            brace_depth = 0

    return issues


# CM007: Duplicate #include
def detect_duplicate_include(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects the same header included multiple times in a file.
    While pragma once prevents multiple inclusion, duplicate
    #include lines are redundant and should be cleaned up.
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()
    seen_includes: dict = {}

    for line_no, source_line in enumerate(source_lines, start=1):
        include_match = re.search(r'#include\s+[<"]([^>"]+)[>"]', source_line)
        if include_match:
            header = include_match.group(1)
            if header in seen_includes:
                issues.append(
                    {
                        "asset_path": file_path,
                        "line": line_no,
                        "class": "Unknown",
                        "severity": "info",
                        "rule_id": "CM007",
                        "category": "Maintainability",
                        "message": (
                            f"Duplicate #include '{header}' — "
                            f"already included on line "
                            f"{seen_includes[header]}."
                        ),
                        "snippet": source_line.strip(),
                        "fix_suggestion": "",
                        "is_auto_fixable": False,
                    }
                )
            else:
                seen_includes[header] = line_no

    return issues


# CM008: Empty destructor
def detect_empty_destructor(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects empty destructor implementations. If a destructor
    has no cleanup logic, it can be removed or defaulted
    unless it needs to be virtual.
    """
    if not _is_cpp(file_path):
        return []

    issues: List[Issue] = []
    source_lines = content.splitlines()

    for line_no, source_line in enumerate(source_lines, start=1):
        # Match: ~ClassName() { } or ~ClassName()\n{\n}
        if re.search(r"~\w+\s*\(\s*\)\s*\{\s*\}", source_line):
            issues.append(
                {
                    "asset_path": file_path,
                    "line": line_no,
                    "class": _extract_class_name(
                        content,
                        _char_pos_for_line(source_lines, line_no),
                    ),
                    "severity": "info",
                    "rule_id": "CM008",
                    "category": "Maintainability",
                    "message": (
                        "Empty destructor — remove or use "
                        "'= default' unless it must be virtual."
                    ),
                    "snippet": source_line.strip(),
                    "fix_suggestion": "",
                    "is_auto_fixable": False,
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

    Performance (CP):      CP001 - CP010
    Best Practices (CB):   CB001 - CB020
    Security (CS):         CS001 - CS008
    Maintainability (CM):  CM001 - CM005
    """
    issues: List[Issue] = []

    # Performance
    issues += detect_find_object_in_tick(content, file_path)
    issues += detect_get_component_in_tick(content, file_path)
    issues += detect_large_tick(content, file_path)
    issues += detect_log_error_in_tick(content, file_path)
    issues += detect_sleep_on_game_thread(content, file_path)
    issues += detect_get_all_actors_in_tick(content, file_path)
    issues += detect_tick_enabled_in_constructor(content, file_path)
    issues += detect_heavy_math_in_tick(content, file_path)
    issues += detect_string_ops_in_tick(content, file_path)
    issues += detect_forceinline_large_function(content, file_path)
    issues += detect_fstring_by_value(content, file_path)
    issues += detect_tarray_copy_in_loop(content, file_path)
    issues += detect_new_object_in_loop(content, file_path)
    #       issues += detect_ftext_format_in_tick(content, file_path)
    #       issues += detect_ensure_in_tick(content, file_path)
    issues += detect_garbage_collect_call(content, file_path)

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
    issues += detect_magic_numbers(content, file_path)
    issues += detect_empty_if_body(content, file_path)
    issues += detect_c_style_cast(content, file_path)
    issues += detect_nullptr_deref(content, file_path)
    issues += detect_hardcoded_path(content, file_path)
    issues += detect_auto_without_obvious_type(content, file_path)
    issues += detect_string_concat_in_loop(content, file_path)
    issues += detect_public_member_without_uproperty(content, file_path)
    issues += detect_raw_c_array(content, file_path)
    issues += detect_non_virtual_destructor(content, file_path)
    issues += detect_fstring_as_identifier(content, file_path)
    issues += detect_lambda_implicit_capture(content, file_path)
    #       issues += detect_ensure_not_always(content, file_path)
    issues += detect_missing_override(content, file_path)
    issues += detect_missing_super_beginplay(content, file_path)
    issues += detect_ufunction_missing_category(content, file_path)
    #     issues += detect_exposed_on_spawn_no_default(content, file_path)
    #     issues += detect_delegate_no_broadcast(content, file_path)
    #     issues += detect_timer_lambda_raw_this(content, file_path)
    #     issues += detect_log_verbose_shipping(content, file_path)
    issues += detect_string_literal_no_text_macro(content, file_path)
    issues += detect_blueprint_pure_side_effects(content, file_path)
    issues += detect_const_ref_uproperty(content, file_path)

    # Security
    issues += detect_getworld_no_check(content, file_path)
    issues += detect_spawnactor_no_check(content, file_path)
    issues += detect_cast_no_check(content, file_path)
    issues += detect_division_no_zero_check(content, file_path)
    issues += detect_array_no_bounds_check(content, file_path)
    issues += detect_getowner_no_check(content, file_path)
    issues += detect_overlap_actor_no_check(content, file_path)
    issues += detect_weak_ptr_no_check(content, file_path)
    #     issues += detect_exec_console_command(content, file_path)
    #     issues += detect_fpath_unsanitized(content, file_path)
    issues += detect_http_insecure(content, file_path)
    issues += detect_hardcoded_secret(content, file_path)

    # Maintainability
    issues += detect_debug_message(content, file_path)
    issues += detect_long_function(content, file_path)
    issues += detect_todo_comments(content, file_path)
    issues += detect_file_too_long(content, file_path)
    issues += detect_too_many_parameters(content, file_path)
    issues += detect_deep_nesting(content, file_path)
    issues += detect_duplicate_include(content, file_path)
    issues += detect_empty_destructor(content, file_path)
    #     issues += detect_commented_code_block(content, file_path)
    #     issues += detect_inconsistent_pointer_style(content, file_path)
    #     issues += detect_multiple_returns(content, file_path)

    return issues
