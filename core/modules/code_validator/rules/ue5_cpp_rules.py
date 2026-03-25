import re
from typing import Dict, List

# Type alias for issue dictionary
Issue = Dict


# RULE 1: FindObjectOfType inside Tick
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
    for match in tick_pattern.finditer(content):
        body = match.group(1)
        if re.search(r"FindObjectOfType\s*<", body):
            issues.append(
                {
                    "asset_path": file_path,
                    "severity": "error",
                    "rule_id": "find_object_in_tick",
                    "message": (
                        "FindObjectOfType called inside Tick() "
                        "— cache the reference in BeginPlay instead"
                    ),
                }
            )
    return issues


# RULE 2: GetComponent inside Tick
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
    for match in tick_pattern.finditer(content):
        body = match.group(1)
        if re.search(r"GetComponent(?:ByClass)?\s*[<(]", body):
            issues.append(
                {
                    "asset_path": file_path,
                    "severity": "error",
                    "rule_id": "get_component_in_tick",
                    "message": (
                        "GetComponent called inside Tick() "
                        "— cache the reference in BeginPlay instead"
                    ),
                }
            )
    return issues


# RULE 3: Infinite loop without exit condition
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
                        "Infinite loop without break/return "
                        "— game thread will freeze"
                    ),
                }
            )
    return issues


# RULE 4: Synchronous asset load outside init
def detect_runtime_load(content: str, file_path: str) -> List[Issue]:
    """
    Detects synchronous asset loading calls outside of
    initialization functions like BeginPlay or Constructor.
    These cause frame hitches at runtime. Use async
    loading via FStreamableManager instead.
    """
    issues = []
    load_pattern = re.compile(
        r"\b(?:StaticLoadObject|LoadObject|" r"FSoftObjectPath|RequestSyncLoad)\s*[<(]"
    )
    init_functions = re.compile(
        r"void\s+\w+::" r"(?:BeginPlay|Constructor|PostInitializeComponents)" r"\s*\("
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
                        "BeginPlay/Constructor "
                        "— use async loading instead"
                    ),
                }
            )
    return issues


# Runner: executes all C++ rules
def run_all_cpp_rules(content: str, file_path: str) -> List[Issue]:
    """
    Runs all deterministic C++ rules against the given
    file content and returns a merged list of issues.
    """
    issues = []
    issues += detect_find_object_in_tick(content, file_path)
    issues += detect_get_component_in_tick(content, file_path)
    issues += detect_infinite_loop(content, file_path)
    issues += detect_runtime_load(content, file_path)
    return issues
