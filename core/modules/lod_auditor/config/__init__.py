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


class UnknownProfileError(ValueError):
    """Raised when a requested threshold profile name isn't shipped.

    ``name`` reaches here straight from client-controlled input
    (``LodAuditRequest.profile`` / ``LodReportRequest.profile``) — see
    api/routes/lod_audit.py. Rejecting explicitly (rather than the old
    silent fall-back to the default profile) closes a path-traversal /
    file-existence oracle: a caller could previously probe for arbitrary
    ``*.yaml`` files elsewhere in the container by observing whether the
    response used default thresholds or not.
    """


@lru_cache(maxsize=8)
def load_profile(name: str = _DEFAULT_PROFILE) -> dict[str, Any]:
    """Load and cache the threshold profile identified by *name*.

    File resolution: ``thresholds_{name}.yaml`` in this package. *name*
    MUST be one of :func:`available_profiles` — validated against that
    allow-list before it ever touches a filesystem path, so a crafted
    name (e.g. containing ``../``) can never resolve outside this
    directory. Raises :class:`UnknownProfileError` (a 400 at the API
    layer) instead of silently substituting the default profile.
    """
    if name not in available_profiles():
        raise UnknownProfileError(
            f"Unknown LOD threshold profile: {name!r}. "
            f"Valid profiles: {available_profiles()}"
        )
    path = _CONFIG_DIR / f"thresholds_{name}.yaml"
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def available_profiles() -> list[str]:
    """Return the list of profile names shipped with the auditor.

    Lightweight — only globs filenames, never parses YAML — so
    :func:`load_profile` can safely call this on every invocation to
    validate its ``name`` argument without recursing into itself.
    """
    names: list[str] = []
    for path in _CONFIG_DIR.glob("thresholds_*.yaml"):
        stem = path.stem  # thresholds_default
        names.append(stem.removeprefix("thresholds_"))
    return sorted(names)


def get_threshold(key: str, profile: str = _DEFAULT_PROFILE) -> Any:
    """Look up one threshold by key, transparently using the cache."""
    return load_profile(profile).get(key)
