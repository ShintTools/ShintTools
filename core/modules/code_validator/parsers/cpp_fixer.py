"""
Generic fixer that applies patterns to C++ code.
"""

import re
from typing import List, Optional, Tuple

try:
    from code_validator.parsers.cpp_parser import CppParser
    from code_validator.parsers.fix_patterns import PATTERNS, RULE_TO_PATTERN
except ModuleNotFoundError:
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
        elif pattern_name == "replace_text" and line_number is not None:
            if isinstance(param, tuple):
                old_text, new_text = param
            else:
                old_text, new_text = param, ""
            return self._apply_replace_text(code, line_number, old_text, new_text)
        elif pattern_name == "extract_function":
            return self._apply_extract_function(code, "Tick", "TickLogic")

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

    def _apply_replace_text(  # CB005, CB006, CB008, CB012, CB020, CB030, CS011
        self,
        code: str,
        line_number: int,
        old_text: str,
        new_text: str,
    ) -> Tuple[str, str, List[str]]:
        """Replace text in a specific line."""
        lines = code.split("\n")
        idx = line_number - 1

        if idx < 0 or idx >= len(lines):
            return code, "", ["Invalid line number"]

        original = lines[idx]
        if old_text in original:
            lines[idx] = original.replace(old_text, new_text, 1)
            changes = [f"Line {line_number}: '{old_text}' -> '{new_text}'"]
            return "\n".join(lines), "", changes

        return code, "", ["Text not found"]

    def _apply_extract_function(
        self,
        code: str,
        func_name: str = "Tick",
        new_func_name: str = "TickLogic",
    ) -> Tuple[str, str, List[str]]:
        """Extract function body to a separate function, leaving it minimal."""
        root = self.parser.parse(code)

        # Encontrar el cuerpo de la función
        func_body = self.parser.find_function_body(root, func_name)
        if not func_body:
            return code, "", [f"No {func_name} function found"]

        lines = code.split("\n")

        # Encontrar líneas dentro de la función
        start_line = func_body.start_point[0]
        end_line = func_body.end_point[0]

        # Encontrar la línea de Super::Tick (la mantenemos)
        super_line_idx = None
        for i in range(start_line, end_line + 1):
            if i < len(lines) and "Super::" in lines[i]:
                super_line_idx = i
                break

        if super_line_idx is None:
            # No hay Super::, extraer todo
            extract_start = start_line + 1  # Después del {
            extract_end = end_line - 1  # Antes del }
        else:
            # Extraer después de Super::
            extract_start = super_line_idx + 1
            extract_end = end_line - 1

        if extract_start >= extract_end:
            return code, "", ["Not enough code to extract"]

        # Extraer las líneas
        extracted_lines = lines[extract_start:extract_end]
        if not any(line.strip() for line in extracted_lines):
            return code, "", ["No code to extract"]

        # Obtener indentación
        indent = "    "
        for line in extracted_lines:
            if line.strip():
                indent = " " * (len(line) - len(line.lstrip()))
                break

        # Detectar si usa DeltaTime
        uses_delta = any("DeltaTime" in line for line in extracted_lines)
        call_params = "DeltaTime" if uses_delta else ""
        func_params = "float DeltaTime" if uses_delta else ""

        # Reemplazar con llamada a función nueva
        new_call = f"{indent}{new_func_name}({call_params});"

        # Construir nuevo código
        new_lines = lines[:extract_start]
        new_lines.append(new_call)
        new_lines.extend(lines[extract_end:])

        # Generar función extraída
        extracted_code = "\n".join(extracted_lines)
        additions = f"""
// Add to .h file:
void {new_func_name}({func_params});

// Add to .cpp file:
void AMyClass::{new_func_name}({func_params})
{{
{extracted_code}
}}
"""

        changes = [
            f"Extracted {extract_end - extract_start} lines to {new_func_name}()"
        ]
        return "\n".join(new_lines), additions, changes
