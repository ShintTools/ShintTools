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
        elif pattern_name == "add_suffix" and line_number is not None:
            suffix = param if param else "f"
            return self._apply_add_suffix(code, line_number, suffix)
        elif pattern_name == "add_virtual" and line_number is not None:
            return self._apply_add_virtual(code, line_number)
        elif pattern_name == "add_override" and line_number is not None:
            return self._apply_add_override(code, line_number)
        elif pattern_name == "wrap_text_macro" and line_number is not None:
            return self._apply_wrap_text_macro(code, line_number)
        elif pattern_name == "replace_destructor_default" and line_number is not None:
            return self._apply_replace_destructor_default(code, line_number)
        elif pattern_name == "wrap_static_cast" and line_number is not None:
            return self._apply_wrap_static_cast(code, line_number)
        elif pattern_name == "insert_line" and line_number is not None:
            insert_text = param if param else ""
            return self._apply_insert_line(code, line_number, insert_text)
        elif pattern_name == "add_zero_check" and line_number is not None:
            return self._apply_add_zero_check(code, line_number)
        elif pattern_name == "add_bounds_check" and line_number is not None:
            return self._apply_add_bounds_check(code, line_number)
        elif pattern_name == "comment_line" and line_number is not None:
            return self._apply_comment_line(code, line_number)
        elif pattern_name == "replace_raw_new" and line_number is not None:
            return self._apply_replace_raw_new(code, line_number)
        elif pattern_name == "remove_nullptr_init" and line_number is not None:
            return self._apply_remove_nullptr_init(code, line_number)
        elif pattern_name == "replace_lambda_capture" and line_number is not None:
            return self._apply_replace_lambda_capture(code, line_number)
        elif pattern_name == "add_ufunction_category" and line_number is not None:
            return self._apply_add_ufunction_category(code, line_number)
        elif pattern_name == "add_const_qualifier" and line_number is not None:
            return self._apply_add_const_qualifier(code, line_number)
        elif pattern_name == "remove_const_ref" and line_number is not None:
            return self._apply_remove_const_ref(code, line_number)
        elif pattern_name == "wrap_shipping_guard" and line_number is not None:
            return self._apply_wrap_shipping_guard(code, line_number)
        elif pattern_name == "insert_field_default" and line_number is not None:
            return self._apply_insert_field_default(code, line_number)
        elif pattern_name == "wrap_weak_lambda" and line_number is not None:
            return self._apply_wrap_weak_lambda(code, line_number)
        elif pattern_name == "mark_for_review" and line_number is not None:
            reason = param if param else "Requires manual review"
            return self._apply_mark_for_review(code, line_number, reason)

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
        """Wrap in null-check using UE5 idiomatic IsValid() pattern.

        Two strategies:
        - EXTRACT: expression is a complete callable (GetWorld(), GetOwner()).
          Assigns it to a local var and wraps usage in IsValid().
        - WRAP: expression is a fragment/marker (Cast<, ->, SpawnActor, …).
          The variable already exists; find it from `Var->` on the line and
          wrap the whole line in IsValid(Var) without re-assigning anything.
        """
        lines = code.split("\n")
        idx = line_number - 1
        if idx < 0 or idx >= len(lines):
            return code, "", ["Invalid line number"]

        original = lines[idx]
        indent = " " * (len(original) - len(original.lstrip()))

        # Expressions that are full callables — safe to extract into a local var
        EXTRACT_EXPRESSIONS = {"GetWorld()", "GetOwner()"}

        if expression in EXTRACT_EXPRESSIONS:
            config = PATTERNS["null_check"]["expressions"].get(
                expression, ("auto", "Ptr")
            )
            var_type, var_name = config
            inner = original.strip().replace(f"{expression}->", f"{var_name}->")
            lines[idx] = (
                f"{indent}{var_type} {var_name} = {expression};\n"
                f"{indent}if (IsValid({var_name}))\n"
                f"{indent}{{\n"
                f"{indent}    {inner}\n"
                f"{indent}}}"
            )
            return (
                "\n".join(lines),
                "",
                [f"Line {line_number}: Added null-check for {expression}"],
            )

        # For all other expressions (Cast<, ->, SpawnActor, OtherActor, WeakPtr …):
        # the variable already exists on the line — just find it and wrap.
        match = re.search(r"(\w+)\s*->", original)
        if not match:
            return code, "", [f"No pointer dereference found on line {line_number}"]

        ptr_var = match.group(1)
        inner = original.strip()
        lines[idx] = (
            f"{indent}if (IsValid({ptr_var}))\n"
            f"{indent}{{\n"
            f"{indent}    {inner}\n"
            f"{indent}}}"
        )
        return (
            "\n".join(lines),
            "",
            [f"Line {line_number}: Added IsValid({ptr_var}) guard"],
        )

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

    # ================================================================
    # Priority 2: Easy new patterns
    # ================================================================

    def _apply_add_suffix(
        self,
        code: str,
        line_number: int,
        suffix: str = "f",
    ) -> Tuple[str, str, List[str]]:
        """Add suffix to float literals. E.g. 1.0 -> 1.0f"""
        lines = code.split("\n")
        idx = line_number - 1
        if idx < 0 or idx >= len(lines):
            return code, "", ["Invalid line number"]

        original = lines[idx]
        stripped = original.lstrip()

        # Skip pure comment lines — float literals there are not compiled code.
        if (
            stripped.startswith("//")
            or stripped.startswith("*")
            or stripped.startswith("/*")
        ):
            return code, "", ["Line is a comment — skipping"]

        # Replace floats only in the code portion (before any // comment).
        comment_idx = original.find("//")
        code_part = original if comment_idx == -1 else original[:comment_idx]
        tail = "" if comment_idx == -1 else original[comment_idx:]

        # Avoid scientific notation (1.0e5) and already-suffixed literals.
        new_code_part = re.sub(
            r"(\d+\.\d+)(?![fe\d])",
            rf"\1{suffix}",
            code_part,
        )
        if new_code_part == code_part:
            return code, "", ["No float literal without suffix found"]

        lines[idx] = new_code_part + tail
        return "\n".join(lines), "", [f"Line {line_number}: Added '{suffix}' suffix"]

    def _apply_add_virtual(
        self,
        code: str,
        line_number: int,
    ) -> Tuple[str, str, List[str]]:
        """Add 'virtual' keyword to destructor. ~Class() -> virtual ~Class()"""
        lines = code.split("\n")
        idx = line_number - 1
        if idx < 0 or idx >= len(lines):
            return code, "", ["Invalid line number"]

        original = lines[idx]
        # Match destructor without virtual keyword
        match = re.search(r"^(\s*)~(\w+)", original)
        if not match:
            return code, "", ["No destructor found"]

        # Check if already virtual
        if "virtual" in original:
            return code, "", ["Already virtual"]

        indent = match.group(1)
        lines[idx] = original.replace(f"{indent}~", f"{indent}virtual ~", 1)
        return "\n".join(lines), "", [f"Line {line_number}: Added 'virtual'"]

    def _apply_add_override(
        self,
        code: str,
        line_number: int,
    ) -> Tuple[str, str, List[str]]:
        """Add 'override' specifier to virtual function declaration."""
        lines = code.split("\n")
        idx = line_number - 1
        if idx < 0 or idx >= len(lines):
            return code, "", ["Invalid line number"]

        original = lines[idx]
        if "override" in original:
            return code, "", ["Already has override"]

        # Two explicit branches avoid backreference \1 bugs with optional groups.
        if re.search(r"\)\s*const\s*;", original):
            new_line = re.sub(r"\)\s*const\s*;", ") const override;", original)
        else:
            new_line = re.sub(r"\)\s*;", ") override;", original)

        if new_line == original:
            return code, "", ["Could not add override"]

        lines[idx] = new_line
        return "\n".join(lines), "", [f"Line {line_number}: Added 'override'"]

    def _apply_wrap_text_macro(
        self,
        code: str,
        line_number: int,
    ) -> Tuple[str, str, List[str]]:
        """Wrap string literals with TEXT() macro. "str" -> TEXT("str")"""
        lines = code.split("\n")
        idx = line_number - 1
        if idx < 0 or idx >= len(lines):
            return code, "", ["Invalid line number"]

        original = lines[idx]
        # Match string literals not already wrapped in TEXT()
        new_line = re.sub(
            r'(?<!TEXT\()("(?:[^"\\]|\\.)*")',
            r"TEXT(\1)",
            original,
        )
        if new_line == original:
            return code, "", ["No unwrapped string literal found"]

        lines[idx] = new_line
        return "\n".join(lines), "", [f"Line {line_number}: Wrapped in TEXT()"]

    def _apply_replace_destructor_default(
        self,
        code: str,
        line_number: int,
    ) -> Tuple[str, str, List[str]]:
        """Replace empty destructor body with = default.

        ~Class() {} -> ~Class() = default;
        """
        lines = code.split("\n")
        idx = line_number - 1
        if idx < 0 or idx >= len(lines):
            return code, "", ["Invalid line number"]

        original = lines[idx]
        # Match empty destructor: ~ClassName() {} or ~ClassName() { }
        new_line = re.sub(
            r"(~\w+\s*\(\s*\))\s*\{\s*\}",
            r"\1 = default;",
            original,
        )
        if new_line == original:
            # Try multiline: current line has ~Class() {, next line has }
            if re.search(r"~\w+\s*\(\s*\)\s*\{", original):
                next_idx = idx + 1
                if next_idx < len(lines) and lines[next_idx].strip() == "}":
                    new_line = re.sub(
                        r"(~\w+\s*\(\s*\))\s*\{",
                        r"\1 = default;",
                        original,
                    )
                    lines[idx] = new_line
                    lines.pop(next_idx)
                    return (
                        "\n".join(lines),
                        "",
                        [f"Line {line_number}: Empty destructor -> = default"],
                    )
            return code, "", ["No empty destructor found"]

        lines[idx] = new_line
        return (
            "\n".join(lines),
            "",
            [f"Line {line_number}: Empty destructor -> = default"],
        )

    # ================================================================
    # Priority 3: Medium new patterns
    # ================================================================

    def _apply_wrap_static_cast(
        self,
        code: str,
        line_number: int,
    ) -> Tuple[str, str, List[str]]:
        """Replace C-style cast with static_cast. (int)x -> static_cast<int>(x)"""
        lines = code.split("\n")
        idx = line_number - 1
        if idx < 0 or idx >= len(lines):
            return code, "", ["Invalid line number"]

        original = lines[idx]
        # Match C-style casts: (Type)expression
        # Negative lookbehind: exclude function-call patterns like func(Type)var
        # Only match when '(' is NOT preceded by an identifier character.
        new_line = re.sub(
            r"(?<![a-zA-Z_0-9])\((\w+)\)\s*(\w+)",
            r"static_cast<\1>(\2)",
            original,
        )
        if new_line == original:
            return code, "", ["No C-style cast found"]

        lines[idx] = new_line
        return (
            "\n".join(lines),
            "",
            [f"Line {line_number}: C-style cast -> static_cast"],
        )

    def _apply_insert_line(
        self,
        code: str,
        line_number: int,
        text_to_insert: str,
    ) -> Tuple[str, str, List[str]]:
        """Insert a line after the specified line number."""
        lines = code.split("\n")
        idx = line_number - 1
        if idx < 0 or idx >= len(lines):
            return code, "", ["Invalid line number"]

        # Detect indentation from the target line
        target_line = lines[idx]
        indent = " " * (len(target_line) - len(target_line.lstrip()))

        lines.insert(idx + 1, f"{indent}{text_to_insert}")
        return (
            "\n".join(lines),
            "",
            [f"Line {line_number + 1}: Inserted '{text_to_insert}'"],
        )

    def _apply_add_zero_check(
        self,
        code: str,
        line_number: int,
    ) -> Tuple[str, str, List[str]]:
        """Wrap division with zero-check ternary. a/b -> (b != 0) ? a/b : 0"""
        lines = code.split("\n")
        idx = line_number - 1
        if idx < 0 or idx >= len(lines):
            return code, "", ["Invalid line number"]

        original = lines[idx]
        # Match division: expr / expr (not inside comments)
        match = re.search(r"(\w+)\s*/\s*(\w+)", original)
        if not match:
            return code, "", ["No division found"]

        numerator = match.group(1)
        divisor = match.group(2)
        safe_expr = f"({divisor} != 0) ? ({numerator} / {divisor}) : 0"

        new_line = original[: match.start()] + safe_expr + original[match.end() :]
        lines[idx] = new_line
        return (
            "\n".join(lines),
            "",
            [f"Line {line_number}: Added zero-division check"],
        )

    def _apply_add_bounds_check(
        self,
        code: str,
        line_number: int,
    ) -> Tuple[str, str, List[str]]:
        """Add bounds check before array access.

        Arr[i] -> if (Arr.IsValidIndex(i)) { Arr[i] }
        """
        lines = code.split("\n")
        idx = line_number - 1
        if idx < 0 or idx >= len(lines):
            return code, "", ["Invalid line number"]

        original = lines[idx]
        # Match array access: ArrayName[index]
        match = re.search(r"(\w+)\[(\w+)\]", original)
        if not match:
            return code, "", ["No array access found"]

        array_name = match.group(1)
        index_expr = match.group(2)
        indent = " " * (len(original) - len(original.lstrip()))

        lines[idx] = (
            f"{indent}if ({array_name}.IsValidIndex({index_expr}))\n"
            f"{indent}{{\n"
            f"{indent}    {original.strip()}\n"
            f"{indent}}}"
        )
        return (
            "\n".join(lines),
            "",
            [f"Line {line_number}: Added bounds check for {array_name}[{index_expr}]"],
        )

    # ================================================================
    # Real auto-fix patterns (formerly mark_for_review)
    # ================================================================

    def _apply_comment_line(
        self,
        code: str,
        line_number: int,
    ) -> Tuple[str, str, List[str]]:
        """Comment out a line instead of deleting it. Safer than delete."""
        lines = code.split("\n")
        idx = line_number - 1
        if idx < 0 or idx >= len(lines):
            return code, "", ["Invalid line number"]

        original = lines[idx]
        indent = " " * (len(original) - len(original.lstrip()))
        lines[idx] = f"{indent}// [SHINTTOOLS] {original.strip()}"
        return "\n".join(lines), "", [f"Line {line_number}: Commented out"]

    def _apply_replace_raw_new(
        self,
        code: str,
        line_number: int,
    ) -> Tuple[str, str, List[str]]:
        """Replace raw new with NewObject<Type>(this).
        new Type(...) -> NewObject<Type>(this)
        new Type[n]  -> commented (array new needs manual review)
        """
        lines = code.split("\n")
        idx = line_number - 1
        if idx < 0 or idx >= len(lines):
            return code, "", ["Invalid line number"]

        original = lines[idx]

        # Match: new TypeName(args) or new TypeName
        new_match = re.search(
            r"\bnew\s+(\w+)\s*(?:\(([^)]*)\))?",
            original,
        )
        if not new_match:
            return code, "", ["No 'new' expression found"]

        type_name = new_match.group(1)

        # Array new -> can't auto-fix safely
        if re.search(r"\bnew\s+\w+\s*\[", original):
            indent = " " * (len(original) - len(original.lstrip()))
            lines[idx] = (
                f"{indent}// [SHINTTOOLS] Array new - use TArray: {original.strip()}"
            )
            return "\n".join(lines), "", [f"Line {line_number}: Array new marked"]

        # Object new -> NewObject<Type>(this)
        new_line = re.sub(
            r"\bnew\s+\w+\s*(?:\([^)]*\))?",
            f"NewObject<{type_name}>(this)",
            original,
        )
        lines[idx] = new_line
        return (
            "\n".join(lines),
            "",
            [f"Line {line_number}: new {type_name}() -> NewObject<{type_name}>(this)"],
        )

    def _apply_remove_nullptr_init(
        self,
        code: str,
        line_number: int,
    ) -> Tuple[str, str, List[str]]:
        """Remove = nullptr from UPROPERTY declaration.
        UPROPERTY() Type* Var = nullptr; -> UPROPERTY() Type* Var;
        """
        lines = code.split("\n")
        idx = line_number - 1
        if idx < 0 or idx >= len(lines):
            return code, "", ["Invalid line number"]

        original = lines[idx]
        new_line = re.sub(r"\s*=\s*nullptr", "", original)
        if new_line == original:
            return code, "", ["No = nullptr found"]

        lines[idx] = new_line
        return "\n".join(lines), "", [f"Line {line_number}: Removed = nullptr"]

    def _apply_replace_lambda_capture(
        self,
        code: str,
        line_number: int,
    ) -> Tuple[str, str, List[str]]:
        """Replace implicit lambda capture with explicit.
        [&] or [=] -> [this]
        """
        lines = code.split("\n")
        idx = line_number - 1
        if idx < 0 or idx >= len(lines):
            return code, "", ["Invalid line number"]

        original = lines[idx]
        new_line = re.sub(r"\[\s*[&=]\s*\]", "[this]", original)
        if new_line == original:
            return code, "", ["No implicit capture found"]

        lines[idx] = new_line
        return "\n".join(lines), "", [f"Line {line_number}: Explicit capture [this]"]

    def _apply_add_ufunction_category(
        self,
        code: str,
        line_number: int,
    ) -> Tuple[str, str, List[str]]:
        """Add Category to UFUNCTION(BlueprintCallable).
        BlueprintCallable) -> BlueprintCallable, Category="Default")
        """
        lines = code.split("\n")
        idx = line_number - 1
        if idx < 0 or idx >= len(lines):
            return code, "", ["Invalid line number"]

        original = lines[idx]
        if "Category" in original:
            return code, "", ["Already has Category"]

        new_line = re.sub(
            r"BlueprintCallable",
            'BlueprintCallable, Category="Default"',
            original,
        )
        if new_line == original:
            return code, "", ["No BlueprintCallable found"]

        lines[idx] = new_line
        return "\n".join(lines), "", [f"Line {line_number}: Added Category"]

    def _apply_add_const_qualifier(
        self,
        code: str,
        line_number: int,
    ) -> Tuple[str, str, List[str]]:
        """Add const to BlueprintPure function.

        void Func(); -> void Func() const;

        Refuses to touch static member functions: C++ forbids 'const'
        on static member functions (they have no 'this' pointer), so
        adding it would produce code that fails to compile. Looks at
        the target line AND the immediate previous non-comment line
        to handle the 'static\\n<return type> Foo();' split style.
        """
        lines = code.split("\n")
        idx = line_number - 1
        if idx < 0 or idx >= len(lines):
            return code, "", ["Invalid line number"]

        original = lines[idx]
        if "const" in original:
            return code, "", ["Already const"]

        # Safety net: refuse static member functions even if a stale
        # issue reaches the fixer past the detector-side skip.
        if re.search(r"\bstatic\b", original):
            return code, "", ["Cannot add const to static function"]
        prev_idx = idx - 1
        while prev_idx >= 0:
            prev_line = lines[prev_idx].strip()
            if not prev_line or prev_line.startswith("//"):
                prev_idx -= 1
                continue
            if not prev_line.startswith("UFUNCTION") and re.search(
                r"\bstatic\b", prev_line
            ):
                return (
                    code,
                    "",
                    ["Cannot add const to static function"],
                )
            break

        new_line = re.sub(r"\)\s*;", ") const;", original)
        if new_line == original:
            return code, "", ["Could not add const"]

        lines[idx] = new_line
        return "\n".join(lines), "", [f"Line {line_number}: Added const"]

    def _apply_remove_const_ref(
        self,
        code: str,
        line_number: int,
    ) -> Tuple[str, str, List[str]]:
        """Remove const reference from UPROPERTY declaration.
        const Type& Var -> Type Var (refs can't be serialized)
        """
        lines = code.split("\n")
        idx = line_number - 1
        if idx < 0 or idx >= len(lines):
            return code, "", ["Invalid line number"]

        original = lines[idx]
        new_line = re.sub(r"\bconst\s+(\w+)\s*&", r"\1", original)
        if new_line == original:
            return code, "", ["No const ref found"]

        lines[idx] = new_line
        return "\n".join(lines), "", [f"Line {line_number}: Removed const ref"]

    # ================================================================
    # Priority 4: Mark for review (no auto-fix)
    # ================================================================

    def _apply_mark_for_review(
        self,
        code: str,
        line_number: int,
        reason: str,
    ) -> Tuple[str, str, List[str]]:
        """Mark a line for manual review. Adds a comment above the line."""
        lines = code.split("\n")
        idx = line_number - 1
        if idx < 0 or idx >= len(lines):
            return code, "", ["Invalid line number"]

        target_line = lines[idx]
        indent = " " * (len(target_line) - len(target_line.lstrip()))

        lines.insert(idx, f"{indent}// [SHINTTOOLS REVIEW] {reason}")
        return (
            "\n".join(lines),
            "",
            [f"Line {line_number}: Marked for review - {reason}"],
        )

    # ================================================================
    # Original patterns
    # ================================================================

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

        return (
            "\n".join(new_lines),
            additions,
            [f"Extracted {len(extracted_lines)} lines to {new_func_name}()"],
        )

    # ================================================================
    # Reintroduced rules: CP015, CB026, CB028, CB029
    # ================================================================

    def _apply_wrap_shipping_guard(
        self,
        code: str,
        line_number: int,
    ) -> Tuple[str, str, List[str]]:
        """
        CP015, CB029 — Wrap the statement on the target line in
        `#if !UE_BUILD_SHIPPING ... #endif`.

        Preserves the original indentation and is idempotent: if the
        previous non-empty line already opens a `#if !UE_BUILD_SHIPPING`
        guard, the fix is a no-op. Supports multi-line statements by
        scanning forward until a `;` at paren depth 0 is reached.
        """
        lines = code.split("\n")
        idx = line_number - 1
        if idx < 0 or idx >= len(lines):
            return code, "", ["Invalid line number"]

        # Idempotency: walk back over blank lines to the previous
        # non-empty line; if it opens a shipping guard, we're done.
        back = idx - 1
        while back >= 0 and not lines[back].strip():
            back -= 1
        if back >= 0 and "#if !UE_BUILD_SHIPPING" in lines[back]:
            return code, "", ["Already wrapped in shipping guard"]

        # Find the end of the statement (balanced parens + trailing ;).
        end_idx = idx
        depth = 0
        for j in range(idx, len(lines)):
            for ch in lines[j]:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
            if depth <= 0 and lines[j].rstrip().endswith(";"):
                end_idx = j
                break

        # Epic convention: preprocessor directives are flush-left
        # inside function bodies, not indented to match the statement.
        guard_open = "#if !UE_BUILD_SHIPPING"
        guard_close = "#endif"

        new_lines = (
            lines[:idx]
            + [guard_open]
            + lines[idx : end_idx + 1]
            + [guard_close]
            + lines[end_idx + 1 :]
        )
        return (
            "\n".join(new_lines),
            "",
            [f"Line {line_number}: Wrapped in #if !UE_BUILD_SHIPPING"],
        )

    def _apply_insert_field_default(
        self,
        code: str,
        line_number: int,
    ) -> Tuple[str, str, List[str]]:
        """
        CB026 — Insert a type-aware default initializer before the `;`
        of a UPROPERTY(ExposeOnSpawn) field declaration.

        Adding a default is idempotent with any constructor assignment:
        if the constructor sets the value, that wins (default init runs
        first). If not, the default avoids uninitialized memory.
        """
        lines = code.split("\n")
        idx = line_number - 1
        if idx < 0 or idx >= len(lines):
            return code, "", ["Invalid line number"]

        original = lines[idx]
        if ";" not in original:
            return code, "", ["No semicolon on target line"]

        before_semi = original.split(";", 1)[0]
        if "=" in before_semi:
            return code, "", ["Field already has a default value"]

        m = re.match(
            r"^(\s*)([A-Za-z_][A-Za-z0-9_:<>,\s\*&]*?)\s+"
            r"([A-Za-z_]\w*)\s*(\[[^\]]*\])?\s*;",
            original,
        )
        if not m:
            return code, "", ["Could not parse field declaration"]

        type_token = m.group(2).strip()
        t = re.sub(r"\b(const|volatile|mutable)\b", "", type_token).strip()
        t = re.sub(r"\s+", " ", t)

        default_value: Optional[str] = None

        if t.endswith("*"):
            default_value = "nullptr"
        elif t.startswith(
            (
                "TObjectPtr<",
                "TWeakObjectPtr<",
                "TSoftObjectPtr<",
                "TSoftClassPtr<",
                "TSubclassOf<",
            )
        ):
            default_value = "nullptr"
        elif t in {
            "int8",
            "int16",
            "int32",
            "int64",
            "uint8",
            "uint16",
            "uint32",
            "uint64",
            "float",
            "double",
            "int",
            "short",
            "long",
            "size_t",
            "SIZE_T",
        }:
            default_value = "0"
        elif t == "bool":
            default_value = "false"
        else:
            ue_defaults = {
                "FVector": "FVector::ZeroVector",
                "FVector2D": "FVector2D::ZeroVector",
                "FVector4": "FVector4(ForceInitToZero)",
                "FRotator": "FRotator::ZeroRotator",
                "FQuat": "FQuat::Identity",
                "FTransform": "FTransform::Identity",
                "FLinearColor": "FLinearColor::White",
                "FColor": "FColor::White",
            }
            default_value = ue_defaults.get(t)

        if default_value is None:
            return (
                code,
                "",
                [f"No safe default for type '{type_token}'"],
            )

        new_line = original.replace(";", f" = {default_value};", 1)
        lines[idx] = new_line
        return (
            "\n".join(lines),
            "",
            [
                f"Line {line_number}: Added default "
                f"'= {default_value}' for {type_token}"
            ],
        )

    def _apply_wrap_weak_lambda(
        self,
        code: str,
        line_number: int,
    ) -> Tuple[str, str, List[str]]:
        """
        CB028 — Wrap a SetTimer lambda that captures `this` in
        FTimerDelegate::CreateWeakLambda(this, <lambda>).

        Works on a 4-line window to support multi-line SetTimer calls.
        Refuses to touch the code if the window already uses
        CreateWeakLambda / CreateUObject, if the SetTimer call isn't
        found, or if the lambda boundaries cannot be located safely.
        """
        lines = code.split("\n")
        idx = line_number - 1
        if idx < 0 or idx >= len(lines):
            return code, "", ["Invalid line number"]

        end_window = min(idx + 4, len(lines))
        joined = "\n".join(lines[idx:end_window])

        if "CreateWeakLambda" in joined or "CreateUObject" in joined:
            return code, "", ["Already uses safe timer binding"]

        if "SetTimer" not in joined:
            return code, "", ["SetTimer call not found in line window"]

        lam_match = re.search(r"(\[\s*(?:this|&|=)[^\]]*\])\s*\(", joined)
        if not lam_match:
            return code, "", ["Lambda capture not found"]

        cap_start = lam_match.start()

        # Scan forward to find the end of the lambda body (matching `}`).
        brace_depth = 0
        lam_end = -1
        i = cap_start
        seen_brace = False
        while i < len(joined):
            ch = joined[i]
            if ch == "{":
                brace_depth += 1
                seen_brace = True
            elif ch == "}":
                brace_depth -= 1
                if seen_brace and brace_depth == 0:
                    lam_end = i + 1
                    break
            i += 1

        if lam_end <= cap_start:
            return code, "", ["Could not locate lambda end"]

        new_joined = (
            joined[:cap_start]
            + "FTimerDelegate::CreateWeakLambda(this, "
            + joined[cap_start:lam_end]
            + ")"
            + joined[lam_end:]
        )

        new_window_lines = new_joined.split("\n")
        result_lines = lines[:idx] + new_window_lines + lines[end_window:]
        return (
            "\n".join(result_lines),
            "",
            [
                f"Line {line_number}: Wrapped lambda in "
                "FTimerDelegate::CreateWeakLambda"
            ],
        )
