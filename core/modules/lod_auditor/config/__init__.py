# core/modules/lod_auditor/config/__init__.py
#
# YAML-based threshold loader for the LOD Auditor.
#
# Each profile (default, mobile, console-low, ...) lives in its own YAML
# file next to this module. The loader caches profiles on first use so
# the YAML is only parsed once per process.

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

_CONFIG_DIR = Path(__file__).parent
_DEFAULT_PROFILE = "default"


@lru_cache(maxsize=8)
def load_profile(name: str = _DEFAULT_PROFILE) -> dict[str, Any]:
    """Load and cache the threshold profile identified by *name*.

    File resolution: ``thresholds_{name}.yaml`` in this package.
    Falls back to the default profile if *name* is missing on disk.
    """
    path = _CONFIG_DIR / f"thresholds_{name}.yaml"
    if not path.exists():
        path = _CONFIG_DIR / f"thresholds_{_DEFAULT_PROFILE}.yaml"
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def available_profiles() -> list[str]:
    """Return the list of profile names shipped with the auditor."""
    names: list[str] = []
    for path in _CONFIG_DIR.glob("thresholds_*.yaml"):
        stem = path.stem  # thresholds_default
        names.append(stem.removeprefix("thresholds_"))
    return sorted(names)


def get_threshold(key: str, profile: str = _DEFAULT_PROFILE) -> Any:
    """Look up one threshold by key, transparently using the cache."""
    return load_profile(profile).get(key)
