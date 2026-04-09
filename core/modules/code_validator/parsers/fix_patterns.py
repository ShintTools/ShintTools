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
# Total: 71 rules
#   - 53 with real auto-fix patterns
#   - 12 with mark_for_review (truly no safe auto-fix)
#   - 6 not in this file (regex-only in ue5_cpp_rules.py)
# ================================================================

RULE_TO_PATTERN = {
    # ==========================================================
    # Performance (CP) — 14 rules, ALL with real auto-fix
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
    "CP014": ("cache_calculation", "FText::Format"),
    "CP015": ("move_to_beginplay", "ensure"),
    "CP016": ("delete_line", "CollectGarbage"),
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
    "CB031": ("add_const_qualifier", None),  # Add const to BlueprintPure
    "CB032": ("remove_const_ref", None),  # Remove const& from UPROPERTY
    # ==========================================================
    # Security (CS) — real auto-fix patterns
    # ==========================================================
    "CS001": ("null_check", "GetWorld()"),
    "CS002": ("null_check", "SpawnActor"),
    "CS003": ("null_check", "Cast<"),
    "CS006": ("null_check", "GetOwner()"),
    "CS007": ("null_check", "OtherActor"),
    "CS008": ("null_check", "WeakPtr"),
    "CS011": ("replace_text", ("http://", "https://")),
    # --- Real auto-fix (formerly mark_for_review) ---
    "CS004": ("add_zero_check", None),  # Division -> ternary zero check
    "CS005": ("add_bounds_check", None),  # Array[] -> IsValidIndex() guard
    "CS012": ("comment_line", None),  # Hardcoded secret -> comment out
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
    "CB017": (
        "mark_for_review",
        "Public member without UPROPERTY - needs specifier choice",
    ),
    "CM004": ("mark_for_review", "File too long - structural refactor needed"),
    "CM005": ("mark_for_review", "Too many parameters - structural refactor needed"),
    "CM006": ("mark_for_review", "Deep nesting - consider extracting functions"),
}
