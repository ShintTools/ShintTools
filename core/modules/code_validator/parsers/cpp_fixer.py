"""
Generic fixer that applies patterns to C++ code.
"""

import re
from typing import List, Optional, Tuple

from cpp_parser import CppParser
from fix_patterns import PATTERNS, RULE_TO_PATTERN


class CppFixer:
    """Applies fixes using pattern definitions."""

    def __init__(self):
        self.parser = CppParser()

    def fix(
        self,
        rule_id: str,
        code: str,
        line_number: Optional[int] = None,
    ) -> Tuple[str, str, List[str]]:
        """Apply fix for a rule."""
        if rule_id not in RULE_TO_PATTERN:
            return code, "", [f"No pattern for {rule_id}"]

        pattern_name, param = RULE_TO_PATTERN[rule_id]

        if pattern_name == "move_to_beginplay":
            return self._apply_move_to_beginplay(code, param)
        elif pattern_name == "null_check" and line_number is not None:
            return self._apply_null_check(code, line_number, param)
        elif pattern_name == "delete_line" and line_number is not None:
            return self._apply_delete_line(code, line_number)
        elif pattern_name == "replace_sleep" and line_number is not None:
            return self._apply_replace_sleep(code, line_number)
        elif pattern_name == "cache_calculation" and line_number is not None:
            return self._apply_cache_calculation(code, line_number)
        elif pattern_name == "move_outside_loop" and line_number is not None:
            return self._apply_move_outside_loop(code, line_number)

        return code, "", ["Pattern not implemented or missing line_number"]

    def _apply_move_to_beginplay(
        self,
        code: str,
        function_name: str,
    ) -> Tuple[str, str, List[str]]:
        """Move call from Tick to BeginPlay."""
        changes = []
        root = self.parser.parse(code)

        tick_body = self.parser.find_function_body(root, "Tick")
        if not tick_body:
            return code, "", ["No Tick function found"]

        calls = self.parser.find_calls_in_node(tick_body, function_name)
        if not calls:
            return code, "", [f"No {function_name} found in Tick"]

        lines = code.split("\n")
        additions = []

        for call in calls:
            var_name = call.variable_assigned
            if not var_name:
                continue

            cached_name = f"Cached{var_name}"
            uses = self.parser.find_variable_uses(tick_body, var_name)
            decl_line = call.line - 1

            # Rename uses
            for line_num in uses:
                idx = line_num - 1
                if idx != decl_line:
                    lines[idx] = lines[idx].replace(var_name, cached_name)
                    changes.append(f"Line {line_num}: {var_name} -> {cached_name}")

            # Comment declaration
            lines[decl_line] = (
                f"    // [SHINTTOOLS] Moved to BeginPlay: {lines[decl_line].strip()}"
            )
            changes.append(f"Line {call.line}: Commented")

            additions.append(f"UPROPERTY() AActor* {cached_name};")
            additions.append(
                f"// In BeginPlay: {cached_name} = {function_name}<...>();"
            )

        return "\n".join(lines), "\n".join(additions), changes

    def _apply_null_check(
        self,
        code: str,
        line_number: int,
        expression: str,
    ) -> Tuple[str, str, List[str]]:
        """Wrap in null-check."""
        config = PATTERNS["null_check"]["expressions"].get(expression, ("auto", "Ptr"))
        var_type, var_name = config

        lines = code.split("\n")
        idx = line_number - 1
        original = lines[idx]
        indent = " " * (len(original) - len(original.lstrip()))

        inner = original.strip().replace(f"{expression}->", f"{var_name}->")

        lines[
            idx
        ] = f"""{indent}if ({var_type} {var_name} = {expression})
{indent}{{
{indent}    {inner}
{indent}}}"""

        return "\n".join(lines), "", [f"Line {line_number}: Added null-check"]

    def _apply_delete_line(
        self,
        code: str,
        line_number: int,
    ) -> Tuple[str, str, List[str]]:
        """Delete a line."""
        lines = code.split("\n")
        deleted = lines.pop(line_number - 1)
        return "\n".join(lines), "", [f"Deleted: {deleted.strip()}"]

    def _apply_replace_sleep(
        self,
        code: str,
        line_number: int,
    ) -> Tuple[str, str, List[str]]:
        """Replace Sleep with Timer."""
        lines = code.split("\n")
        idx = line_number - 1
        original = lines[idx]
        indent = " " * (len(original) - len(original.lstrip()))

        match = re.search(r"Sleep\s*\(\s*([0-9.f]+)\s*\)", original)
        duration = match.group(1) if match else "1.0f"

        timer_code = (
            f"{indent}FTimerHandle TimerHandle;\n"
            f"{indent}GetWorld()->GetTimerManager().SetTimer(\n"
            f"{indent}    TimerHandle,\n"
            f"{indent}    this,\n"
            f"{indent}    &AMyClass::OnTimerComplete,\n"
            f"{indent}    {duration},\n"
            f"{indent}    false\n"
            f"{indent});"
        )
        lines[idx] = timer_code
        additions = "// Add: FTimerHandle TimerHandle; void OnTimerComplete();"
        changes = [f"Line {line_number}: Sleep -> Timer"]
        return "\n".join(lines), additions, changes

    def _apply_cache_calculation(
        self,
        code: str,
        line_number: int,
    ) -> Tuple[str, str, List[str]]:
        """Cache expensive calculation."""
        lines = code.split("\n")
        idx = line_number - 1
        original = lines[idx]
        indent = " " * (len(original) - len(original.lstrip()))

        lines[idx] = (
            f"{indent}// [SHINTTOOLS] Cache this in BeginPlay: {original.strip()}"
        )

        additions = "// Add cached variable in .h and initialize in BeginPlay"
        return "\n".join(lines), additions, [f"Line {line_number}: Marked for caching"]

    def _apply_move_outside_loop(
        self,
        code: str,
        line_number: int,
    ) -> Tuple[str, str, List[str]]:
        """Move allocation outside loop."""
        lines = code.split("\n")
        idx = line_number - 1
        original = lines[idx]
        indent = " " * (len(original) - len(original.lstrip()))

        match = re.search(r"NewObject\s*<\s*(\w+)\s*>", original)
        obj_type = match.group(1) if match else "UObject"

        lines[idx] = (
            f"{indent}// [SHINTTOOLS] Pre-allocate before loop: {original.strip()}"
        )

        additions = (
            f"// Add: TArray<{obj_type}*> PreAllocated; and allocate before loop"
        )
        return "\n".join(lines), additions, [f"Line {line_number}: Move outside loop"]
