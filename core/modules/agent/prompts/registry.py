# core/modules/agent/prompts/registry.py
#
# Server-side prompt registry — loads system prompt + few-shots from
# versioned YAML files instead of hard-coding them in Python.
#
# Layout under prompts/templates/:
#     _shared/v1.yaml                       — cross-module fallback
#     {module}/{engine}/v{N}.yaml           — module+engine override
#
# Resolution order in load_template(module, engine, version):
#     1. {module}/{engine}/v{version}.yaml
#     2. _shared/v{version}.yaml
#     3. raise FileNotFoundError
#
# When version="latest" we pick the highest vN.yaml present in the
# chosen directory.
#
# Hot-reload is intentionally restart-only: the API caches templates
# in memory at first access and the acceptance criterion is
# "edit YAML + restart → output changes" (no file-watcher needed).
#
# The registry directory can be overridden with the
# SHINTTOOLS_PROMPT_REGISTRY_DIR env var, which keeps tests isolated
# from the bundled templates.

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml  # type: ignore[import-untyped]

_DEFAULT_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
_VERSION_FILE_PATTERN = re.compile(r"^v(\d+)\.yaml$")


@dataclass(frozen=True)
class PromptTemplate:
    """Parsed (module, engine, version) prompt configuration.

    Frozen so callers can safely cache references without worrying
    about mutation.
    """

    module: str
    engine: str
    version: int
    model: str
    system: str
    few_shots: str
    stop_tokens: tuple[str, ...]
    max_tokens: int
    temperature: float
    source_path: Path


# Cache key is (module, engine, version_arg) where version_arg may be
# "latest" or a concrete int as a string. Same key → same loaded
# object across the whole process.
_template_cache: dict[tuple[str, str, str], PromptTemplate] = {}


def _templates_dir() -> Path:
    """Where to look for YAML templates.

    Tests set SHINTTOOLS_PROMPT_REGISTRY_DIR to point at a tmp_path so
    they don't read or stomp the bundled templates.
    """
    override = os.environ.get("SHINTTOOLS_PROMPT_REGISTRY_DIR")
    if override:
        return Path(override)
    return _DEFAULT_TEMPLATES_DIR


def _scan_versions(dir_path: Path) -> list[int]:
    """Return sorted version numbers found in dir_path as vN.yaml."""
    if not dir_path.is_dir():
        return []
    versions: list[int] = []
    for entry in dir_path.iterdir():
        match = _VERSION_FILE_PATTERN.match(entry.name)
        if match and entry.is_file():
            versions.append(int(match.group(1)))
    versions.sort()
    return versions


def _resolve_yaml_path(module: str, engine: str, version: str) -> Path:
    """Walk the resolution order and return the YAML to load.

    Raises FileNotFoundError with a message naming every directory we
    looked in, so a misconfiguration is obvious instead of silent.
    """
    base = _templates_dir()
    candidate_dirs: list[Path] = []
    if module != "_shared":
        candidate_dirs.append(base / module / engine)
    candidate_dirs.append(base / "_shared")

    searched: list[str] = []
    for dir_path in candidate_dirs:
        searched.append(str(dir_path))
        if version == "latest":
            versions = _scan_versions(dir_path)
            if versions:
                return dir_path / f"v{versions[-1]}.yaml"
            continue
        candidate = dir_path / f"v{version}.yaml"
        if candidate.is_file():
            return candidate

    raise FileNotFoundError(
        "No prompt template found for "
        f"module={module!r} engine={engine!r} version={version!r}. "
        f"Searched: {searched}"
    )


def _parse_yaml(yaml_path: Path) -> dict[str, Any]:
    with yaml_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(
            f"Prompt template {yaml_path} must be a YAML mapping; "
            f"got {type(data).__name__}."
        )
    return data


def load_template(module: str, engine: str, version: str = "latest") -> PromptTemplate:
    """Resolve, parse, and cache the template for (module, engine).

    Cache invalidation is process-restart only. Tests call
    reset_cache() between cases.
    """
    cache_key = (module, engine, version)
    cached = _template_cache.get(cache_key)
    if cached is not None:
        return cached

    yaml_path = _resolve_yaml_path(module, engine, version)
    data = _parse_yaml(yaml_path)

    if "system" not in data:
        raise ValueError(f"Template {yaml_path} is missing required 'system' field.")

    generation = data.get("generation") or {}
    template = PromptTemplate(
        module=module,
        engine=engine,
        version=int(data.get("version", 1)),
        model=str(data.get("model", "")),
        system=str(data["system"]).rstrip(),
        few_shots=str(data.get("few_shots", "")).rstrip(),
        stop_tokens=tuple(data.get("stop_tokens") or []),
        max_tokens=int(generation.get("max_tokens", 220)),
        temperature=float(generation.get("temperature", 0.2)),
        source_path=yaml_path,
    )
    _template_cache[cache_key] = template
    return template


def reset_cache() -> None:
    """Clear the in-memory template cache. Test-only entry point."""
    _template_cache.clear()


def list_templates() -> list[tuple[str, str, int, Path]]:
    """Enumerate every (module, engine, version, path) on disk.

    Used by /agent/templates-style diagnostic endpoints and tests.
    Returns an empty list when the templates directory is missing.
    """
    base = _templates_dir()
    if not base.is_dir():
        return []
    out: list[tuple[str, str, int, Path]] = []
    for module_dir in sorted(base.iterdir()):
        if not module_dir.is_dir():
            continue
        if module_dir.name == "_shared":
            for version in _scan_versions(module_dir):
                out.append(
                    ("_shared", "_shared", version, module_dir / f"v{version}.yaml")
                )
            continue
        for engine_dir in sorted(module_dir.iterdir()):
            if not engine_dir.is_dir():
                continue
            for version in _scan_versions(engine_dir):
                out.append(
                    (
                        module_dir.name,
                        engine_dir.name,
                        version,
                        engine_dir / f"v{version}.yaml",
                    )
                )
    return out


# ── (module, engine) resolution from an issue dict ─────────────────────────
#
# Today the orchestrators do NOT inject an explicit module/engine pair,
# so we derive it from the rule_id prefix. That keeps Fase A
# backward-compatible with every existing call site: nothing in the
# detectors or the API has to change for the registry to kick in.
#
# When the orchestrators start setting issue["module"] / issue["engine"]
# explicitly (e.g. for Unity C# vs Unity VS distinction), the explicit
# values win.

_PREFIX_TO_MODULE_ENGINE: dict[str, tuple[str, str]] = {
    # C++ rules — emitted by code_validator/unreal/cpp/
    "CS": ("unreal_cpp", "ue5"),
    "CP": ("unreal_cpp", "ue5"),
    "CB": ("unreal_cpp", "ue5"),
    "CM": ("unreal_cpp", "ue5"),
    # Blueprint rules — emitted by code_validator/unreal/blueprint/
    "BPB": ("unreal_blueprint", "ue5"),
    "BPP": ("unreal_blueprint", "ue5"),
    "BPM": ("unreal_blueprint", "ue5"),
    "BPS": ("unreal_blueprint", "ue5"),
    # LOD auditor rules — all families route to the same template
    "LD": ("lod_auditor", "ue5"),
    "LM": ("lod_auditor", "ue5"),
    "LT": ("lod_auditor", "ue5"),
    "LA": ("lod_auditor", "ue5"),
    "LV": ("lod_auditor", "ue5"),
    "LU": ("lod_auditor", "ue5"),
    "LL": ("lod_auditor", "ue5"),
    "LX": ("lod_auditor", "ue5"),
    "LMB": ("lod_auditor", "ue5"),
    # Naming rules apply to both engines; default to UE5 here.
    # The orchestrator can override with issue["engine"] = "unity6".
    "NM": ("naming", "ue5"),
}


def resolve_module_engine(issue_dict: Mapping[str, Any]) -> tuple[str, str]:
    """Pick the right (module, engine) for an issue.

    Precedence:
        1. Explicit issue["module"] + issue["engine"].
        2. rule_id prefix lookup (3-letter then 2-letter).
        3. ("_shared", "_shared") so the shared template applies.
    """
    explicit_module = issue_dict.get("module")
    explicit_engine = issue_dict.get("engine")
    if (
        isinstance(explicit_module, str)
        and explicit_module
        and isinstance(explicit_engine, str)
        and explicit_engine
    ):
        return explicit_module, explicit_engine

    rule_id = str(issue_dict.get("rule_id") or "")
    alpha_prefix = "".join(ch for ch in rule_id if ch.isalpha())
    for length in (3, 2):
        key = alpha_prefix[:length]
        if key in _PREFIX_TO_MODULE_ENGINE:
            return _PREFIX_TO_MODULE_ENGINE[key]

    return "_shared", "_shared"


# ── Prompt assembly ────────────────────────────────────────────────────────


def assemble(template: PromptTemplate, issue_block: str) -> str:
    """Glue system + few-shots + per-issue block into the final prompt.

    The trailing ``\\n\\nEXPLANATION\\n`` cue is part of the assembled
    output: it tells the LLM to start the explanation right after.
    Stop tokens (configured in the YAML) cut the response when the
    model tries to keep going past the closing line.
    """
    parts: list[str] = [template.system.rstrip()]
    few_shots = template.few_shots.strip()
    if few_shots:
        parts.append(few_shots)
    parts.append(issue_block.rstrip())
    return "\n\n".join(parts) + "\n\nEXPLANATION\n"
