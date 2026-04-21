# core/modules/code_validator/tiers.py
#
# Subscription tier definitions for ShintTools Code Validator.
#
# FREE  — 40 rules (30 C++ + 10 BP), Asset Naming capped at 500
# INDIE — All rules unlocked, Asset Naming unlimited
#
# How it works:
#   1. The UE5 plugin sends api_key with every request.
#   2. The API resolves the api_key to a tier via MongoDB.
#   3. Issues are filtered: only rules in the client's tier
#      are returned.
#   4. Asset scans are capped by the tier's asset_limit.
#
# To add a new tier, define it in TIERS and list the
# allowed rule IDs.  Rules NOT listed are silently dropped
# from the response — the detection still runs (simplifies
# code), but the client never sees the result.

from typing import Dict, FrozenSet, Optional

# ── Rule sets ────────────────────────────────────────

# C++ Performance — 8 of 16 (basic Tick + obvious)
_FREE_CP = frozenset(
    {
        "CP001",  # FindObject in Tick
        "CP002",  # GetComponent in Tick
        "CP003",  # Large Tick
        "CP004",  # Log in Tick
        "CP005",  # Sleep on game thread
        "CP006",  # GetAllActors in Tick
        "CP007",  # Tick enabled in constructor
        "CP016",  # Garbage collect call
    }
)

# C++ Best Practices — 12 of 34 (fundamentals)
_FREE_CB = frozenset(
    {
        "CB001",  # Infinite loop
        "CB003",  # Raw new
        "CB004",  # Raw delete
        "CB005",  # STL usage
        "CB006",  # Printf
        "CB008",  # Float no suffix
        "CB010",  # Magic numbers
        "CB011",  # Empty if body
        "CB012",  # C-style cast
        "CB014",  # Hardcoded path
        "CB019",  # Non-virtual destructor
        "CB023",  # Missing Super::BeginPlay
    }
)

# C++ Security — 5 of 13 (critical)
_FREE_CS = frozenset(
    {
        "CS001",  # GetWorld no check
        "CS002",  # SpawnActor no check
        "CS003",  # Cast no check
        "CS004",  # Division zero check
        "CS005",  # Array bounds check
    }
)

# C++ Maintainability — 5 of 8 (basics)
_FREE_CM = frozenset(
    {
        "CM001",  # Debug message
        "CM002",  # Long function
        "CM003",  # TODO comments
        "CM004",  # File too long
        "CM005",  # Too many parameters
    }
)

# Blueprint — 10 of 17 (essentials)
_FREE_BP = frozenset(
    {
        "BPB001",  # Missing BP_ prefix
        "BPB002",  # No functions large graph
        "BPB004",  # Missing BeginPlay super
        "BPB005",  # Missing EndPlay super
        "BPP001",  # Tick enabled
        "BPP002",  # Excessive casts
        "BPP003",  # Heavy EventTick
        "BPM001",  # Unused variables
        "BPM002",  # Disconnected nodes
        "BPM003",  # Large Blueprint
    }
)

FREE_RULES: FrozenSet[str] = _FREE_CP | _FREE_CB | _FREE_CS | _FREE_CM | _FREE_BP

# Indie: everything — no filter applied
INDIE_RULES: Optional[FrozenSet[str]] = None  # None = all rules

# ── Asset limits ─────────────────────────────────────

FREE_ASSET_LIMIT: int = 500
INDIE_ASSET_LIMIT: Optional[int] = None  # None = unlimited

# ── Tier registry ───────────────────────────────────

TIERS: Dict[str, dict] = {
    "free": {
        "rules": FREE_RULES,
        "asset_limit": FREE_ASSET_LIMIT,
    },
    "indie": {
        "rules": INDIE_RULES,
        "asset_limit": INDIE_ASSET_LIMIT,
    },
}

DEFAULT_TIER = "free"


# ── Helpers ──────────────────────────────────────────


def get_tier_config(tier_name: str) -> dict:
    """Return the config dict for a tier, falling back to free."""
    return TIERS.get(tier_name, TIERS[DEFAULT_TIER])


def filter_issues_by_tier(
    issues: list,
    tier_name: str,
) -> list:
    """Remove issues whose rule_id is not in the tier's allowed set.

    If the tier allows all rules (rules=None), returns unfiltered.
    """
    config = get_tier_config(tier_name)
    allowed: Optional[FrozenSet[str]] = config["rules"]

    if allowed is None:
        return issues

    return [issue for issue in issues if issue.get("rule_id", "") in allowed]


def get_asset_limit(tier_name: str) -> Optional[int]:
    """Return the asset scan limit for a tier, or None if unlimited."""
    config = get_tier_config(tier_name)
    return config["asset_limit"]
