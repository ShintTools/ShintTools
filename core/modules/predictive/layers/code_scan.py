# core/modules/predictive/layers/code_scan.py
#
# In-process code scanning for Layer 3 — mirrors how Layer 1 imports
# lod_auditor.audit_assets directly instead of requiring the client to
# pre-run the LOD audit and pass its findings. Here, the client sends raw
# source (path + content) and Predictive runs the Code Validator's own rule
# engines itself, so a project's code cost no longer depends on the client
# having already triggered a separate /validate/* scan.
#
# Dispatch mirrors api/routes/validate.py::_analyse_file. Deliberately
# thin: this module owns routing + key normalization only, never rule
# logic or costing (that stays in rule_costs.py).

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("shinttools.predictive.code_scan")

_CPP_EXTENSIONS = {".cpp", ".h", ".hpp", ".cc"}


def _normalize_engine(raw: str) -> str:
    e = (raw or "").strip().lower()
    if e in ("unity", "unity6"):
        return "unity"
    return "unreal"


def _scan_one(path: str, content: str, engine: str) -> list[dict[str, Any]]:
    """Run the matching rule engine over one source file.

    Blueprint scanning (run_all_blueprint_rules_from_export) needs an
    export-JSON input, not raw text — out of scope until a UE5 predictive
    client exists to produce that export. Unknown extensions yield no
    issues rather than raising, matching _analyse_file's behaviour.
    """
    ext = Path(path).suffix.lower()
    issues: list[dict[str, Any]] = []

    if engine == "unreal" and ext in _CPP_EXTENSIONS:
        from code_validator.unreal.cpp.cpp_orchestrator import run_all_cpp_rules

        issues = run_all_cpp_rules(content, path)
    elif engine == "unity" and ext == ".cs":
        from code_validator.unity.csharp.csharp_orchestrator import (
            run_all_csharp_rules,
        )

        issues = run_all_csharp_rules(content, path)

    for issue in issues:
        # run_all_*_rules tags "file_path"; Layer 3 / apply_rule_cost read
        # "file" (the shape a client-supplied code_issues entry already
        # has) — normalize so both input paths produce identical items.
        issue.setdefault("file", issue.get("file_path", path))

    return issues


def scan_code_files(files: list[dict[str, Any]], engine: str) -> list[dict[str, Any]]:
    """Scan raw source files and return validator-shaped issues.

    ``files``: ``[{"path": "...", "content": "..."}]``. Errors on one file
    don't sink the batch — logged and skipped, same posture as Layer 1's
    guarded ``audit_assets`` call.
    """
    normalized_engine = _normalize_engine(engine)
    issues: list[dict[str, Any]] = []

    for file in files:
        path = str(file.get("path") or "")
        content = file.get("content")
        if not path or not isinstance(content, str):
            continue
        try:
            issues.extend(_scan_one(path, content, normalized_engine))
        except Exception:  # noqa: BLE001 — one bad file must not sink the scan
            logger.exception("code_scan: failed to scan %s — skipped", path)

    return issues
