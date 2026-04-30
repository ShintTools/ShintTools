# core/modules/metrics/tests/test_score_calculator.py
#
# Unit tests for the Quality Score calculator.
# Covers: perfect score, severity weights, naming penalty reduction,
#          category sub-scores, edge cases, and document structure.

from metrics.score_calculator import (
    compute_score,
    compute_score_from_combined,
    recalculate_after_fixes,
)

# ── Helpers ─────────────────────────────────────────────


def _make_issue(
    rule_id: str = "CP001",
    severity: str = "error",
    category: str = "Performance",
) -> dict:
    """Create a minimal issue dict for testing."""
    return {
        "rule_id": rule_id,
        "severity": severity,
        "category": category,
        "message": f"Test issue {rule_id}",
        "line": 1,
    }


# ── Test: Perfect score (no issues) ────────────────────


class TestPerfectScore:
    def test_zero_issues_gives_100(self):
        result = compute_score(issues=[], files_scanned=10)
        assert result["overall_score"] == 100.0

    def test_zero_issues_zero_files_gives_100(self):
        """Edge case: no files scanned, no issues — still 100."""
        result = compute_score(issues=[], files_scanned=0)
        assert result["overall_score"] == 100.0

    def test_category_scores_all_100_when_no_issues(self):
        result = compute_score(issues=[], files_scanned=5)
        for cat, score in result["category_scores"].items():
            assert score == 100.0, f"{cat} should be 100.0"


# ── Test: Severity weights ──────────────────────────────


class TestSeverityWeights:
    def test_single_error_penalty(self):
        """1 error in 1 file → penalty 5 → score 95."""
        issues = [_make_issue(severity="error")]
        result = compute_score(issues=issues, files_scanned=1)
        assert result["overall_score"] == 95.0

    def test_single_warning_penalty(self):
        """1 warning in 1 file → penalty 2 → score 98."""
        issues = [_make_issue(severity="warning")]
        result = compute_score(issues=issues, files_scanned=1)
        assert result["overall_score"] == 98.0

    def test_single_info_penalty(self):
        """1 info in 1 file → penalty 0.5 → score 99.5."""
        issues = [_make_issue(severity="info")]
        result = compute_score(issues=issues, files_scanned=1)
        assert result["overall_score"] == 99.5

    def test_mixed_severities(self):
        """2 errors + 3 warnings + 4 infos in 1 file.
        penalty = 10 + 6 + 2 = 18, score = 82."""
        issues = (
            [_make_issue(severity="error")] * 2
            + [_make_issue(severity="warning")] * 3
            + [_make_issue(severity="info")] * 4
        )
        result = compute_score(issues=issues, files_scanned=1)
        assert result["overall_score"] == 82.0


# ── Test: File normalization ────────────────────────────


class TestFileNormalization:
    def test_more_files_dilutes_penalty(self):
        """10 errors across 10 files → density 5 → score 95.
        Same 10 errors in 1 file → density 50 → score 50."""
        issues = [_make_issue(severity="error")] * 10
        result_10 = compute_score(issues=issues, files_scanned=10)
        result_1 = compute_score(issues=issues, files_scanned=1)
        assert result_10["overall_score"] > result_1["overall_score"]
        assert result_10["overall_score"] == 95.0
        assert result_1["overall_score"] == 50.0

    def test_zero_files_treated_as_one(self):
        """Avoid division by zero: files_scanned=0 → uses 1."""
        issues = [_make_issue(severity="error")]
        result = compute_score(issues=issues, files_scanned=0)
        assert result["overall_score"] == 95.0


# ── Test: Naming penalty reduction ──────────────────────


class TestNamingReduction:
    def test_naming_error_half_weight(self):
        """NM error = 5 × 0.5 = 2.5 penalty → score 97.5."""
        issues = [_make_issue(rule_id="NM001", severity="error")]
        result = compute_score(issues=issues, files_scanned=1)
        assert result["overall_score"] == 97.5

    def test_naming_warning_half_weight(self):
        """NM warning = 2 × 0.5 = 1.0 penalty → score 99."""
        issues = [_make_issue(rule_id="NM005", severity="warning")]
        result = compute_score(issues=issues, files_scanned=1)
        assert result["overall_score"] == 99.0

    def test_naming_vs_cpp_same_severity(self):
        """NM error penalizes less than CP error."""
        nm_issues = [_make_issue(rule_id="NM001", severity="error")]
        cp_issues = [_make_issue(rule_id="CP001", severity="error")]
        nm_result = compute_score(issues=nm_issues, files_scanned=1)
        cp_result = compute_score(issues=cp_issues, files_scanned=1)
        assert nm_result["overall_score"] > cp_result["overall_score"]


# ── Test: Category sub-scores ──────────────────────────


class TestCategoryScores:
    def test_issues_only_affect_their_category(self):
        """CP issues only lower performance score, not security."""
        issues = [_make_issue(rule_id="CP001", severity="error")]
        result = compute_score(issues=issues, files_scanned=1)
        cats = result["category_scores"]
        assert cats["performance"] == 95.0
        assert cats["security"] == 100.0
        assert cats["best_practices"] == 100.0
        assert cats["maintainability"] == 100.0

    def test_bp_rules_map_to_correct_category(self):
        """BPP issues go to performance, BPS to security."""
        issues = [
            _make_issue(rule_id="BPP001", severity="warning"),
            _make_issue(rule_id="BPS001", severity="error"),
        ]
        result = compute_score(issues=issues, files_scanned=1)
        cats = result["category_scores"]
        assert cats["performance"] == 98.0  # 1 warning = 2 penalty
        assert cats["security"] == 95.0  # 1 error = 5 penalty

    def test_naming_category_exists(self):
        """Naming is its own sub-score category."""
        issues = [_make_issue(rule_id="NM001", severity="warning")]
        result = compute_score(issues=issues, files_scanned=1)
        assert "naming" in result["category_scores"]
        # NM warning = 2 × 0.5 = 1.0 → score 99.0
        assert result["category_scores"]["naming"] == 99.0


# ── Test: Score floor (can't go below 0) ────────────────


class TestScoreFloor:
    def test_massive_issues_bottoms_at_zero(self):
        """50 errors in 1 file → penalty 250 → score 0 (not negative)."""
        issues = [_make_issue(severity="error")] * 50
        result = compute_score(issues=issues, files_scanned=1)
        assert result["overall_score"] == 0.0

    def test_extreme_case_still_zero(self):
        """1000 errors → still 0, never negative."""
        issues = [_make_issue(severity="error")] * 1000
        result = compute_score(issues=issues, files_scanned=1)
        assert result["overall_score"] == 0.0


# ── Test: Document structure ────────────────────────────


class TestDocumentStructure:
    def test_required_fields_present(self):
        result = compute_score(
            issues=[],
            files_scanned=5,
            project_id="my-game",
            scan_type="full",
            tier="indie",
        )
        assert result["project_id"] == "my-game"
        assert result["scan_type"] == "full"
        assert result["tier"] == "indie"
        assert result["files_scanned"] == 5
        assert result["total_issues"] == 0
        assert "timestamp" in result
        assert "overall_score" in result
        assert "category_scores" in result
        assert "issue_counts" in result

    def test_issue_counts_correct(self):
        issues = (
            [_make_issue(severity="error")] * 3
            + [_make_issue(severity="warning")] * 7
            + [_make_issue(severity="info")] * 2
        )
        result = compute_score(issues=issues, files_scanned=10)
        counts = result["issue_counts"]
        assert counts["errors"] == 3
        assert counts["warnings"] == 7
        assert counts["infos"] == 2
        assert result["total_issues"] == 12


# ── Test: compute_score_from_combined ───────────────────


class TestCombinedScore:
    def test_merges_all_issue_types(self):
        cpp = [_make_issue(rule_id="CP001", severity="error")]
        bp = [_make_issue(rule_id="BPP001", severity="warning")]
        nm = [_make_issue(rule_id="NM001", severity="warning")]

        result = compute_score_from_combined(
            cpp_issues=cpp,
            bp_issues=bp,
            nm_issues=nm,
            files_scanned=1,
            project_id="test",
        )
        # penalty: 5 (CP error) + 2 (BPP warning) + 1 (NM warning ×0.5) = 8
        assert result["overall_score"] == 92.0
        assert result["total_issues"] == 3

    def test_empty_combined(self):
        result = compute_score_from_combined(
            cpp_issues=[],
            bp_issues=[],
            nm_issues=[],
            files_scanned=0,
        )
        assert result["overall_score"] == 100.0


# ── Test: Unknown severity fallback ─────────────────────


class TestUnknownSeverity:
    def test_unknown_severity_treated_as_info(self):
        """Unknown severity gets 0.5 weight (same as info)."""
        issues = [_make_issue(severity="critical")]
        result = compute_score(issues=issues, files_scanned=1)
        # Fallback weight 0.5 → score 99.5
        assert result["overall_score"] == 99.5


# ── Test: recalculate_after_fixes ───────────────────────


class TestRecalculateAfterFixes:
    def _make_prev_score(self, issues, files_scanned=10):
        """Helper: compute a score doc to use as 'previous'."""
        return compute_score(
            issues=issues,
            files_scanned=files_scanned,
            project_id="test-project",
        )

    def test_fixing_one_error_improves_score(self):
        """Start with 3 errors (penalty 15, density 1.5, score 98.5).
        Fix 1 error → penalty 10 → density 1.0 → score 99.0."""
        issues = [_make_issue(rule_id="CP001", severity="error")] * 3
        prev = self._make_prev_score(issues, files_scanned=10)
        assert prev["overall_score"] == 98.5

        fixed = [{"rule_id": "CP001", "severity": "error"}]
        result = recalculate_after_fixes(prev, fixed)
        assert result["overall_score"] == 99.0
        assert result["scan_type"] == "fix_update"
        assert result["issue_counts"]["errors"] == 2

    def test_fixing_all_issues_gives_100(self):
        """Fix every issue → score goes to 100."""
        issues = [
            _make_issue(rule_id="CP001", severity="error"),
            _make_issue(rule_id="CS001", severity="warning"),
        ]
        prev = self._make_prev_score(issues, files_scanned=1)

        fixed = [
            {"rule_id": "CP001", "severity": "error"},
            {"rule_id": "CS001", "severity": "warning"},
        ]
        result = recalculate_after_fixes(prev, fixed)
        assert result["overall_score"] == 100.0
        assert result["total_issues"] == 0

    def test_fixing_zero_issues_keeps_score(self):
        """No fixes applied → score unchanged."""
        issues = [_make_issue(rule_id="CP001", severity="error")]
        prev = self._make_prev_score(issues, files_scanned=1)

        result = recalculate_after_fixes(prev, [])
        assert result["overall_score"] == prev["overall_score"]

    def test_category_score_updates_correctly(self):
        """Fixing a performance issue should improve performance sub-score
        but not affect security sub-score."""
        issues = [
            _make_issue(rule_id="CP001", severity="error"),
            _make_issue(rule_id="CS001", severity="warning"),
        ]
        prev = self._make_prev_score(issues, files_scanned=1)

        fixed = [{"rule_id": "CP001", "severity": "error"}]
        result = recalculate_after_fixes(prev, fixed)

        # Performance should improve (fixed the CP error)
        assert result["category_scores"]["performance"] == 100.0
        # Security should stay the same (CS001 still there)
        assert (
            result["category_scores"]["security"] == prev["category_scores"]["security"]
        )

    def test_naming_fix_uses_half_weight(self):
        """Fixing a naming issue subtracts halved penalty."""
        issues = [_make_issue(rule_id="NM001", severity="error")]
        prev = self._make_prev_score(issues, files_scanned=1)
        # NM error = 5 × 0.5 = 2.5 → score 97.5
        assert prev["overall_score"] == 97.5

        fixed = [{"rule_id": "NM001", "severity": "error"}]
        result = recalculate_after_fixes(prev, fixed)
        assert result["overall_score"] == 100.0

    def test_project_id_preserved(self):
        """Project ID carries over from previous score."""
        prev = self._make_prev_score([], files_scanned=5)
        prev["project_id"] = "titanfall-next"
        result = recalculate_after_fixes(prev, [])
        assert result["project_id"] == "titanfall-next"
