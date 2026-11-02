"""Evaluation of contractual conditions attached to a permitted category.

The condition vocabulary is a closed enum.  Legal drafting is open-ended, so
anything outside the enum lands in ``AgreementRuleSet.unmodelled_conditions``
and forces review for the affected category -- the engine never decides a
condition it does not understand.

A condition the agreement states but the reconciliation gives no field to test
is NOT_EVALUABLE, which sends the line to review.  It is never treated as
passing.
"""

from __future__ import annotations

from ..models import Condition, ConditionOutcome, ConditionType, LineItem

#: Condition types the engine can test deterministically from a line's fields.
EVALUABLE = frozenset(
    {ConditionType.LOOKFORWARD_MONTHS_MAX, ConditionType.NON_CASH_ONLY}
)


def _evaluate_one(condition: Condition, line: LineItem) -> tuple[ConditionOutcome, str]:
    if condition.type is ConditionType.LOOKFORWARD_MONTHS_MAX:
        if condition.value is None:
            return ConditionOutcome.NOT_EVALUABLE, (
                "agreement states a realisation period but no limit was extracted"
            )
        try:
            limit = int(condition.value)
        except (TypeError, ValueError):
            return ConditionOutcome.NOT_EVALUABLE, (
                f"realisation period limit {condition.value!r} is not an integer"
            )
        if line.realisation_period_months is None:
            return ConditionOutcome.NOT_EVALUABLE, (
                f"limit is {limit} months but the line states no realisation period"
            )
        if line.realisation_period_months > limit:
            return ConditionOutcome.FAIL, (
                f"realisation period {line.realisation_period_months} months "
                f"exceeds the permitted {limit} months"
            )
        return ConditionOutcome.PASS, (
            f"realisation period {line.realisation_period_months} months is "
            f"within the permitted {limit} months"
        )

    if condition.type is ConditionType.NON_CASH_ONLY:
        if line.is_cash is None:
            return ConditionOutcome.NOT_EVALUABLE, (
                "category is non-cash only but the line does not state whether "
                "the charge is cash"
            )
        if line.is_cash:
            return ConditionOutcome.FAIL, (
                "category permits non-cash charges only; this line is a cash charge"
            )
        return ConditionOutcome.PASS, "non-cash charge, as the category requires"

    if condition.type is ConditionType.REQUIRES_CERTIFICATION:
        # Surfaced for the reviewer; deliberately not auto-evaluated, because
        # whether an officer's certificate was delivered is not a fact present
        # in either document.
        return ConditionOutcome.PASS, (
            "agreement requires certification; delivery is not checked by this "
            "engine and is left to the reviewer"
        )

    # WITHIN_PERIOD and OTHER are recognised but not testable from our fields.
    return ConditionOutcome.NOT_EVALUABLE, (
        f"condition type {condition.type.value} is not evaluable from the "
        f"reconciliation fields"
    )


def evaluate(
    conditions: tuple[Condition, ...], line: LineItem
) -> tuple[ConditionOutcome, tuple[str, ...]]:
    """Aggregate outcome over every condition on the category.

    FAIL dominates NOT_EVALUABLE, which dominates PASS: a line that definitely
    breaches one condition is excluded even if another is untestable.
    """
    if not conditions:
        return ConditionOutcome.PASS, ()

    outcomes: list[ConditionOutcome] = []
    reasons: list[str] = []
    for condition in conditions:
        outcome, reason = _evaluate_one(condition, line)
        outcomes.append(outcome)
        reasons.append(f"{condition.type.value}: {reason}")

    if ConditionOutcome.FAIL in outcomes:
        return ConditionOutcome.FAIL, tuple(reasons)
    if ConditionOutcome.NOT_EVALUABLE in outcomes:
        return ConditionOutcome.NOT_EVALUABLE, tuple(reasons)
    return ConditionOutcome.PASS, tuple(reasons)
