# core/modules/predictive/tests/test_prediction_math.py
#
# The Prediction band is the module's only numeric currency — its arithmetic
# has to be boringly correct or every layer above it lies.

import pytest
from predictive.cost_model.prediction import (
    Prediction,
    sum_predictions,
    worst_confidence,
)


class TestConstructors:
    def test_exact_is_high_confidence_zero_width(self):
        p = Prediction.exact(21.8, "mb", "4096 BC7 + mips")
        assert p.min == p.expected == p.max == 21.8
        assert p.confidence == "high"

    def test_banded_rounds_to_2_decimals(self):
        p = Prediction.banded(1.4444, 0.911, 1.877, "ms_frame", "medium", "x")
        assert (p.expected, p.min, p.max) == (1.44, 0.91, 1.88)

    def test_zero(self):
        p = Prediction.zero("ms_frame")
        assert p.expected == 0.0 and p.min == 0.0 and p.max == 0.0
        assert p.confidence == "high"


class TestArithmetic:
    def test_plus_adds_member_wise(self):
        a = Prediction.banded(1.4, 0.9, 1.8, "ms_frame", "medium", "a")
        b = Prediction.banded(0.6, 0.1, 1.2, "ms_frame", "high", "b")
        c = a.plus(b)
        assert (c.expected, c.min, c.max) == (2.0, 1.0, 3.0)

    def test_plus_degrades_confidence_to_worst(self):
        a = Prediction.banded(1, 1, 1, "ms_frame", "high", "a")
        b = Prediction.banded(1, 1, 1, "ms_frame", "low", "b")
        assert a.plus(b).confidence == "low"

    def test_plus_never_narrows_the_band(self):
        # Aggregation must widen (or keep) uncertainty, never shrink it.
        a = Prediction.banded(1.4, 0.9, 1.8, "ms_frame", "medium", "a")
        c = a.plus(a)
        assert (c.max - c.min) >= (a.max - a.min)

    def test_plus_rejects_unit_mismatch(self):
        a = Prediction.zero("ms_frame")
        b = Prediction.zero("mb")
        with pytest.raises(ValueError):
            a.plus(b)

    def test_scaled(self):
        a = Prediction.banded(1.0, 0.5, 2.0, "ms_frame", "medium", "a")
        c = a.scaled(3)
        assert (c.expected, c.min, c.max) == (3.0, 1.5, 6.0)
        assert c.confidence == "medium"

    def test_scaled_rejects_negative(self):
        with pytest.raises(ValueError):
            Prediction.zero("mb").scaled(-1)

    def test_negated_flips_sign(self):
        a = Prediction.banded(1.4, 0.9, 1.8, "ms_frame", "medium", "a")
        d = a.negated()
        assert (d.expected, d.min, d.max) == (-1.4, -0.9, -1.8)


class TestSum:
    def test_sum_of_three(self):
        a = Prediction.banded(1.4, 0.9, 1.8, "ms_frame", "medium", "a")
        total = sum_predictions([a, a, a], "ms_frame", "sum of 3")
        assert (total.expected, total.min, total.max) == (4.2, 2.7, 5.4)
        assert total.basis == "sum of 3"

    def test_empty_sum_is_exact_zero(self):
        total = sum_predictions([], "mb", "none")
        assert total.expected == 0.0 and total.confidence == "high"


class TestDisplay:
    def test_spec_example_format(self):
        # The literal target format from the product spec.
        p = Prediction.banded(1.4, 0.9, 1.8, "ms_frame", "medium", "CP006")
        assert p.to_display() == "+0.9–1.8 ms, est. +1.4 ms"

    def test_exact_collapses_to_single_figure(self):
        assert Prediction.exact(21.8, "mb", "x").to_display() == "+21.8 MB"

    def test_negative_delta(self):
        d = Prediction.banded(1.4, 0.9, 1.8, "ms_frame", "medium", "x").negated()
        assert d.to_display() == "-0.9–1.8 ms, est. -1.4 ms"


class TestWorstConfidence:
    def test_order(self):
        assert worst_confidence("high", "medium") == "medium"
        assert worst_confidence("medium", "low", "high") == "low"
        assert worst_confidence("high", "high") == "high"
