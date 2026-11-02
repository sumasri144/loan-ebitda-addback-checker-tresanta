"""The validation gate, including the refusal to normalise an unexpected sign
convention."""

from __future__ import annotations

import unittest
from decimal import Decimal

from addback.engine import validate
from addback.models import (
    AnchorStatus,
    CapGroup,
    CapType,
    CapBase,
    Presentation,
    Scale,
    Severity,
    SignConvention,
)

from . import builders as b

D = Decimal


def codes(flags) -> set:
    return {f.code for f in flags}


def severity_of(flags, code) -> Severity:
    return next(f.severity for f in flags if f.code == code)


def simple_rules():
    return b.ruleset(categories=[b.category("interest_expense")])


class InputConventions(unittest.TestCase):
    def test_signed_explicit_is_accepted(self):
        extract = b.extract("1000", [b.line("L1", "500", "interest_expense")])
        self.assertNotIn(
            "SIGN_CONVENTION_REQUIRES_MANUAL_NORMALISATION",
            codes(validate.validate_reconciliation(extract)),
        )

    def test_any_other_convention_is_refused_not_converted(self):
        extract = b.extract(
            "1000",
            [b.line("L1", "500", "interest_expense")],
            sign_convention=SignConvention.UNRECOGNISED,
        )
        flags = validate.validate_reconciliation(extract)
        self.assertIn("SIGN_CONVENTION_REQUIRES_MANUAL_NORMALISATION", codes(flags))
        self.assertIs(
            severity_of(flags, "SIGN_CONVENTION_REQUIRES_MANUAL_NORMALISATION"),
            Severity.BLOCKING,
        )

    def test_undetermined_scale_blocks(self):
        extract = b.extract(
            "1000", [b.line("L1", "500", "interest_expense")], scale=Scale.UNDETERMINED
        )
        self.assertIn("SCALE_UNDETERMINED", codes(validate.validate_reconciliation(extract)))


class PerLineIntegrity(unittest.TestCase):
    def test_label_and_sign_must_agree(self):
        extract = b.extract(
            "1000",
            [
                b.line(
                    "L1", "-500", "interest_expense", presentation=Presentation.ADDITION
                )
            ],
        )
        flags = validate.validate_reconciliation(extract)
        self.assertIn("SIGN_PRESENTATION_MISMATCH", codes(flags))
        self.assertIs(severity_of(flags, "SIGN_PRESENTATION_MISMATCH"), Severity.BLOCKING)

    def test_duplicate_line_ids_block(self):
        extract = b.extract(
            "1000",
            [
                b.line("L1", "500", "interest_expense", row=1),
                b.line("L1", "300", "interest_expense", row=2),
            ],
        )
        self.assertIn("DUPLICATE_LINE_ID", codes(validate.validate_reconciliation(extract)))

    def test_duplicate_descriptions_go_to_review_not_blocking(self):
        from dataclasses import replace

        first = b.line("L1", "500", "interest_expense", row=1)
        second = replace(
            b.line("L2", "500", "interest_expense", row=2),
            raw_description=first.raw_description,
        )
        extract = b.extract("1000", [first, second])
        flags = validate.validate_reconciliation(extract)
        self.assertIn("DUPLICATE_DESCRIPTION", codes(flags))
        self.assertIs(severity_of(flags, "DUPLICATE_DESCRIPTION"), Severity.REVIEW)

    def test_borrower_total_must_reconcile(self):
        extract = b.extract(
            "1000", [b.line("L1", "500", "interest_expense")], stated="1600"
        )
        flags = validate.validate_reconciliation(extract)
        self.assertIn("BORROWER_SUM_MISMATCH", codes(flags))
        message = next(f.message for f in flags if f.code == "BORROWER_SUM_MISMATCH")
        self.assertIn("1500", message)
        self.assertIn("1600", message)


class EvidenceSeverities(unittest.TestCase):
    def test_invalid_line_anchor_blocks(self):
        from dataclasses import replace

        line = b.line("L1", "500", "interest_expense")
        line = replace(line, anchor=replace(line.anchor, status=AnchorStatus.INVALID))
        flags = validate.validate_reconciliation(b.extract("1000", [line]))
        self.assertIn("ANCHOR_INVALID", codes(flags))
        self.assertIs(severity_of(flags, "ANCHOR_INVALID"), Severity.BLOCKING)

    def test_unverified_anchor_blocks(self):
        from dataclasses import replace

        line = b.line("L1", "500", "interest_expense")
        line = replace(
            line, anchor=replace(line.anchor, status=AnchorStatus.NOT_VERIFIED)
        )
        flags = validate.validate_reconciliation(b.extract("1000", [line]))
        self.assertIn("ANCHOR_NOT_VERIFIED", codes(flags))

    def test_ambiguous_anchor_is_review(self):
        from dataclasses import replace

        line = b.line("L1", "500", "interest_expense")
        line = replace(line, anchor=replace(line.anchor, status=AnchorStatus.AMBIGUOUS))
        flags = validate.validate_reconciliation(b.extract("1000", [line]))
        self.assertIs(severity_of(flags, "ANCHOR_AMBIGUOUS"), Severity.REVIEW)

    def test_repaired_anchor_is_informational_only(self):
        from dataclasses import replace

        line = b.line("L1", "500", "interest_expense")
        line = replace(line, anchor=replace(line.anchor, status=AnchorStatus.REPAIRED))
        flags = validate.validate_reconciliation(b.extract("1000", [line]))
        self.assertIs(severity_of(flags, "ANCHOR_REPAIRED"), Severity.INFO)


class RuleSetStructure(unittest.TestCase):
    def test_clean_ruleset_has_no_blocking_flags(self):
        rules = b.ruleset(
            categories=[
                b.category("interest_expense"),
                b.category("restructuring_charges", cap_group_id="cg_1"),
            ],
            cap_groups=[b.percent_group("cg_1", ["restructuring_charges"], "0.15")],
        )
        flags = validate.validate_ruleset(rules, Scale.THOUSANDS)
        self.assertEqual([f for f in flags if f.severity is Severity.BLOCKING], [])

    def test_category_claimed_by_two_groups_blocks(self):
        rules = b.ruleset(
            categories=[b.category("restructuring_charges", cap_group_id="cg_1")],
            cap_groups=[
                b.percent_group("cg_1", ["restructuring_charges"], "0.15"),
                b.percent_group("cg_2", ["restructuring_charges"], "0.20"),
            ],
        )
        self.assertIn(
            "CAP_GROUP_CONFLICT", codes(validate.validate_ruleset(rules, Scale.THOUSANDS))
        )

    def test_reference_to_a_missing_group_blocks(self):
        rules = b.ruleset(categories=[b.category("restructuring_charges", cap_group_id="cg_9")])
        flags = validate.validate_ruleset(rules, Scale.THOUSANDS)
        self.assertIn("CAP_GROUP_UNKNOWN", codes(flags))

    def test_one_sided_membership_blocks(self):
        rules = b.ruleset(
            categories=[b.category("restructuring_charges", cap_group_id="cg_1")],
            cap_groups=[b.percent_group("cg_1", ["savings"], "0.15")],
        )
        self.assertIn(
            "CAP_GROUP_MEMBERSHIP_INCONSISTENT",
            codes(validate.validate_ruleset(rules, Scale.THOUSANDS)),
        )

    def test_absolute_cap_against_a_scaled_statement_blocks(self):
        # The cap is in currency units; the statement is in thousands.
        # Rescaling is a human decision, so the run stops.
        group = CapGroup(
            cap_group_id="cg_1",
            member_category_ids=("restructuring_charges",),
            cap_type=CapType.ABSOLUTE_AMOUNT,
            cap_base=CapBase.UNDETERMINED,
            cap_value=D("5000000"),
            base_quote="GBP 5,000,000",
            anchor=b.anchor(),
        )
        rules = b.ruleset(
            categories=[b.category("restructuring_charges", cap_group_id="cg_1")],
            cap_groups=[group],
        )
        self.assertIn(
            "ABSOLUTE_CAP_SCALE_MISMATCH",
            codes(validate.validate_ruleset(rules, Scale.THOUSANDS)),
        )
        self.assertNotIn(
            "ABSOLUTE_CAP_SCALE_MISMATCH",
            codes(validate.validate_ruleset(rules, Scale.UNITS)),
        )


if __name__ == "__main__":
    unittest.main()
