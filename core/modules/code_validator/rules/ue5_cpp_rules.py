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
# BEST PRACTICES (CB) — continued
#   CB010 — Magic number literal
#   CB011 — Empty if-body (dead branch)
#   CB012 — C-style cast
#   CB013 — Nullptr dereference risk
#   CB014 — Hardcoded absolute path
#   CB015 — Auto without obvious type
#   CB016 — String concatenation in loop
#   CB017 — Public member without UPROPERTY
#   CB018 — Raw C array (use TArray)
#
# PERFORMANCE (CP) — continued
#   CP005 — FPlatformProcess::Sleep on game thread
#
# SECURITY (CS)
#   CS001 — GetWorld() without null-check
#   CS002 — SpawnActor without null-check
#   CS003 — Cast<T> without null-check
#
# MAINTAINABILITY (CM)
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

    issues = []
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
                        "snippet": body_line.strip(),
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

    issues = []
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

    issues = []
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

    issues = []
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

    issues = []
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
                    "snippet": source_line.strip(),
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

    issues = []
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


# ── BEST PRACTICES (CB) — continued ──────────────────


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

    issues = []
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

    issues = []
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

    issues = []
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

    issues = []
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

    issues = []
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

    issues = []
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

    issues = []
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

    issues = []
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

    issues = []
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
                            "snippet": source_line.strip(),
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

    issues = []
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

    Performance (CP):      CP001, CP002, CP003, CP004, CP005
    Best Practices (CB):   CB001-CB018
    Security (CS):         CS001, CS002, CS003
    Maintainability (CM):  CM001, CM002, CM003
    """
    issues: List[Issue] = []

    # Performance
    issues += detect_find_object_in_tick(content, file_path)
    issues += detect_get_component_in_tick(content, file_path)
    issues += detect_large_tick(content, file_path)
    issues += detect_log_error_in_tick(content, file_path)
    issues += detect_sleep_on_game_thread(content, file_path)

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

    # Security
    issues += detect_getworld_no_check(content, file_path)
    issues += detect_spawnactor_no_check(content, file_path)
    issues += detect_cast_no_check(content, file_path)

    # Maintainability
    issues += detect_debug_message(content, file_path)
    issues += detect_long_function(content, file_path)
    issues += detect_todo_comments(content, file_path)

    return issues
