# core/modules/predictive/cost_model/prediction.py
#
# The Prediction band — the only numeric currency of the Predictive Profiler.
#
# Every estimate the module emits is a band {min, expected, max} with a
# declared confidence and a one-sentence basis. There is deliberately no way
# to express "this will cost 1.4 ms" without also expressing how sure we are
# and where the number comes from — static analysis can be honest or it can
# be impressive-looking, and this type picks honest.
#
# Confidence semantics (documented for users in COST_MODEL.md):
#   high   — deterministic arithmetic (BCn texture VRAM, buffer sizes).
#            Band is exact or ±5%.
#   medium — patterns calibrated against reference-project ground truth
#            (rule_costs.yaml carries the calibration_version).
#   low    — uncalibrated heuristics. Bands are wide on purpose.
#
# Aggregation rules:
#   - Bands add member-wise (min+min, expected+expected, max+max). The
#     aggregate max is an upper bound — correlation between items is not
#     modelled, and we never narrow a band when combining.
#   - Combined confidence is the WORST of the inputs.
#   - Units must match to combine; mixing units is a programming error and
#     raises immediately.

from __future__ import annotations

from typing import Iterable

from pydantic import BaseModel

# Ordered worst-first so combining picks the earliest match.
_CONFIDENCE_ORDER: tuple[str, ...] = ("low", "medium", "high")

# Units understood by the model. Kept as a plain frozenset (not an Enum) so
# the JSON contract stays plain strings, mirroring the lod_auditor schema
# style.
UNITS: frozenset[str] = frozenset(
    {
        "ms_frame",  # milliseconds per frame (CPU or GPU)
        "mb",  # megabytes (VRAM / RAM / build size)
        "mb_min",  # megabytes per minute (GC pressure)
        "s",  # seconds (cold load)
        "min",  # minutes (package time)
    }
)


def worst_confidence(*levels: str) -> str:
    """The lowest confidence among *levels* ("low" beats "medium" beats "high")."""
    for level in _CONFIDENCE_ORDER:
        if level in levels:
            return level
    return "low"


class Prediction(BaseModel):
    """A banded estimate: never a bare scalar.

    ``basis`` is a single human sentence explaining where the number comes
    from — it surfaces verbatim in the clients' detail panes.
    """

    expected: float
    min: float
    max: float
    unit: str
    confidence: str  # "high" | "medium" | "low"
    basis: str

    # ── Constructors ─────────────────────────────────────────────────────────

    @classmethod
    def exact(cls, value: float, unit: str, basis: str) -> "Prediction":
        """A deterministic figure (min == expected == max, confidence high)."""
        value = round(value, 2)
        return cls(
            expected=value,
            min=value,
            max=value,
            unit=unit,
            confidence="high",
            basis=basis,
        )

    @classmethod
    def banded(
        cls,
        expected: float,
        lo: float,
        hi: float,
        unit: str,
        confidence: str,
        basis: str,
    ) -> "Prediction":
        return cls(
            expected=round(expected, 2),
            min=round(lo, 2),
            max=round(hi, 2),
            unit=unit,
            confidence=confidence,
            basis=basis,
        )

    @classmethod
    def zero(cls, unit: str, basis: str = "no contributing items") -> "Prediction":
        return cls(expected=0.0, min=0.0, max=0.0, unit=unit,
                   confidence="high", basis=basis)

    # ── Arithmetic ───────────────────────────────────────────────────────────

    def plus(self, other: "Prediction", basis: str | None = None) -> "Prediction":
        """Member-wise band sum. Units must match; confidence degrades."""
        if self.unit != other.unit:
            raise ValueError(
                f"cannot add predictions of different units: "
                f"{self.unit!r} + {other.unit!r}"
            )
        return Prediction(
            expected=round(self.expected + other.expected, 2),
            min=round(self.min + other.min, 2),
            max=round(self.max + other.max, 2),
            unit=self.unit,
            confidence=worst_confidence(self.confidence, other.confidence),
            basis=basis if basis is not None else self.basis,
        )

    def scaled(self, factor: float, basis: str | None = None) -> "Prediction":
        """Scale the whole band by *factor* (>= 0). Confidence unchanged."""
        if factor < 0:
            raise ValueError("scale factor must be >= 0 — use negated() for deltas")
        return Prediction(
            expected=round(self.expected * factor, 2),
            min=round(self.min * factor, 2),
            max=round(self.max * factor, 2),
            unit=self.unit,
            confidence=self.confidence,
            basis=basis if basis is not None else self.basis,
        )

    def negated(self, basis: str | None = None) -> "Prediction":
        """The band as a saving/delta. min stays the SMALLER magnitude:
        a recovery of 0.9–1.8 ms negates to −0.9 (min) … −1.8 (max)."""
        return Prediction(
            expected=round(-self.expected, 2),
            min=round(-self.min, 2),
            max=round(-self.max, 2),
            unit=self.unit,
            confidence=self.confidence,
            basis=basis if basis is not None else self.basis,
        )

    # ── Display ──────────────────────────────────────────────────────────────

    def to_display(self) -> str:
        """"+0.9–1.8 ms, est. +1.4 ms" style string (sign from expected)."""
        suffix = {
            "ms_frame": "ms",
            "mb": "MB",
            "mb_min": "MB/min",
            "s": "s",
            "min": "min",
        }.get(self.unit, self.unit)
        sign = "+" if self.expected >= 0 else "-"
        lo, hi = abs(self.min), abs(self.max)
        if lo == hi:
            return f"{sign}{abs(self.expected)} {suffix}"
        return (
            f"{sign}{min(lo, hi)}–{max(lo, hi)} {suffix}, "
            f"est. {sign}{abs(self.expected)} {suffix}"
        )


def sum_predictions(
    items: Iterable[Prediction], unit: str, basis: str
) -> Prediction:
    """Band-sum of *items* (all of *unit*), or an exact zero when empty."""
    total: Prediction | None = None
    for item in items:
        total = item if total is None else total.plus(item)
    if total is None:
        return Prediction.zero(unit)
    return Prediction(
        expected=total.expected,
        min=total.min,
        max=total.max,
        unit=unit,
        confidence=total.confidence,
        basis=basis,
    )
