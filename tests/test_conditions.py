"""Condition evaluation, including the refusal to treat an untestable
condition as satisfied."""

from __future__ import annotations

import unittest

from addback.engine import conditions
from addback.models import Condition, ConditionOutcome, ConditionType

from . import builders as b


class Lookforward(unittest.TestCase):
    def test_within_the_window_passes(self):
        outcome, _ = conditions.evaluate(
            (b.lookforward(12),), b.line("L1", "900", "savings", months=9)
        )
        self.assertIs(outcome, ConditionOutcome.PASS)

    def test_exactly_at_the_window_passes(self):
        outcome, _ = conditions.evaluate(
            (b.lookforward(12),), b.line("L1", "900", "savings", months=12)
        )
        self.assertIs(outcome, ConditionOutcome.PASS)

    def test_beyond_the_window_fails(self):
        outcome, reasons = conditions.evaluate(
            (b.lookforward(12),), b.line("L1", "900", "savings", months=24)
        )
        self.assertIs(outcome, ConditionOutcome.FAIL)
        self.assertIn("exceeds the permitted 12 months", " ".join(reasons))

    def test_missing_period_is_not_evaluable(self):
        outcome, _ = conditions.evaluate(
            (b.lookforward(12),), b.line("L1", "900", "savings")
        )
        self.assertIs(outcome, ConditionOutcome.NOT_EVALUABLE)

    def test_unparseable_limit_is_not_evaluable(self):
        bad = Condition(
            type=ConditionType.LOOKFORWARD_MONTHS_MAX,
            value="twelve",
            quote="within twelve months",
            anchor=b.anchor(),
        )
        outcome, _ = conditions.evaluate((bad,), b.line("L1", "900", "savings", months=9))
        self.assertIs(outcome, ConditionOutcome.NOT_EVALUABLE)


class NonCash(unittest.TestCase):
    def test_non_cash_charge_passes(self):
        outcome, _ = conditions.evaluate(
            (b.non_cash(),), b.line("L1", "640", "sbc", is_cash=False)
        )
        self.assertIs(outcome, ConditionOutcome.PASS)

    def test_cash_charge_fails(self):
        outcome, _ = conditions.evaluate(
            (b.non_cash(),), b.line("L1", "640", "sbc", is_cash=True)
        )
        self.assertIs(outcome, ConditionOutcome.FAIL)

    def test_unknown_cash_nature_is_not_evaluable(self):
        outcome, _ = conditions.evaluate((b.non_cash(),), b.line("L1", "640", "sbc"))
        self.assertIs(outcome, ConditionOutcome.NOT_EVALUABLE)


class Aggregation(unittest.TestCase):
    def test_no_conditions_passes(self):
        outcome, reasons = conditions.evaluate((), b.line("L1", "100", "interest"))
        self.assertIs(outcome, ConditionOutcome.PASS)
        self.assertEqual(reasons, ())

    def test_fail_dominates_not_evaluable(self):
        line = b.line("L1", "900", "savings", months=24)  # fails lookforward
        outcome, _ = conditions.evaluate(
            (b.lookforward(12), b.non_cash()), line  # non_cash not evaluable
        )
        self.assertIs(outcome, ConditionOutcome.FAIL)

    def test_not_evaluable_dominates_pass(self):
        line = b.line("L1", "900", "savings", months=9)  # passes lookforward
        outcome, _ = conditions.evaluate(
            (b.lookforward(12), b.non_cash()), line  # non_cash not evaluable
        )
        self.assertIs(outcome, ConditionOutcome.NOT_EVALUABLE)

    def test_unmodelled_condition_type_is_not_evaluable(self):
        other = Condition(
            type=ConditionType.OTHER,
            value=None,
            quote="subject to such other terms as the Agent may require",
            anchor=b.anchor(),
        )
        outcome, _ = conditions.evaluate((other,), b.line("L1", "100", "x"))
        self.assertIs(outcome, ConditionOutcome.NOT_EVALUABLE)


if __name__ == "__main__":
    unittest.main()
