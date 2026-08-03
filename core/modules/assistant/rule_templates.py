# core/modules/assistant/rule_templates.py
#
# Tier A — the parameterized template catalog for studio rules.
#
# A template is a deterministic, already-audited check; defining a rule
# means filling its parameters, never generating code. This is the same
# declarative spirit as the threshold YAML profiles, applied to per-studio
# conventions. Evaluation is pure Python over (path, content) pairs — no
# LLM anywhere in Tier A, so a template rule costs nothing per scan and
# can never hallucinate a violation.
#
# The catalog is intentionally small and grows by observed demand. Adding
# a template means: an entry in TEMPLATES + an evaluator here + tests.

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any, Callable

# One violation: same vocabulary the code_validator issues use, so template
# findings render in the existing panels without a new client contract.
Violation = dict[str, Any]

Evaluator = Callable[[dict[str, Any], str, str], list[Violation]]


def _violation(
    rule_name: str, file_path: str, line: int, message: str
) -> Violation:
    return {
        "rule_id": "STUDIO",
        "rule_name": rule_name,
        "file": file_path,
        "line": line,
        "severity": "warning",
        "message": message,
        "auto_fixable": False,
        "source": "studio_rule",
    }


def _line_of(content: str, index: int) -> int:
    return content.count("\n", 0, index) + 1


# ── Evaluators ────────────────────────────────────────────────────────────────


def _eval_forbidden_api(
    params: dict[str, Any], path: str, content: str
) -> list[Violation]:
    """params: {api: str, scope_suffixes: [".h", ...] (optional), reason: str}"""
    api = str(params.get("api", "")).strip()
    if not api:
        return []
    suffixes = tuple(params.get("scope_suffixes") or ())
    if suffixes and not path.lower().endswith(tuple(s.lower() for s in suffixes)):
        return []
    out: list[Violation] = []
    for match in re.finditer(re.escape(api), content):
        out.append(
            _violation(
                str(params.get("_rule_name", f"Forbidden API: {api}")),
                path,
                _line_of(content, match.start()),
                (
                    f"'{api}' is forbidden by a team rule"
                    + (f": {params['reason']}" if params.get("reason") else ".")
                ),
            )
        )
    return out


def _eval_naming_pattern(
    params: dict[str, Any], path: str, content: str
) -> list[Violation]:
    """params: {file_glob_suffix: str, pattern: str (regex over the stem)}

    Checks the FILE name, not the content — the cheap, unambiguous 80% of
    naming conventions ("all widgets start with SShint").
    """
    suffix = str(params.get("file_glob_suffix", "")).strip()
    pattern = str(params.get("pattern", "")).strip()
    if not pattern:
        return []
    if suffix and not path.lower().endswith(suffix.lower()):
        return []
    stem = PurePosixPath(path.replace("\\", "/")).stem
    try:
        if re.fullmatch(pattern, stem):
            return []
    except re.error:
        return []  # a broken pattern must not take down the scan
    return [
        _violation(
            str(params.get("_rule_name", "Naming convention")),
            path,
            1,
            f"File name '{stem}' does not match the team pattern /{pattern}/.",
        )
    ]


def _eval_required_text(
    params: dict[str, Any], path: str, content: str
) -> list[Violation]:
    """params: {required: str, when_contains: str, scope_suffixes: [...]}

    "Any file that mentions X must also contain Y" — covers required
    super-calls, license headers, include guards.
    """
    required = str(params.get("required", "")).strip()
    trigger = str(params.get("when_contains", "")).strip()
    if not required:
        return []
    suffixes = tuple(params.get("scope_suffixes") or ())
    if suffixes and not path.lower().endswith(tuple(s.lower() for s in suffixes)):
        return []
    if trigger and trigger not in content:
        return []
    if required in content:
        return []
    return [
        _violation(
            str(params.get("_rule_name", f"Required: {required}")),
            path,
            1,
            (
                f"Team rule requires '{required}'"
                + (f" whenever '{trigger}' is used" if trigger else "")
                + ", but it is missing from this file."
            ),
        )
    ]


def _eval_file_location(
    params: dict[str, Any], path: str, content: str
) -> list[Violation]:
    """params: {file_glob_suffix: str, required_dir: str}"""
    suffix = str(params.get("file_glob_suffix", "")).strip()
    required_dir = str(params.get("required_dir", "")).strip().replace("\\", "/")
    if not suffix or not required_dir:
        return []
    normalized = path.replace("\\", "/")
    if not normalized.lower().endswith(suffix.lower()):
        return []
    if required_dir.lower() in normalized.lower():
        return []
    return [
        _violation(
            str(params.get("_rule_name", "File location")),
            path,
            1,
            f"Files matching '*{suffix}' belong under '{required_dir}/' "
            "by team rule.",
        )
    ]


# template_id -> (human name, evaluator, required params)
TEMPLATES: dict[str, dict[str, Any]] = {
    "forbidden_api": {
        "label": "Forbidden API/token",
        "evaluator": _eval_forbidden_api,
        "required_params": ("api",),
    },
    "naming_pattern": {
        "label": "File naming pattern",
        "evaluator": _eval_naming_pattern,
        "required_params": ("pattern",),
    },
    "required_text": {
        "label": "Required text/call",
        "evaluator": _eval_required_text,
        "required_params": ("required",),
    },
    "file_location": {
        "label": "Required file location",
        "evaluator": _eval_file_location,
        "required_params": ("file_glob_suffix", "required_dir"),
    },
}


def evaluate_template_rule(
    rule: dict[str, Any], files: list[tuple[str, str]]
) -> list[Violation]:
    """Run one template rule over (path, content) pairs. Unknown template
    or missing params -> no findings (a broken rule never breaks a scan)."""
    template = rule.get("template") or {}
    spec = TEMPLATES.get(str(template.get("template_id", "")))
    if spec is None:
        return []
    params = dict(template.get("params") or {})
    if any(not params.get(k) for k in spec["required_params"]):
        return []
    params["_rule_name"] = rule.get("name", spec["label"])

    out: list[Violation] = []
    for path, content in files:
        out.extend(spec["evaluator"](params, path, content or ""))
    return out
