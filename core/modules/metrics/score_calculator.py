# core/modules/metrics/score_calculator.py
#
# Quality Score engine for ShintTools.
#
# Computes a 0-100 score from a list of issues produced by the
# validation pipeline.  The score is penalty-based:
#
#   penalty  = sum of weighted issues
#   density  = penalty / max(files_scanned, 1)
#   score    = clamp(100 - density, 0, 100)
#
# Severity weights:
#   error   → 5 points
#   warning → 2 points
#   info    → 0.5 points
#
# Naming rules (NM*) contribute with halved weight (×0.5 multiplier)
# because bad naming is bad practice but doesn't affect runtime.
#
# Sub-scores are computed per category using the same formula,
# filtered by the category's rule prefixes.

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

# ── Severity weights ────────────────────────────────────

SEVERITY_WEIGHTS: Dict[str, float] = {
    "error": 5.0,
    "warning": 2.0,
    "info": 0.5,
}

# Naming rules get halved penalty (cosmetic, not runtime-impacting)
_NAMING_PENALTY_MULTIPLIER: float = 0.5

# ── Category definitions ────────────────────────────────
#
# Each category maps to the rule-ID prefixes that belong to it.
# This lets us compute sub-scores by filtering issues.

CATEGORY_PREFIXES: Dict[str, List[str]] = {
    "performance": ["CP", "BPP"],
    "security": ["CS", "BPS"],
    "best_practices": ["CB", "BPB"],
    "maintainability": ["CM", "BPM"],
    "naming": ["NM"],
}


# ── Helpers ─────────────────────────────────────────────


def _is_naming_rule(rule_id: str) -> bool:
    """Check if a rule_id belongs to the Naming category."""
    return rule_id.startswith("NM")


def _issue_penalty(issue: Dict[str, Any]) -> float:
    """Calculate the penalty contribution of a single issue."""
    severity = issue.get("severity", "info")
    weight = SEVERITY_WEIGHTS.get(severity, 0.5)
    rule_id = issue.get("rule_id", "")

    if _is_naming_rule(rule_id):
        weight *= _NAMING_PENALTY_MULTIPLIER

    return weight


def _compute_score_from_penalty(penalty: float, files_scanned: int) -> float:
    """Convert raw penalty into a 0-100 score, normalized by files."""
    divisor = max(files_scanned, 1)
    density = penalty / divisor
    score = max(0.0, 100.0 - density)
    return round(score, 1)


def _count_by_severity(issues: List[Dict[str, Any]]) -> Dict[str, int]:
    """Count issues grouped by severity."""
    counts: Dict[str, int] = {"errors": 0, "warnings": 0, "infos": 0}
    for issue in issues:
        sev = issue.get("severity", "info")
        if sev == "error":
            counts["errors"] += 1
        elif sev == "warning":
            counts["warnings"] += 1
        else:
            counts["infos"] += 1
    return counts


def _issues_for_category(
    issues: List[Dict[str, Any]],
    prefixes: List[str],
) -> List[Dict[str, Any]]:
    """Filter issues to those whose rule_id starts with any prefix."""
    return [
        i for i in issues if any(i.get("rule_id", "").startswith(p) for p in prefixes)
    ]


# ── Public API ──────────────────────────────────────────


def compute_category_scores(
    issues: List[Dict[str, Any]],
    files_scanned: int,
) -> Dict[str, float]:
    """Compute sub-scores for each category.

    Returns a dict like::

        {
            "performance": 85.0,
            "security": 92.5,
            "best_practices": 78.0,
            "maintainability": 90.0,
            "naming": 95.0,
        }
    """
    scores: Dict[str, float] = {}

    for category, prefixes in CATEGORY_PREFIXES.items():
        cat_issues = _issues_for_category(issues, prefixes)
        penalty = sum(_issue_penalty(i) for i in cat_issues)
        scores[category] = _compute_score_from_penalty(penalty, files_scanned)

    return scores


def compute_score(
    issues: List[Dict[str, Any]],
    files_scanned: int,
    project_id: str = "",
    scan_type: str = "full",
    tier: str = "free",
) -> Dict[str, Any]:
    """Compute the full Quality Score document.

    This is the main entry point.  It takes the raw issues list
    from any /validate/* endpoint and produces a complete score
    document ready to be persisted in MongoDB.

    Parameters
    ----------
    issues : list[dict]
        Issues as returned by the validation pipeline.
    files_scanned : int
        Number of files/blueprints analysed in this scan.
    project_id : str
        Project identifier from the plugin.
    scan_type : str
        "full" or "incremental".
    tier : str
        Subscription tier of the client.

    Returns
    -------
    dict
        Complete score document with overall_score, category_scores,
        issue_counts, and metadata.
    """
    # Overall penalty (naming already halved inside _issue_penalty)
    total_penalty = sum(_issue_penalty(i) for i in issues)
    overall_score = _compute_score_from_penalty(total_penalty, files_scanned)

    # Category breakdown
    category_scores = compute_category_scores(issues, files_scanned)

    # Issue counts
    severity_counts = _count_by_severity(issues)

    return {
        "project_id": project_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overall_score": overall_score,
        "category_scores": category_scores,
        "issue_counts": severity_counts,
        "files_scanned": files_scanned,
        "total_issues": len(issues),
        "total_penalty": round(total_penalty, 1),
        "scan_type": scan_type,
        "tier": tier,
    }


def compute_score_from_combined(
    cpp_issues: List[Dict[str, Any]],
    bp_issues: List[Dict[str, Any]],
    nm_issues: List[Dict[str, Any]],
    files_scanned: int,
    project_id: str = "",
    tier: str = "free",
) -> Dict[str, Any]:
    """Convenience wrapper that merges issues from all pipelines.

    Useful when the plugin sends C++, Blueprint, and Naming results
    separately and the caller wants a single unified score.
    """
    all_issues = cpp_issues + bp_issues + nm_issues
    return compute_score(
        issues=all_issues,
        files_scanned=files_scanned,
        project_id=project_id,
        scan_type="full",
        tier=tier,
    )


def recalculate_after_fixes(
    previous_score_doc: Dict[str, Any],
    fixed_issues: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Recalculate score after issues have been fixed.

    Instead of re-scanning the whole project, this takes the
    previous score document and subtracts the penalties of the
    issues that were successfully fixed.

    Parameters
    ----------
    previous_score_doc : dict
        The last persisted score document from MongoDB.
    fixed_issues : list[dict]
        Issues that were successfully fixed.  Each must have
        at least ``rule_id`` and ``severity``.

    Returns
    -------
    dict
        Updated score document ready to be persisted.
    """
    # Subtract penalties of fixed issues from previous total
    fixed_penalty = sum(_issue_penalty(i) for i in fixed_issues)
    prev_penalty = previous_score_doc.get("total_penalty", 0.0)
    new_penalty = max(0.0, prev_penalty - fixed_penalty)

    files_scanned = previous_score_doc.get("files_scanned", 1)
    new_overall = _compute_score_from_penalty(new_penalty, files_scanned)

    # Recalculate category scores by subtracting fixed penalties
    prev_cat_scores = previous_score_doc.get("category_scores", {})
    new_cat_scores: Dict[str, float] = {}

    for category, prefixes in CATEGORY_PREFIXES.items():
        cat_fixed = _issues_for_category(fixed_issues, prefixes)
        cat_fixed_penalty = sum(_issue_penalty(i) for i in cat_fixed)

        if cat_fixed_penalty > 0:
            # Reverse-engineer previous penalty from previous score
            prev_cat_score = prev_cat_scores.get(category, 100.0)
            prev_cat_penalty = (100.0 - prev_cat_score) * max(files_scanned, 1)
            new_cat_penalty = max(0.0, prev_cat_penalty - cat_fixed_penalty)
            new_cat_scores[category] = _compute_score_from_penalty(
                new_cat_penalty, files_scanned
            )
        else:
            new_cat_scores[category] = prev_cat_scores.get(category, 100.0)

    # Update issue counts
    prev_counts = previous_score_doc.get("issue_counts", {})
    fixed_counts = _count_by_severity(fixed_issues)
    new_counts = {
        "errors": max(0, prev_counts.get("errors", 0) - fixed_counts["errors"]),
        "warnings": max(0, prev_counts.get("warnings", 0) - fixed_counts["warnings"]),
        "infos": max(0, prev_counts.get("infos", 0) - fixed_counts["infos"]),
    }
    new_total_issues = (
        new_counts["errors"] + new_counts["warnings"] + new_counts["infos"]
    )

    return {
        "project_id": previous_score_doc.get("project_id", ""),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overall_score": new_overall,
        "category_scores": new_cat_scores,
        "issue_counts": new_counts,
        "files_scanned": files_scanned,
        "total_issues": new_total_issues,
        "total_penalty": round(new_penalty, 1),
        "scan_type": "fix_update",
        "tier": previous_score_doc.get("tier", "free"),
    }
