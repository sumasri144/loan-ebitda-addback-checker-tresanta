"""Uncertainty bounds.

Each bound is a full re-evaluation of every cap group, so an uncertain line
that belongs to a capped group is evaluated *inside* that group and its effect
is damped by the cap -- it is never added alongside the group.  These tests are
written so that the wrong implementation (adding the uncertain amount outside
the group) produces a different, named number.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from addback.engine.assess import assess
from addback.models import UNMATCHED, RunVerdict

from . import builders as b

D = Decimal


def rules():
    return b.ruleset(
        categories=[
            b.category("interest_expense"),
            b.category("restructuring_charges", cap_group_id="cg_1"),
        ],
        cap_groups=[b.percent_group("cg_1", ["restructuring_charges"], "0.10")],
    )


class UncertainBothSignsInsideACappedGroup(unittest.TestCase):
    """base = 1,000 + 500 = 1,500; cap = 10% x 1,500 = 150
    confirmed group = +100 -> point allowed 100, covenant 1,600
    uncertain inside the group: +80 and -30

    HIGH admits +80 only:  included 180 -> allowed min(180, 150) = 150 -> 1,650
    LOW  admits -30 only:  included  70 -> allowed min( 70, 150) =  70 -> 1,570
    """

    def setUp(self):
        self.extract = b.extract(
            "1000",
            [
                b.line("L1", "500", "interest_expense", row=1),
                b.line("L2", "100", "restructuring_charges", row=2),
                b.line("L3", "80", UNMATCHED, row=3, candidate="restructuring_charges"),
                b.line("L4", "-30", UNMATCHED, row=4, candidate="restructuring_charges"),
            ],
        )
        self.result = assess(rules(), self.extract, cap_base_confirmed=True)
        self.r = self.result.recomputation

    def test_point_estimate_excludes_both_uncertain_lines(self):
        self.assertEqual(self.r.point.ebitda, D("1600"))
        self.assertEqual(self.r.point.groups[0].included, D("100"))

    def test_high_bound_admits_the_positive_and_is_damped_by_the_cap(self):
        # Adding +80 outside the group would give 1,680.  Inside the group the
        # cap binds at 150, so the true maximum is 1,650.
        self.assertEqual(self.r.high.ebitda, D("1650.00"))
        self.assertNotEqual(self.r.high.ebitda, D("1680"))
        self.assertEqual(self.r.high.groups[0].included, D("180"))
        self.assertEqual(self.r.high.groups[0].allowed, D("150.00"))

    def test_low_bound_admits_the_negative_inside_the_group(self):
        self.assertEqual(self.r.low.ebitda, D("1570.00"))
        self.assertEqual(self.r.low.groups[0].included, D("70"))
        self.assertEqual(self.r.low.groups[0].allowed, D("70"))

    def test_bounds_bracket_the_point_estimate(self):
        self.assertLessEqual(self.r.low.ebitda, self.r.point.ebitda)
        self.assertLessEqual(self.r.point.ebitda, self.r.high.ebitda)

    def test_straddling_bounds_force_abstention(self):
        self.assertIs(self.result.verdict, RunVerdict.INSUFFICIENT_INFORMATION)

    def test_decomposition_balances_with_signed_review_amounts(self):
        d = self.r.decomposition
        self.assertEqual(d.claimed, D("1650"))
        self.assertEqual(d.review_sum, D("50"))  # +80 - 30
        self.assertEqual(d.delta, D("50"))
        self.assertEqual(d.residual, D("0"))


class UncertaintyIsImmaterialWhenTheCapAlreadyBinds(unittest.TestCase):
    """base 1,500; cap 150; confirmed group = +200, already over the cap.
    uncertain inside the group: +80 and -30

    HIGH: included 280 -> allowed 150 -> 1,650
    LOW:  included 170 -> allowed 150 -> 1,650

    Both bounds equal the point estimate, so neither uncertain line can change
    the answer and the run can still reach a confident verdict.  Adding the -30
    outside the group would wrongly give a low bound of 1,620.
    """

    def setUp(self):
        self.extract = b.extract(
            "1000",
            [
                b.line("L1", "500", "interest_expense", row=1),
                b.line("L2", "200", "restructuring_charges", row=2),
                b.line("L3", "80", UNMATCHED, row=3, candidate="restructuring_charges"),
                b.line("L4", "-30", UNMATCHED, row=4, candidate="restructuring_charges"),
            ],
        )
        self.result = assess(rules(), self.extract, cap_base_confirmed=True)
        self.r = self.result.recomputation

    def test_all_three_scenarios_coincide(self):
        self.assertEqual(self.r.point.ebitda, D("1650.00"))
        self.assertEqual(self.r.low.ebitda, D("1650.00"))
        self.assertEqual(self.r.high.ebitda, D("1650.00"))

    def test_the_negative_was_not_added_outside_the_group(self):
        self.assertNotEqual(self.r.low.ebitda, D("1620"))

    def test_a_confident_verdict_is_still_reached(self):
        self.assertIs(self.result.verdict, RunVerdict.DISCREPANCY)

    def test_decomposition_balances(self):
        d = self.r.decomposition
        self.assertEqual(d.claimed, D("1750"))
        self.assertEqual(d.delta, D("100.00"))
        self.assertEqual(d.disallowed_total, D("50.00"))
        self.assertEqual(d.review_sum, D("50"))
        self.assertEqual(d.residual, D("0"))


class UncertainLineWithNoCappedCandidate(unittest.TestCase):
    """An uncertain line whose candidate category is uncapped moves the base --
    and therefore moves a percentage cap with it.  That is correct and not
    circular: the base does not depend on the cap.

    base 1,500; cap 150; confirmed group +200 -> point allowed 150, 1,650
    uncertain free line +1,000 with no candidate category

    HIGH: base 2,500 -> cap 250 -> group allowed 200 -> 2,700
    LOW:  unchanged -> 1,650
    """

    def setUp(self):
        self.extract = b.extract(
            "1000",
            [
                b.line("L1", "500", "interest_expense", row=1),
                b.line("L2", "200", "restructuring_charges", row=2),
                b.line("L3", "1000", UNMATCHED, row=3),
            ],
        )
        self.result = assess(rules(), self.extract, cap_base_confirmed=True)
        self.r = self.result.recomputation

    def test_high_bound_moves_the_base_and_the_cap(self):
        self.assertEqual(self.r.high.base, D("2500"))
        self.assertEqual(self.r.high.groups[0].cap, D("250.00"))
        self.assertEqual(self.r.high.groups[0].allowed, D("200"))
        self.assertEqual(self.r.high.ebitda, D("2700"))

    def test_low_bound_is_the_point_estimate(self):
        self.assertEqual(self.r.low.ebitda, D("1650.00"))
        self.assertEqual(self.r.point.ebitda, D("1650.00"))

    def test_bounds_bracket_the_point_estimate(self):
        self.assertLessEqual(self.r.low.ebitda, self.r.point.ebitda)
        self.assertLessEqual(self.r.point.ebitda, self.r.high.ebitda)

    def test_decomposition_balances(self):
        d = self.r.decomposition
        self.assertEqual(d.review_sum, D("1000"))
        self.assertEqual(d.disallowed_total, D("50.00"))
        self.assertEqual(d.delta, D("1050.00"))
        self.assertEqual(d.residual, D("0"))


class UncertainNegativeOnly(unittest.TestCase):
    """Only the low bound should move when the sole uncertain line is negative.
    The earlier design, which admitted every uncertain line into the high
    bound, would have pushed this one the wrong way."""

    def setUp(self):
        self.extract = b.extract(
            "1000",
            [
                b.line("L1", "500", "interest_expense", row=1),
                b.line("L2", "-120", UNMATCHED, row=2),
            ],
        )
        self.result = assess(
            b.ruleset(categories=[b.category("interest_expense")]), self.extract
        )
        self.r = self.result.recomputation

    def test_high_bound_does_not_move(self):
        self.assertEqual(self.r.high.ebitda, D("1500"))
        self.assertEqual(self.r.point.ebitda, D("1500"))

    def test_low_bound_absorbs_the_negative(self):
        self.assertEqual(self.r.low.ebitda, D("1380"))

    def test_ordering_holds(self):
        self.assertLessEqual(self.r.low.ebitda, self.r.point.ebitda)
        self.assertLessEqual(self.r.point.ebitda, self.r.high.ebitda)


if __name__ == "__main__":
    unittest.main()
