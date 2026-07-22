# core/modules/predictive/cost_model/platform_profiles.py
#
# Platform budget profiles — the denominators of every risk score.
#
# A prediction of "+1.4 ms" is meaningless on its own; it only becomes a risk
# statement against a budget ("+1.4 ms of a 10 ms CPU budget"). Profiles ship
# as YAML next to this module (platform_*.yaml), one per target platform,
# mirroring the lod_auditor thresholds loader pattern
# (lod_auditor/config/__init__.py).

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel

_CONFIG_DIR = Path(__file__).parent / "config"
DEFAULT_PROFILE = "desktop_60"


class PlatformProfile(BaseModel):
    """Frame/memory/build budgets for one target platform."""

    profile: str
    display_name: str
    target_fps: int
    frame_budget_ms: float
    cpu_budget_ms: float
    gpu_budget_ms: float
    vram_budget_mb: int
    ram_budget_mb: int
    disk_read_mb_s: int
    build_advisory_mb: int
    reference_hw: str
    hw_scale_factor: float = 1.0
    # VR: budget overruns are a comfort problem — layer4 steepens the risk
    # curve when set.
    strict_budget: bool = False
    # Steam Deck & friends: VRAM and RAM come out of one pool — layer4
    # evaluates memory risk against the joint budget when set.
    unified_memory: bool = False

    @property
    def is_calibrated(self) -> bool:
        """True when ground truth was measured on this profile's hardware.

        Predictions against an uncalibrated profile are confidence-capped at
        "medium" by the orchestrator no matter what the rule says.
        """
        return not self.reference_hw.startswith("Uncalibrated")


@lru_cache(maxsize=16)
def load_platform_profile(name: str = DEFAULT_PROFILE) -> PlatformProfile:
    """Load and cache ``platform_{name}.yaml``; falls back to the default."""
    path = _CONFIG_DIR / f"platform_{name}.yaml"
    if not path.exists():
        path = _CONFIG_DIR / f"platform_{DEFAULT_PROFILE}.yaml"
    with path.open(encoding="utf-8") as f:
        return PlatformProfile(**(yaml.safe_load(f) or {}))


def available_platform_profiles() -> list[PlatformProfile]:
    """Every shipped profile, sorted by name — the GET /predict/profiles body."""
    return [
        load_platform_profile(p.stem.removeprefix("platform_"))
        for p in sorted(_CONFIG_DIR.glob("platform_*.yaml"))
    ]
