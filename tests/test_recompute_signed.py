"""Signed recomputation: the arithmetic the whole system exists to protect.

Every expected figure below is computed by hand in the comments so a reviewer
can check the engine against the agreement rather than against itself.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from addback.engine.assess import assess
from addback.models import (
    NOT_PERMITTED,
    Confidence,
    Effect,
    LineVerdict,
    Presentation,
    RunVerdict,
)

from . import builders as b

D = Decimal


def full_ruleset():
    """Mirrors the synthetic agreement: five uncapped additions, one uncapped
    deduction, and a two-member group capped at 15% of the base."""
    return b.ruleset(
        categories=[
            b.category("interest_expense"),
            b.category("income_taxes"),
            b.category("depreciation_amortisation"),
            b.category("share_based_compensation", conditions=[b.non_cash()]),
            b.category("non_recurring_disposal_gains"),
            b.category("restructuring_charges", cap_group_id="cg_1"),
            b.category(
                "projected_cost_savings",
                cap_group_id="cg_1",
                conditions=[b.lookforward(12)],
            ),
        ],
        cap_groups=[
            b.percent_group(
                "cg_1", ["restructuring_charges", "projected_cost_savings"], "0.15"
            )
        ],
    )


def simple_ruleset():
    """No cap group, so no cap-base confirmation is required."""
    return b.ruleset(categories=[b.category("interest_expense")])


class HeadlineSyntheticCase(unittest.TestCase):
    """The synthetic borrower pack, worked by hand:

        starting metric                        4,200
        uncapped: 1,850 + 1,120 + 3,400 + 640 - 750 = 6,260
        base (E_pre)                          10,460
        cap = 15% x 10,460                     1,569
        capped group claimed 1,500 + 900 =     2,400
        allowed = min(2,400, 1,569) =          1,569
        disallowed                               831
        covenant EBITDA = 10,460 + 1,569 =    12,029
        claimed                               12,860
        delta                                    831
    """

    def setUp(self):
        self.extract = b.extract(
            "4200",
            [
                b.line("L1", "1850", "interest_expense", row=1),
                b.line("L2", "1120", "income_taxes", row=2),
                b.line("L3", "3400", "depreciation_amortisation", row=3),
                b.line("L4", "640", "share_based_compensation", row=4, is_cash=False),
                b.line("L5", "1500", "restructuring_charges", row=5),
                b.line("L6", "900", "projected_cost_savings", row=6, months=9),
                b.line("L7", "-750", "non_recurring_disposal_gains", row=7),
            ],
        )
        self.result = assess(full_ruleset(), self.extract, cap_base_confirmed=True)

    def test_claimed_total_is_consistent(self):
        self.assertEqual(self.extract.stated_adjusted_ebitda, D("12860"))

    def test_base_excludes_the_capped_group(self):
        self.assertEqual(self.result.recomputation.point.base, D("10460"))

    def test_cap_is_fifteen_percent_of_the_base(self):
        group = self.result.recomputation.point.groups[0]
        self.assertEqual(group.cap, D("1569.00"))
        self.assertEqual(group.included, D("2400"))
        self.assertEqual(group.allowed, D("1569.00"))
        self.assertEqual(group.disallowed, D("831.00"))

    def test_covenant_ebitda(self):
        self.assertEqual(self.result.recomputation.covenant_ebitda, D("12029.00"))

    def test_verdict_is_a_discrepancy(self):
        self.assertIs(self.result.verdict, RunVerdict.DISCREPANCY)

    def test_delta_decomposition_balances(self):
        d = self.result.recomputation.decomposition
        self.assertEqual(d.delta, D("831.00"))
        self.assertEqual(d.disallowed_total, D("831.00"))
        self.assertEqual(d.excluded_sum, D("0"))
        self.assertEqual(d.review_sum, D("0"))
        self.assertEqual(d.residual, D("0"))

    def test_no_uncertainty_so_bounds_collapse(self):
        r = self.result.recomputation
        self.assertEqual(r.low.ebitda, r.point.ebitda)
        self.assertEqual(r.high.ebitda, r.point.ebitda)

    def test_the_uncapped_deduction_is_inside_the_cap_base(self):
        # -750 of disposal gains lowers the base and therefore the cap itself.
        # Had it been dropped, the base would be 11,210 and the cap 1,681.50.
        self.assertEqual(self.result.recomputation.point.base, D("10460"))


class UnderCapAgrees(unittest.TestCase):
    """Same shape, capped group within the cap:
        base 10,460; cap 1,569; claimed group 1,200 -> allowed 1,200
        covenant EBITDA 11,660 == claimed 11,660
    """

    def build(self):
        return b.extract(
            "4200",
            [
                b.line("L1", "1850", "interest_expense", row=1),
                b.line("L2", "1120", "income_taxes", row=2),
                b.line("L3", "3400", "depreciation_amortisation", row=3),
                b.line("L4", "640", "share_based_compensation", row=4, is_cash=False),
                b.line("L5", "1200", "restructuring_charges", row=5),
                b.line("L6", "-750", "non_recurring_disposal_gains", row=6),
            ],
        )

    def test_agrees_when_the_cap_base_is_confirmed(self):
        result = assess(full_ruleset(), self.build(), cap_base_confirmed=True)
        self.assertIs(result.verdict, RunVerdict.AGREES)
        self.assertEqual(result.recomputation.covenant_ebitda, D("11660"))
        self.assertEqual(result.recomputation.decomposition.delta, D("0"))

    def test_held_back_when_the_cap_base_is_unconfirmed(self):
        # The anchor verifier can prove the clause was quoted, not that it was
        # read correctly, so agreement with the borrower is never auto-recorded.
        result = assess(full_ruleset(), self.build(), cap_base_confirmed=False)
        self.assertIs(result.verdict, RunVerdict.INSUFFICIENT_INFORMATION)
        self.assertIn(
            "CAP_BASE_CONFIRMATION_REQUIRED", {f.code for f in result.flags}
        )


class ExactlyAtTheCap(unittest.TestCase):
    def test_a_claim_equal_to_the_cap_is_allowed_in_full(self):
        # base = 1,000 + 500 = 1,500; cap = 10% = 150; claimed group = 150
        rules = b.ruleset(
            categories=[
                b.category("interest_expense"),
                b.category("restructuring_charges", cap_group_id="cg_1"),
            ],
            cap_groups=[b.percent_group("cg_1", ["restructuring_charges"], "0.10")],
        )
        extract = b.extract(
            "1000",
            [
                b.line("L1", "500", "interest_expense", row=1),
                b.line("L2", "150", "restructuring_charges", row=2),
            ],
        )
        result = assess(rules, extract, cap_base_confirmed=True)
        group = result.recomputation.point.groups[0]
        self.assertEqual(group.allowed, D("150.00"))
        self.assertEqual(group.disallowed, D("0.00"))
        self.assertIs(result.verdict, RunVerdict.AGREES)


class SignedExclusions(unittest.TestCase):
    def test_an_unpermitted_addition_lowers_covenant_ebitda(self):
        # base 1,500; the +300 is excluded -> covenant 1,500 vs claimed 1,800
        extract = b.extract(
            "1000",
            [
                b.line("L1", "500", "interest_expense", row=1),
                b.line("L2", "300", NOT_PERMITTED, row=2),
            ],
        )
        result = assess(simple_ruleset(), extract)
        self.assertEqual(result.recomputation.covenant_ebitda, D("1500"))
        self.assertEqual(result.recomputation.decomposition.delta, D("300"))
        line = next(l for l in result.lines if l.line_id == "L2")
        self.assertIs(line.verdict, LineVerdict.NOT_ELIGIBLE_UNPERMITTED)
        self.assertIs(line.effect, Effect.DECREASE)
        self.assertIs(result.verdict, RunVerdict.DISCREPANCY)

    def test_an_unpermitted_deduction_raises_covenant_ebitda(self):
        # The borrower deducted something the agreement does not require, so
        # the agreement-compliant figure is HIGHER than the claim.  This is why
        # `covenant <= claimed` is not an invariant of this engine.
        extract = b.extract(
            "1000",
            [
                b.line("L1", "500", "interest_expense", row=1),
                b.line("L2", "-200", NOT_PERMITTED, row=2),
            ],
        )
        result = assess(simple_ruleset(), extract)
        self.assertEqual(extract.stated_adjusted_ebitda, D("1300"))
        self.assertEqual(result.recomputation.covenant_ebitda, D("1500"))
        self.assertGreater(
            result.recomputation.covenant_ebitda, extract.stated_adjusted_ebitda
        )
        d = result.recomputation.decomposition
        self.assertEqual(d.delta, D("-200"))
        # The component itself must stay signed; an absolute magnitude here
        # would break the identity for every negative adjustment.
        self.assertEqual(d.excluded_sum, D("-200"))
        self.assertEqual(d.residual, D("0"))
        line = next(l for l in result.lines if l.line_id == "L2")
        self.assertIs(line.effect, Effect.INCREASE)
        self.assertIs(result.verdict, RunVerdict.DISCREPANCY)

    def test_mixed_sign_exclusions_sum_signed_not_absolute(self):
        # +400 and -150 excluded: the signed sum is +250, not 550.
        extract = b.extract(
            "1000",
            [
                b.line("L1", "500", "interest_expense", row=1),
                b.line("L2", "400", NOT_PERMITTED, row=2),
                b.line("L3", "-150", NOT_PERMITTED, row=3),
            ],
        )
        result = assess(simple_ruleset(), extract)
        d = result.recomputation.decomposition
        self.assertEqual(d.excluded_sum, D("250"))
        self.assertEqual(d.claimed, D("1750"))
        self.assertEqual(result.recomputation.covenant_ebitda, D("1500"))
        self.assertEqual(d.delta, D("250"))
        self.assertEqual(d.residual, D("0"))
        effects = {l.line_id: l.effect for l in result.lines}
        self.assertIs(effects["L2"], Effect.DECREASE)
        self.assertIs(effects["L3"], Effect.INCREASE)

    def test_a_breached_condition_excludes_the_line(self):
        # savings realisable over 24 months against a 12-month window
        extract = b.extract(
            "4200",
            [
                b.line("L1", "1850", "interest_expense", row=1),
                b.line("L2", "900", "projected_cost_savings", row=2, months=24),
            ],
        )
        result = assess(full_ruleset(), extract, cap_base_confirmed=True)
        line = next(l for l in result.lines if l.line_id == "L2")
        self.assertIs(line.verdict, LineVerdict.NOT_ELIGIBLE_CONDITION)
        self.assertIs(line.effect, Effect.DECREASE)
        self.assertEqual(result.recomputation.covenant_ebitda, D("6050"))
        self.assertEqual(result.recomputation.decomposition.excluded_sum, D("900"))
        self.assertEqual(result.recomputation.decomposition.residual, D("0"))


class DecompositionComponentsAreSigned(unittest.TestCase):
    """Tested directly against the recomputation, below ``assess``.

    ``assess`` blocks on a non-zero residual and discards the figures, so a bug
    that makes a component unsigned shows up there only as a refusal. Asserting
    on the components themselves gives a diagnostic failure instead.
    """

    def recompute_with(self, lines):
        from addback.engine import recompute as recompute_mod, verdicts

        extract = b.extract("1000", lines)
        partition, _ = verdicts.classify(simple_ruleset(), extract)
        return recompute_mod.recompute(simple_ruleset(), extract, partition)

    def test_excluded_sum_is_negative_when_exclusions_net_negative(self):
        r = self.recompute_with(
            [
                b.line("L1", "500", "interest_expense", row=1),
                b.line("L2", "150", NOT_PERMITTED, row=2),
                b.line("L3", "-400", NOT_PERMITTED, row=3),
            ]
        )
        d = r.decomposition
        self.assertEqual(d.excluded_sum, D("-250"))
        self.assertEqual(d.claimed, D("1250"))
        self.assertEqual(d.recomputed, D("1500"))
        self.assertEqual(d.delta, D("-250"))
        self.assertEqual(d.residual, D("0"))

    def test_review_sum_is_negative_when_review_lines_net_negative(self):
        from addback.models import UNMATCHED

        r = self.recompute_with(
            [
                b.line("L1", "500", "interest_expense", row=1),
                b.line("L2", "100", UNMATCHED, row=2),
                b.line("L3", "-300", UNMATCHED, row=3),
            ]
        )
        d = r.decomposition
        self.assertEqual(d.review_sum, D("-200"))
        self.assertEqual(d.delta, D("-200"))
        self.assertEqual(d.residual, D("0"))


class MixedSignCapGroup(unittest.TestCase):
    """A cap limits how far a group may raise EBITDA.  It must never suppress a
    deduction inside that group."""

    def rules(self):
        return b.ruleset(
            categories=[
                b.category("interest_expense"),
                b.category("restructuring_charges", cap_group_id="cg_1"),
            ],
            cap_groups=[b.percent_group("cg_1", ["restructuring_charges"], "0.10")],
        )

    def test_net_under_the_cap_is_allowed_in_full(self):
        # base 1,500; cap 150; group = +200 - 100 = +100 net -> allowed 100
        extract = b.extract(
            "1000",
            [
                b.line("L1", "500", "interest_expense", row=1),
                b.line("L2", "200", "restructuring_charges", row=2),
                b.line("L3", "-100", "restructuring_charges", row=3),
            ],
        )
        result = assess(self.rules(), extract, cap_base_confirmed=True)
        group = result.recomputation.point.groups[0]
        self.assertEqual(group.included, D("100"))
        self.assertEqual(group.allowed, D("100"))
        self.assertEqual(group.disallowed, D("0"))
        self.assertEqual(result.recomputation.covenant_ebitda, D("1600"))
        self.assertIs(result.verdict, RunVerdict.AGREES)

    def test_net_negative_group_is_admitted_in_full(self):
        # group = +50 - 150 = -100 net; the cap does not bind on a deduction
        extract = b.extract(
            "1000",
            [
                b.line("L1", "500", "interest_expense", row=1),
                b.line("L2", "50", "restructuring_charges", row=2),
                b.line("L3", "-150", "restructuring_charges", row=3),
            ],
        )
        result = assess(self.rules(), extract, cap_base_confirmed=True)
        group = result.recomputation.point.groups[0]
        self.assertEqual(group.included, D("-100"))
        self.assertEqual(group.allowed, D("-100"))
        self.assertEqual(group.disallowed, D("0"))
        self.assertEqual(result.recomputation.covenant_ebitda, D("1400"))


class RefusalsProduceNoFigure(unittest.TestCase):
    def test_sign_and_label_disagreement_blocks(self):
        extract = b.extract(
            "1000",
            [
                b.line(
                    "L1",
                    "500",
                    "interest_expense",
                    row=1,
                    presentation=Presentation.DEDUCTION,
                )
            ],
        )
        result = assess(simple_ruleset(), extract)
        self.assertIs(result.verdict, RunVerdict.INSUFFICIENT_INFORMATION)
        self.assertIsNone(result.recomputation)
        self.assertIn("SIGN_PRESENTATION_MISMATCH", {f.code for f in result.flags})

    def test_borrower_total_mismatch_blocks(self):
        extract = b.extract(
            "1000",
            [b.line("L1", "500", "interest_expense", row=1)],
            stated="1600",  # should be 1,500
        )
        result = assess(simple_ruleset(), extract)
        self.assertIs(result.verdict, RunVerdict.INSUFFICIENT_INFORMATION)
        self.assertIsNone(result.recomputation)
        self.assertIn("BORROWER_SUM_MISMATCH", {f.code for f in result.flags})

    def test_unsupported_cap_base_blocks_with_no_figure(self):
        from addback.models import CapBase

        rules = b.ruleset(
            categories=[
                b.category("interest_expense"),
                b.category("restructuring_charges", cap_group_id="cg_1"),
            ],
            cap_groups=[
                b.percent_group(
                    "cg_1",
                    ["restructuring_charges"],
                    "0.10",
                    cap_base=CapBase.OTHER_UNSUPPORTED,
                )
            ],
        )
        extract = b.extract(
            "1000",
            [
                b.line("L1", "500", "interest_expense", row=1),
                b.line("L2", "900", "restructuring_charges", row=2),
            ],
        )
        result = assess(rules, extract, cap_base_confirmed=True)
        self.assertIs(result.verdict, RunVerdict.INSUFFICIENT_INFORMATION)
        self.assertIsNone(result.recomputation)
        self.assertIn("CAP_BASE_UNSUPPORTED", {f.code for f in result.flags})

    def test_a_category_outside_the_rule_set_blocks(self):
        extract = b.extract(
            "1000", [b.line("L1", "500", "goodwill_impairment_addback", row=1)]
        )
        result = assess(simple_ruleset(), extract)
        self.assertIs(result.verdict, RunVerdict.INSUFFICIENT_INFORMATION)
        self.assertIn("UNKNOWN_CATEGORY_ID", {f.code for f in result.flags})


class NoCapInTheAgreement(unittest.TestCase):
    def test_absent_cap_means_no_disallowance_and_no_confirmation(self):
        # Guards against inventing a cap the agreement does not contain.
        rules = b.ruleset(categories=[b.category("restructuring_charges")])
        extract = b.extract(
            "1000", [b.line("L1", "9000", "restructuring_charges", row=1)]
        )
        result = assess(rules, extract)  # no confirmation passed
        self.assertEqual(result.recomputation.covenant_ebitda, D("10000"))
        self.assertEqual(result.recomputation.point.groups, ())
        self.assertIs(result.verdict, RunVerdict.AGREES)


class LowConfidenceEscalates(unittest.TestCase):
    def test_a_positive_determination_at_low_confidence_goes_to_review(self):
        extract = b.extract(
            "1000",
            [
                b.line("L1", "500", "interest_expense", row=1),
                b.line("L2", "300", NOT_PERMITTED, row=2, confidence=Confidence.LOW),
            ],
        )
        result = assess(simple_ruleset(), extract)
        line = next(l for l in result.lines if l.line_id == "L2")
        self.assertIs(line.verdict, LineVerdict.NEEDS_REVIEW)
        self.assertIs(result.verdict, RunVerdict.INSUFFICIENT_INFORMATION)

    def test_an_unverifiable_clause_quote_goes_to_review(self):
        from addback.models import AnchorStatus

        extract = b.extract(
            "1000",
            [
                b.line("L1", "500", "interest_expense", row=1),
                b.line(
                    "L2",
                    "300",
                    "interest_expense",
                    row=2,
                    justification_status=AnchorStatus.INVALID,
                ),
            ],
        )
        result = assess(simple_ruleset(), extract)
        line = next(l for l in result.lines if l.line_id == "L2")
        self.assertIs(line.verdict, LineVerdict.NEEDS_REVIEW)
        self.assertIs(result.verdict, RunVerdict.INSUFFICIENT_INFORMATION)


if __name__ == "__main__":
    unittest.main()
