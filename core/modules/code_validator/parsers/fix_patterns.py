"""
Fix patterns definitions.
Each pattern defines: what to find, how to transform, what to add.
"""

PATTERNS = {
    # Patrón: Mover de Tick a BeginPlay
    "move_to_beginplay": {
        "functions": ["FindObjectOfType", "GetComponent", "GetAllActorsOfClass"],
        "from_func": "Tick",
        "to_func": "BeginPlay",
        "cache_prefix": "Cached",
    },
    # Patrón: Envolver en null-check
    "null_check": {
        "expressions": {
            "GetWorld()": ("UWorld*", "World"),
            "GetOwner()": ("AActor*", "Owner"),
            "SpawnActor": ("AActor*", "SpawnedActor"),
            "Cast<": ("auto", "CastedPtr"),
        },
    },
    # Patrón: Borrar línea
    "delete_line": {
        "markers": [
            "GEngine->AddOnScreenDebugMessage",
            "UE_LOG",
            "FORCEINLINE",
            "CollectGarbage",
            "bCanEverTick = true",
        ],
    },
    # Patrón: Reemplazar Sleep con Timer
    "replace_sleep": {
        "find": "FPlatformProcess::Sleep",
        "template": (
            "FTimerHandle TimerHandle;\n"
            "GetWorld()->GetTimerManager().SetTimer("
            "TimerHandle, this, &{class_name}::OnTimerComplete, "
            "{duration}, false);"
        ),
    },
    # Patrón: Cachear cálculo
    "cache_calculation": {
        "markers": ["FText::Format", "FString::Printf"],
        "from_func": "Tick",
        "cache_prefix": "Cached",
    },
    # Patrón: Mover fuera del loop
    "move_outside_loop": {
        "markers": ["NewObject<"],
        "template": "TArray<{type}*> PreAllocated;",
    },
}

# Mapeo de regla a patrón
RULE_TO_PATTERN = {
    # Performance (CP)
    "CP001": ("move_to_beginplay", "FindObjectOfType"),
    "CP002": ("move_to_beginplay", "GetComponent"),
    "CP003": ("extract_function", None),
    "CP004": ("delete_line", "UE_LOG"),
    "CP005": ("replace_sleep", None),
    "CP006": ("move_to_beginplay", "GetAllActorsOfClass"),
    "CP007": ("delete_line", "bCanEverTick"),
    "CP008": ("cache_calculation", None),
    "CP009": ("cache_calculation", None),
    "CP010": ("delete_line", "FORCEINLINE"),
    "CP013": ("move_outside_loop", "NewObject"),
    "CP014": ("cache_calculation", "FText::Format"),
    "CP015": ("move_to_beginplay", "ensure"),
    "CP016": ("delete_line", "CollectGarbage"),
    # # Best Practices (CB)
    "CB005": ("replace_text", "std::vector", "TArray"),
    # Security (CS)
    "CS001": ("null_check", "GetWorld()"),
    "CS002": ("null_check", "SpawnActor"),
    "CS003": ("null_check", "Cast<"),
    "CS006": ("null_check", "GetOwner()"),
    # Maintainability (CM)
    "CM001": ("delete_line", "GEngine->AddOnScreenDebugMessage"),
    "CM007": ("delete_line", None),
    "CB011": ("delete_line", None),
}
