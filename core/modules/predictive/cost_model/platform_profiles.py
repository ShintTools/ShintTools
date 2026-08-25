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


class UnknownPlatformProfileError(ValueError):
    """Raised when a requested platform profile name isn't shipped.

    ``name`` reaches here straight from client-controlled input
    (``AnalyzeRequest.platform_profile`` / ``SimulateRequest.platform_profile``)
    — see api/routes/predictive.py. Rejecting explicitly (rather than the old
    silent fall-back to the default profile) closes a path-traversal / file
    read primitive: the previous implementation parsed whatever ``.yaml`` file
    the traversed path resolved to and — if it happened to match the
    PlatformProfile schema — reflected its full contents back to the caller
    in the PredictiveReport response.
    """


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


def _available_profile_names() -> list[str]:
    """Filenames only — never parses YAML — so :func:`load_platform_profile`
    can safely call this on every invocation to validate its ``name``
    argument without recursing into itself (``available_platform_profiles``
    below DOES parse, and is built on top of ``load_platform_profile``)."""
    return sorted(
        p.stem.removeprefix("platform_") for p in _CONFIG_DIR.glob("platform_*.yaml")
    )


@lru_cache(maxsize=16)
def load_platform_profile(name: str = DEFAULT_PROFILE) -> PlatformProfile:
    """Load and cache ``platform_{name}.yaml``.

    *name* MUST be one of :func:`_available_profile_names` — validated
    against that allow-list before it ever touches a filesystem path, so a
    crafted name (e.g. containing ``../``) can never resolve outside this
    directory. Raises :class:`UnknownPlatformProfileError` (a 400 at the API
    layer) instead of silently substituting the default profile.
    """
    if name not in _available_profile_names():
        raise UnknownPlatformProfileError(
            f"Unknown platform profile: {name!r}. "
            f"Valid profiles: {_available_profile_names()}"
        )
    path = _CONFIG_DIR / f"platform_{name}.yaml"
    with path.open(encoding="utf-8") as f:
        return PlatformProfile(**(yaml.safe_load(f) or {}))


def available_platform_profiles() -> list[PlatformProfile]:
    """Every shipped profile, sorted by name — the GET /predict/profiles body."""
    return [load_platform_profile(n) for n in _available_profile_names()]
