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
from typing import List, Optional, Tuple

from code_validator.unreal.cpp._cpp_helpers import (
    Issue,
    _char_pos_for_line,
    _extract_class_name,
    _get_line_number,
    _is_commandlet_context,
    _is_cpp,
    _is_fixable,
    _is_header,
    _is_source,
)

# Tree-sitter-based body extraction.
#
# The legacy regex `\{([^}]*(?:\{[^}]*\}[^}]*)*)\}` only handles ONE level
# of inner braces, so calls nested inside if/for/switch/while blocks were
# missed. CppParser walks the real C++ AST and captures the full body at
# any nesting depth.
#
# Import is best-effort: if tree-sitter or its grammar is unavailable the
# affected rules transparently fall back to the old regex (see
# `_iter_function_bodies` / `_iter_loop_bodies`).
try:
    from code_validator.unreal.parsers.cpp_parser import CppParser

    _TREE_SITTER_AVAILABLE = True
except Exception:  # pragma: no cover - import-time env guard
    CppParser = None  # type: ignore[assignment,misc]
    _TREE_SITTER_AVAILABLE = False


def _byte_to_char_pos(content: str, byte_offset: int) -> int:
    """Convert a UTF-8 byte offset into a character index in ``content``.

    Tree-sitter reports positions as byte offsets; the rest of this module
    works with character offsets (``_get_line_number`` etc.). For pure-ASCII
    UE5 source the two are identical, but this stays correct for any
    non-ASCII content (comments, string literals).
    """
    return len(content.encode("utf-8")[:byte_offset].decode("utf-8", "ignore"))


def _node_text(node, content: str) -> str:
    """Return the source text of a tree-sitter node."""
    if getattr(node, "text", None) is not None:
        return node.text.decode("utf-8", "ignore")
    return content[
        _byte_to_char_pos(content, node.start_byte) : _byte_to_char_pos(
            content, node.end_byte
        )
    ]


def _walk(node):
    """Yield ``node`` and all of its descendants."""
    yield node
    for child in node.children:
        yield from _walk(child)


def _declarator_qualified_name(func_def) -> str:
    """Extract ``Class::Method`` (or ``Method``) from a function_definition."""
    for child in func_def.children:
        if child.type == "function_declarator":
            for sub in _walk(child):
                if sub.type == "qualified_identifier":
                    return sub.text.decode("utf-8", "ignore")
                if sub.type == "identifier":
                    return sub.text.decode("utf-8", "ignore")
    return ""


_RAW_PARSER = None
_RAW_PARSER_TRIED = False


def _raw_parser():
    """Build a tree-sitter parser directly, robust across API versions.

    ``CppParser`` only catches ``TypeError`` to detect the tree-sitter
    0.21.x API. On 0.21.0 ``Parser(language)`` does *not* raise — it
    silently builds a parser whose ``parse()`` then raises ``ValueError``.
    To keep tree-sitter actually working (instead of always falling back
    to the weak regex) we build the parser here using the 0.21.x-correct
    ``Parser() + set_language()`` path, without touching cpp_parser.py.

    Cached after the first attempt. Returns None if unavailable.
    """
    global _RAW_PARSER, _RAW_PARSER_TRIED
    if _RAW_PARSER_TRIED:
        return _RAW_PARSER
    _RAW_PARSER_TRIED = True
    try:
        import tree_sitter_cpp as tscpp
        from tree_sitter import Language, Parser

        try:
            lang = Language(tscpp.language())  # tree-sitter >= 0.22
        except TypeError:
            lang = Language(tscpp.language(), "cpp")  # 0.21.x

        try:
            parser = Parser()
            parser.set_language(lang)  # 0.21.x path
        except (TypeError, AttributeError):
            parser = Parser(lang)  # >= 0.22 path
        _RAW_PARSER = parser
    except Exception:
        _RAW_PARSER = None
    return _RAW_PARSER


def _try_parse(content: str):
    """Parse ``content`` and return the root node, or None on failure.

    Tries ``CppParser`` first (per the migration spec); if that fails for
    any reason (tree-sitter missing, version mismatch, parse error) it
    retries with a directly-built parser, and finally returns None so the
    caller transparently falls back to the legacy regex.
    """
    if not _TREE_SITTER_AVAILABLE or CppParser is None:
        return _try_parse_raw(content)
    try:
        parser = CppParser()
        return parser.parse(content)
    except Exception:
        return _try_parse_raw(content)


def _try_parse_raw(content: str):
    """Parse with the directly-built parser. Returns root node or None."""
    parser = _raw_parser()
    if parser is None:
        return None
    try:
        code_bytes = content.encode("utf-8") if isinstance(content, str) else content
        return parser.parse(code_bytes).root_node
    except Exception:
        return None


def _iter_function_bodies(
    content: str,
    name_regex: str,
) -> Optional[List[Tuple[str, str, int]]]:
    """Yield ``(class_name, body_text, body_char_start)`` for each matching func.

    ``name_regex`` is matched against the bare method name (e.g. ``Tick`` or
    ``Tick|Update``). ``body_text`` is the code *between* the outer braces
    (matching the legacy regex group), and ``body_char_start`` is the
    character index in ``content`` of the first character inside ``{``.

    Returns None when tree-sitter is unavailable so the caller can fall
    back to the legacy regex.
    """
    root = _try_parse(content)
    if root is None:
        return None

    name_pat = re.compile(r"^(?:%s)$" % name_regex)
    results: List[Tuple[str, str, int]] = []
    for node in _walk(root):
        if node.type != "function_definition":
            continue
        qualified = _declarator_qualified_name(node)
        if "::" in qualified:
            class_name, _, method = qualified.rpartition("::")
        else:
            class_name, method = "Unknown", qualified
        if not name_pat.match(method):
            continue
        body = None
        for child in node.children:
            if child.type == "compound_statement":
                body = child
                break
        if body is None:
            continue
        # Strip the enclosing braces to mirror the legacy regex group(2).
        outer = _node_text(body, content)
        inner = outer[1:-1] if outer.startswith("{") and outer.endswith("}") else outer
        body_char_start = _byte_to_char_pos(content, body.start_byte) + 1
        results.append((class_name, inner, body_char_start))
    return results


def _iter_loop_bodies(
    content: str,
) -> Optional[List[Tuple[str, int]]]:
    """Yield ``(body_text, body_char_start)`` for each for/while loop body.

    Mirrors the legacy loop regex group(1) (code between the loop's braces)
    but at any nesting depth. Returns None if tree-sitter is unavailable.
    """
    root = _try_parse(content)
    if root is None:
        return None

    results: List[Tuple[str, int]] = []
    for node in _walk(root):
        if node.type not in ("for_statement", "while_statement"):
            continue
        body = None
        for child in node.children:
            if child.type == "compound_statement":
                body = child
                break
        if body is None:
            continue
        outer = _node_text(body, content)
        inner = outer[1:-1] if outer.startswith("{") and outer.endswith("}") else outer
        body_char_start = _byte_to_char_pos(content, body.start_byte) + 1
        results.append((inner, body_char_start))
    return results


# Legacy regexes — used only when tree-sitter is unavailable.
_LEGACY_TICK_RE = re.compile(
    r"void\s+(\w+)::(?:Tick|Update)\s*\([^)]*\)\s*" r"\{([^}]*(?:\{[^}]*\}[^}]*)*)\}",
    re.DOTALL,
)
_LEGACY_TICK_ONLY_RE = re.compile(
    r"void\s+(\w+)::Tick\s*\([^)]*\)\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}",
    re.DOTALL,
)
_LEGACY_LOOP_RE = re.compile(
    r"(?:for|while)\s*\([^)]*\)\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}",
    re.DOTALL,
)


def _tick_bodies(
    content: str,
    tick_only: bool = False,
) -> List[Tuple[str, str, int]]:
    """Return ``(class_name, body_text, body_char_start)`` for Tick/Update.

    Prefers the tree-sitter AST (full body at any nesting depth); falls
    back to the legacy 1-level regex when tree-sitter is unavailable.

    When ``tick_only`` is True only ``Tick`` is matched (not ``Update``),
    matching the few rules that historically targeted Tick exclusively.
    """
    name_regex = "Tick" if tick_only else "Tick|Update"
    ts_result = _iter_function_bodies(content, name_regex)
    if ts_result is not None:
        return ts_result

    legacy_re = _LEGACY_TICK_ONLY_RE if tick_only else _LEGACY_TICK_RE
    fallback: List[Tuple[str, str, int]] = []
    for m in legacy_re.finditer(content):
        fallback.append((m.group(1), m.group(2), m.start(2)))
    return fallback


def _loop_bodies(content: str) -> List[Tuple[str, int]]:
    """Return ``(body_text, body_char_start)`` for every for/while loop.

    Prefers the tree-sitter AST; falls back to the legacy regex.
    """
    ts_result = _iter_loop_bodies(content)
    if ts_result is not None:
        return ts_result

    fallback: List[Tuple[str, int]] = []
    for m in _LEGACY_LOOP_RE.finditer(content):
        fallback.append((m.group(1), m.start(1)))
    return fallback


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
    for class_name, tick_body, body_start in _tick_bodies(content):
        find_match = re.search(r"FindObjectOfType\s*<", tick_body)
        if find_match:
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
    for class_name, tick_body, body_start in _tick_bodies(content):
        comp_match = re.search(r"GetComponent(?:ByClass)?\s*[<(]", tick_body)
        if comp_match:
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

    # Commandlets / editor batch tools don't run on the live game thread —
    # a blocking Sleep in a headless cooker pass is idiomatic (Epic's own
    # content-validation commandlet does it). Don't flag it there.
    if _is_commandlet_context(file_path, content):
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
    for class_name, tick_body, body_start in _tick_bodies(content):
        actor_match = re.search(
            r"\bGetAllActors(?:OfClass|WithInterface)\s*[<(]",
            tick_body,
        )
        if actor_match:
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
def _has_meaningful_tick(content: str) -> bool:
    """True if the file defines a Tick override that does real work (more
    than a bare ``Super::Tick(...)`` call).

    Enabling tick in the constructor is the CANONICAL, Epic-recommended way
    to turn on per-frame updates — flagging it unconditionally is a false
    positive on every actor that genuinely ticks. We only warn when tick is
    enabled but NOT actually used (no Tick override, or an empty/Super-only
    one), which is the real waste this rule targets.
    """
    sig = re.search(r"\b\w+::Tick\s*\([^)]*\)", content)
    if not sig:
        return False
    brace_start = content.find("{", sig.end())
    if brace_start == -1:
        return False
    depth = 0
    i = brace_start
    while i < len(content):
        ch = content[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    body = content[brace_start + 1 : i]
    # Strip comments and the Super::Tick call; anything left = real logic.
    body = re.sub(r"//[^\n]*", "", body)
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    body = re.sub(r"\bSuper::Tick\s*\([^)]*\)\s*;", "", body)
    return bool(body.strip())


def detect_tick_enabled_in_constructor(
    content: str,
    file_path: str,
) -> List[Issue]:
    """
    Detects PrimaryActorTick.bCanEverTick = true enabled in
    the constructor of an actor that does NOT actually use
    Tick (no Tick override, or an empty/Super-only one).

    Enabling tick in the constructor is the correct UE5 pattern
    when the actor genuinely needs per-frame updates, so we stay
    silent in that case and only flag the wasteful one: tick on,
    but no real Tick body. Use timers or events for infrequent
    logic instead of an always-on empty tick.
    """
    if not _is_source(file_path):
        return []

    # Actor genuinely ticks → enabling it in the ctor is correct. Skip.
    if _has_meaningful_tick(content):
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
    # Heavy math functions to detect
    heavy_math_pattern = re.compile(
        r"\bFMath::" r"(?:Sqrt|Sin|Cos|Tan|Atan2|Pow|Exp|Log)\s*\("
    )

    for class_name, tick_body, body_start in _tick_bodies(content):
        math_match = heavy_math_pattern.search(tick_body)
        if math_match:
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
    string_op_pattern = re.compile(
        r"\bFString\s*\+=" r"|\bFString::Printf\s*\(" r"|\bFString::Format\s*\("
    )

    for class_name, tick_body, body_start in _tick_bodies(content):
        str_match = string_op_pattern.search(tick_body)
        if str_match:
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

    # Inside loop: TArray<Type> VarName = (copy assignment)
    copy_pattern = re.compile(r"\bTArray\s*<[^>]+>\s+(\w+)\s*=\s*(?!MoveTemp)")

    for loop_body, loop_body_start in _loop_bodies(content):
        copy_match = copy_pattern.search(loop_body)

        if copy_match:
            var_name = copy_match.group(1)
            line_no = _get_line_number(
                content,
                loop_body_start + copy_match.start(),
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

    for loop_body, loop_body_start in _loop_bodies(content):
        newobj_match = re.search(r"\bNewObject\s*<", loop_body)

        if newobj_match:
            line_no = _get_line_number(
                content,
                loop_body_start + newobj_match.start(),
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

    # Tree-sitter extracts the full Tick/Update body at any nesting depth;
    # falls back to the legacy 1-level regex when tree-sitter is unavailable.
    for class_name, tick_body, body_start in _tick_bodies(content):
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
            # Commandlets / editor batch tools legitimately force GC between
            # processing thousands of assets — not a runtime frame hitch.
            if _is_commandlet_context(file_path, content):
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
    Super::Tick(DeltaTime). An empty Tick still costs ~0.1 ms per
    actor per frame from virtual dispatch and tick registration.
    Remove the override and set bCanEverTick = false in the
    constructor when per-frame updates aren't needed.
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
    spawn_pattern = re.compile(r"\bSpawnActor(?:Deferred)?\s*<")

    for class_name, tick_body, body_start in _tick_bodies(content):
        # Skip if body contains comment-only spawn mentions
        spawn_match = spawn_pattern.search(tick_body)
        if not spawn_match:
            continue

        # Verify the spawn is not inside a comment
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
