"""Cap resolution, including the refusal to compute an unsupported base."""

from __future__ import annotations

import unittest
from decimal import Decimal

from addback.engine import caps
from addback.models import CapBase, CapGroup, CapType, Severity

from . import builders as b

D = Decimal


def group(**overrides) -> CapGroup:
    base = dict(
        cap_group_id="cg_1",
        member_category_ids=("restructuring", "savings"),
        cap_type=CapType.PERCENT_OF_BASE,
        cap_base=CapBase.BASE_PLUS_UNCAPPED_PERMITTED,
        cap_value=D("0.15"),
        base_quote="before giving effect to any add-back",
        anchor=b.anchor(),
    )
    base.update(overrides)
    return CapGroup(**base)


def codes(flags) -> set:
    return {f.code for f in flags}


class CapForBase(unittest.TestCase):
    def test_percentage_of_supported_base(self):
        self.assertEqual(caps.cap_for_base(group(), D("10460")), D("1569.00"))

    def test_absolute_cap_ignores_the_base(self):
        g = group(cap_type=CapType.ABSOLUTE_AMOUNT, cap_value=D("5000"))
        self.assertEqual(caps.cap_for_base(g, D("10460")), D("5000"))
        self.assertEqual(caps.cap_for_base(g, D("1")), D("5000"))

    def test_uncapped_group_returns_none(self):
        g = group(cap_type=CapType.NONE, cap_value=None)
        self.assertIsNone(caps.cap_for_base(g, D("10460")))

    def test_non_positive_base_yields_a_zero_cap(self):
        # A percentage of a non-positive number is not a cap.  The run is
        # blocked separately by validate_base; the value here must still be
        # well defined so the bound scenarios stay monotone.
        self.assertEqual(caps.cap_for_base(group(), D("0")), D("0"))
        self.assertEqual(caps.cap_for_base(group(), D("-500")), D("0"))

    def test_unsupported_base_refuses_to_compute(self):
        g = group(cap_base=CapBase.OTHER_UNSUPPORTED)
        with self.assertRaises(caps.UnsupportedCapError):
            caps.cap_for_base(g, D("10460"))

    def test_undetermined_base_refuses_to_compute(self):
        g = group(cap_base=CapBase.UNDETERMINED)
        with self.assertRaises(caps.UnsupportedCapError):
            caps.cap_for_base(g, D("10460"))


class AllowedAmount(unittest.TestCase):
    def test_under_cap_is_allowed_in_full(self):
        self.assertEqual(caps.allowed_amount(D("1000"), D("1569")), D("1000"))

    def test_at_the_cap_is_allowed_in_full(self):
        self.assertEqual(caps.allowed_amount(D("1569"), D("1569")), D("1569"))

    def test_over_cap_is_trimmed(self):
        self.assertEqual(caps.allowed_amount(D("2400"), D("1569")), D("1569"))

    def test_a_cap_never_suppresses_a_net_deduction(self):
        # A cap limits how far a category may raise EBITDA.  A group whose net
        # is negative is admitted in full.
        self.assertEqual(caps.allowed_amount(D("-300"), D("1569")), D("-300"))

    def test_uncapped_group_allows_everything(self):
        self.assertEqual(caps.allowed_amount(D("99999"), None), D("99999"))


class ValidateCapGroup(unittest.TestCase):
    def test_supported_group_is_clean(self):
        self.assertEqual(caps.validate_cap_group(group()), ())
        self.assertTrue(caps.supported(group()))

    def test_unsupported_base_blocks_and_quotes_the_wording(self):
        g = group(cap_base=CapBase.OTHER_UNSUPPORTED, base_quote="of Consolidated Total Assets")
        flags = caps.validate_cap_group(g)
        self.assertEqual(codes(flags), {"CAP_BASE_UNSUPPORTED"})
        self.assertIs(flags[0].severity, Severity.BLOCKING)
        self.assertIn("Consolidated Total Assets", flags[0].message)

    def test_undetermined_base_blocks(self):
        flags = caps.validate_cap_group(group(cap_base=CapBase.UNDETERMINED))
        self.assertEqual(codes(flags), {"CAP_BASE_UNDETERMINED"})

    def test_undetermined_cap_type_blocks(self):
        flags = caps.validate_cap_group(group(cap_type=CapType.UNDETERMINED))
        self.assertEqual(codes(flags), {"CAP_TYPE_UNDETERMINED"})

    def test_missing_cap_value_blocks(self):
        flags = caps.validate_cap_group(group(cap_value=None))
        self.assertIn("CAP_VALUE_MISSING", codes(flags))

    def test_percentage_outside_zero_to_one_blocks(self):
        for value in ("0", "1", "15", "-0.2"):
            with self.subTest(value=value):
                flags = caps.validate_cap_group(group(cap_value=D(value)))
                self.assertIn("CAP_PERCENTAGE_OUT_OF_RANGE", codes(flags))

    def test_absolute_cap_does_not_need_a_base(self):
        g = group(
            cap_type=CapType.ABSOLUTE_AMOUNT,
            cap_value=D("5000"),
            cap_base=CapBase.UNDETERMINED,
        )
        self.assertEqual(caps.validate_cap_group(g), ())

    def test_uncapped_group_needs_nothing(self):
        g = group(cap_type=CapType.NONE, cap_value=None, cap_base=CapBase.UNDETERMINED)
        self.assertEqual(caps.validate_cap_group(g), ())


class ValidateBase(unittest.TestCase):
    def test_positive_base_is_clean(self):
        self.assertEqual(caps.validate_base(group(), D("10460")), ())

    def test_non_positive_base_blocks(self):
        flags = caps.validate_base(group(), D("-1"))
        self.assertEqual(codes(flags), {"NON_POSITIVE_CAP_BASE"})
        self.assertIs(flags[0].severity, Severity.BLOCKING)

    def test_absolute_cap_is_indifferent_to_the_base(self):
        g = group(cap_type=CapType.ABSOLUTE_AMOUNT, cap_value=D("5000"))
        self.assertEqual(caps.validate_base(g, D("-1")), ())


if __name__ == "__main__":
    unittest.main()
