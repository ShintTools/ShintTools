"""
Fix patterns definitions.
Each pattern defines: what to find, how to transform, what to add.

Pattern types and their auto-fix behavior:
- Real auto-fix: generates before/after code for client approval
- mark_for_review: only for rules where no safe auto-fix exists
"""

PATTERNS = {
    # Move expensive calls from Tick to BeginPlay
    "move_to_beginplay": {
        "functions": ["FindObjectOfType", "GetComponent", "GetAllActorsOfClass"],
        "from_func": "Tick",
        "to_func": "BeginPlay",
        "cache_prefix": "Cached",
    },
    # Wrap expression in null-check (uses IsValid for UObject types)
    "null_check": {
        "expressions": {
            "GetWorld()": ("UWorld*", "World"),
            "GetOwner()": ("AActor*", "Owner"),
            "SpawnActor": ("AActor*", "SpawnedActor"),
            "Cast<": ("auto", "CastedPtr"),
            "OtherActor": ("AActor*", "OtherActor"),
            "WeakPtr": ("auto", "StrongPtr"),
            "->": ("auto", "Ptr"),
            "GetPlayerController()": ("APlayerController*", "PC"),
            "GetGameInstance()": ("UGameInstance*", "GI"),
            "GetPlayerState()": ("auto", "PS"),
        },
    },
    # Delete the entire line
    "delete_line": {
        "markers": [
            "GEngine->AddOnScreenDebugMessage",
            "UE_LOG",
            "CollectGarbage",
        ],
    },
    # Replace Sleep with Timer
    "replace_sleep": {
        "find": "FPlatformProcess::Sleep",
        "template": (
            "FTimerHandle TimerHandle;\n"
            "GetWorld()->GetTimerManager().SetTimer("
            "TimerHandle, this, &{class_name}::OnTimerComplete, "
            "{duration}, false);"
        ),
    },
    # Mark expensive calculation for caching
    "cache_calculation": {
        "markers": ["FText::Format", "FString::Printf"],
        "from_func": "Tick",
        "cache_prefix": "Cached",
    },
    # Mark allocation to move outside loop
    "move_outside_loop": {
        "markers": ["NewObject<"],
        "template": "TArray<{type}*> PreAllocated;",
    },
}

# ================================================================
# Rule -> Pattern mapping
#
# Categories:
#   - Real auto-fix: client sees before/after diff
#   - mark_for_review: only when NO safe transformation exists
#
# Total: 77 rules
#   - CP014 discarded (requires cross-file refactor — caching FText
#     in a class member). No safe mechanical transformation.
#   - CP015 reintroduced with wrap_shipping_guard (was move_to_beginplay,
#     which made no semantic sense for ensure()).
#   - CB026, CB028, CB029 reintroduced from the old discarded list
#     now that Tree-sitter + safe defaults make them auto-fixable.
#   - CS013, CS014, CS015 added (null-check for GetPlayerController,
#     GetGameInstance, GetPlayerState).
#   - CB033 added (Super::EndPlay missing — analogue of CB024).
#   - CB034 added (raw pointer in UPROPERTY → TObjectPtr<T>).
#   - CB035 added (UPROPERTY EditAnywhere without Category).
#   - CP017 added (empty Tick override).
#   - CB017 promoted from mark_for_review to insert_uproperty.
# ================================================================

RULE_TO_PATTERN = {
    # ==========================================================
    # Performance (CP) — 16 rules with real auto-fix (CP014 discarded)
    # ==========================================================
    "CP001": ("move_to_beginplay", "FindObjectOfType"),
    "CP002": ("move_to_beginplay", "GetComponent"),
    "CP003": ("extract_function", None),
    "CP004": ("delete_line", "UE_LOG"),
    "CP005": ("replace_sleep", None),
    "CP006": ("move_to_beginplay", "GetAllActorsOfClass"),
    "CP007": ("replace_text", ("= true", "= false")),
    "CP008": ("cache_calculation", None),
    "CP009": ("cache_calculation", None),
    "CP010": ("replace_text", ("FORCEINLINE", "inline")),
    "CP011": ("replace_text", ("FString ", "const FString& ")),
    "CP012": ("replace_text", ("TArray<", "const TArray<")),
    "CP013": ("move_outside_loop", "NewObject"),
    # CP014 discarded — requires moving FText::Format result into a
    # cached class member (cross-file refactor). No safe auto-fix.
    # CP015: ensure() in Tick → wrap in #if !UE_BUILD_SHIPPING
    "CP015": ("wrap_shipping_guard", None),
    "CP016": ("delete_line", "CollectGarbage"),
    # CP017: Empty Tick → comment out (actor should disable tick)
    "CP017": ("comment_line", None),
    # ==========================================================
    # Best Practices (CB) — real auto-fix patterns
    # ==========================================================
    # --- Tree-sitter patterns (precise) ---
    "CB005": ("replace_text", ("std::vector", "TArray")),
    "CB006": ("replace_text", ("printf(", "UE_LOG(LogTemp, Log, ")),
    "CB008": ("add_suffix", "f"),
    "CB011": ("delete_line", None),
    "CB012": ("wrap_static_cast", None),
    "CB013": ("null_check", "->"),
    "CB018": ("replace_text", ("std::array", "TArray")),
    "CB019": ("add_virtual", None),
    "CB020": ("replace_text", ("FString Id", "FName Id")),
    "CB022": ("replace_text", ("ensure(", "ensureAlways(")),
    "CB023": ("add_override", None),
    "CB030": ("wrap_text_macro", None),
    # --- Real auto-fix (formerly mark_for_review) ---
    "CB001": ("comment_line", None),  # Infinite loop -> comment out
    "CB002": ("comment_line", None),  # Sync load -> comment out
    "CB003": ("replace_raw_new", None),  # new Type() -> NewObject<Type>(this)
    "CB004": ("comment_line", None),  # delete ptr -> comment out
    "CB007": ("comment_line", None),  # System header -> comment out
    "CB009": ("remove_nullptr_init", None),  # = nullptr -> remove
    "CB016": ("comment_line", None),  # String concat in loop -> comment
    "CB021": ("replace_lambda_capture", None),  # [&]/[=] -> [this]
    "CB024": ("insert_line", "Super::BeginPlay();"),  # Insert Super call
    "CB025": ("add_ufunction_category", None),  # Add Category="Default"
    # CB026: ExposeOnSpawn field → insert type-aware default
    "CB026": ("insert_field_default", None),
    # CB028: SetTimer raw `this` → wrap in CreateWeakLambda
    "CB028": ("wrap_weak_lambda", None),
    # CB029: UE_LOG Verbose → wrap in #if !UE_BUILD_SHIPPING
    "CB029": ("wrap_shipping_guard", None),
    "CB031": ("add_const_qualifier", None),  # Add const to BlueprintPure
    "CB032": ("remove_const_ref", None),  # Remove const& from UPROPERTY
    # CB033: EndPlay without Super call → insert Super::EndPlay()
    "CB033": ("insert_endplay_super", None),
    # CB034: Raw pointer in UPROPERTY → TObjectPtr<T>
    "CB034": ("replace_raw_ptr_tobjectptr", None),
    # CB035: UPROPERTY EditAnywhere without Category → add Category
    "CB035": ("add_uproperty_category", None),
    # ==========================================================
    # Security (CS) — real auto-fix patterns
    # ==========================================================
    # CS001/CS006/CS013/CS014/CS015 were previously auto-fixed via the
    # null_check pattern, but the single-line wrap generates invalid C++
    # in real-world contexts: `return GetWorld()->X;` becomes a function
    # that falls off the end without a return, lines inside lambdas /
    # ternaries / multi-statement initialisers get half-rewrapped, etc.
    # Downgraded to mark_for_review so the developer applies the wrap
    # with the surrounding context in mind. (CS002 SpawnActor, CS003
    # Cast<>, CS007 OtherActor and CS008 WeakPtr keep auto-fix because
    # the patterns are structurally simpler.)
    "CS001": ("mark_for_review", "GetWorld() needs null-check — wrap callsite in `if (UWorld* World = GetWorld()) { ... }`"),
    "CS002": ("null_check", "SpawnActor"),
    "CS003": ("null_check", "Cast<"),
    "CS006": ("mark_for_review", "GetOwner() needs null-check — wrap callsite in `if (AActor* Owner = GetOwner()) { ... }`"),
    "CS007": ("null_check", "OtherActor"),
    "CS008": ("null_check", "WeakPtr"),
    "CS011": ("replace_text", ("http://", "https://")),
    # --- Real auto-fix (formerly mark_for_review) ---
    "CS004": ("add_zero_check", None),  # Division -> ternary zero check
    "CS005": ("add_bounds_check", None),  # Array[] -> IsValidIndex() guard
    "CS012": ("comment_line", None),  # Hardcoded secret -> comment out
    "CS013": ("mark_for_review", "GetPlayerController() needs null-check — wrap callsite in `if (APlayerController* PC = GetPlayerController(0)) { ... }`"),
    "CS014": ("mark_for_review", "GetGameInstance() needs null-check — wrap callsite in `if (UGameInstance* GI = GetGameInstance()) { ... }`"),
    "CS015": ("mark_for_review", "GetPlayerState() needs null-check — wrap callsite in `if (auto* PS = GetPlayerState<APlayerState>()) { ... }`"),
    # ==========================================================
    # Maintainability (CM) — real auto-fix patterns
    # ==========================================================
    "CM001": ("delete_line", "GEngine->AddOnScreenDebugMessage"),
    "CM002": ("extract_function", None),
    "CM003": ("delete_line", None),
    "CM007": ("delete_line", None),
    "CM008": ("replace_destructor_default", None),
    # ==========================================================
    # TRUE mark_for_review — NO safe automatic transformation
    # Only 6 rules: structural refactors or need semantic analysis
    # ==========================================================
    "CB010": ("mark_for_review", "Magic number - extract to named constant"),
    "CB014": ("mark_for_review", "Hardcoded path - use FPaths or config"),
    "CB015": ("mark_for_review", "auto without obvious type - needs Clang AST"),
    "CB017": ("insert_uproperty", None),  # Insert bare UPROPERTY() above member
    "CM004": ("mark_for_review", "File too long - structural refactor needed"),
    "CM005": ("mark_for_review", "Too many parameters - structural refactor needed"),
    "CM006": ("mark_for_review", "Deep nesting - consider extracting functions"),
    # ==========================================================
    # Blueprint (BPB/BPP/BPM) — fix instructions sent to plugin
    # Plugin executes via UE5 editor API; Core only emits JSON.
    # ==========================================================
    # Fully automatic (no user input needed)
    "BPB001": ("bp_rename_asset", None),
    "BPP001": ("bp_set_property", "tick_enabled"),
    "BPM001": ("bp_remove_variable", None),
    "BPM002": ("bp_delete_disconnected", None),
    # Semi-automatic (plugin shows dialog for user input)
    "BPB003": ("bp_rename_variable", None),
    "BPB007": ("bp_set_variable_category", None),
}


# ================================================================
# Blueprint fix instruction builders
#
# Each builder receives the issue dict emitted by blueprint_rules
# and returns a fix_instruction dict that the UE5 plugin can
# execute directly via its editor API.
#
# Schema:
#   action   — str: what the plugin should do
#   target   — str: asset path or variable/node identifier
#   value    — any: new value (name, bool, category, etc.)
#   needs_input — bool: if True, plugin must prompt the user
# ================================================================


def build_bp_fix_instruction(issue: dict) -> dict:
    """Build a fix_instruction dict for a Blueprint issue.

    Returns an empty dict for rules that are not auto-fixable
    or have no defined builder.
    """
    rule_id = issue.get("rule_id", "")
    builder = _BP_FIX_BUILDERS.get(rule_id)
    if builder is None:
        return {}
    return builder(issue)


def _build_bpb001(issue: dict) -> dict:
    """BPB001: add BP_ prefix to asset name."""
    msg = issue.get("message", "")
    # Extract old name from message pattern "'<name>' does not use"
    old_name = ""
    if "'" in msg:
        parts = msg.split("'")
        if len(parts) >= 2:
            old_name = parts[1]
    return {
        "action": "rename_asset",
        "target": issue.get("asset_path", ""),
        "old_name": old_name,
        "value": f"BP_{old_name}" if old_name else "",
        "needs_input": False,
    }


def _build_bpb003(issue: dict) -> dict:
    """BPB003: rename generic variable — needs user input."""
    msg = issue.get("message", "")
    var_name = ""
    if "'" in msg:
        parts = msg.split("'")
        if len(parts) >= 2:
            var_name = parts[1]
    return {
        "action": "rename_variable",
        "target": issue.get("asset_path", ""),
        "variable": var_name,
        "value": "",
        "needs_input": True,
        "prompt": (
            f"Enter a descriptive name for '{var_name}' "
            "(e.g. 'PlayerHealth', 'MoveSpeed')"
        ),
    }


def _build_bpb007(issue: dict) -> dict:
    """BPB007: assign category to public variable — needs input."""
    msg = issue.get("message", "")
    var_name = ""
    if "'" in msg:
        parts = msg.split("'")
        if len(parts) >= 2:
            var_name = parts[1]
    return {
        "action": "set_variable_category",
        "target": issue.get("asset_path", ""),
        "variable": var_name,
        "value": "",
        "needs_input": True,
        "prompt": (
            f"Enter a category for '{var_name}' " "(e.g. 'Combat', 'Movement', 'UI')"
        ),
    }


def _build_bpp001(issue: dict) -> dict:
    """BPP001: disable tick."""
    return {
        "action": "set_property",
        "target": issue.get("asset_path", ""),
        "property": "bCanEverTick",
        "value": False,
        "needs_input": False,
    }


def _build_bpm001(issue: dict) -> dict:
    """BPM001: remove unused variable."""
    msg = issue.get("message", "")
    var_name = ""
    if "'" in msg:
        parts = msg.split("'")
        if len(parts) >= 2:
            var_name = parts[1]
    return {
        "action": "remove_variable",
        "target": issue.get("asset_path", ""),
        "variable": var_name,
        "needs_input": False,
    }


def _build_bpm002(issue: dict) -> dict:
    """BPM002: delete disconnected nodes."""
    return {
        "action": "delete_disconnected_nodes",
        "target": issue.get("asset_path", ""),
        "needs_input": False,
    }


_BP_FIX_BUILDERS = {
    "BPB001": _build_bpb001,
    "BPB003": _build_bpb003,
    "BPB007": _build_bpb007,
    "BPP001": _build_bpp001,
    "BPM001": _build_bpm001,
    "BPM002": _build_bpm002,
}
