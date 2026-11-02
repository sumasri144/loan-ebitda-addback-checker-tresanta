"""Amount parsing at the extraction boundary.

Only explicitly signed amounts are accepted.  Every other convention is
refused so that a human normalises it, because deciding whether '(1,234)' or a
'Less:' column means a deduction is a reading of the document, not arithmetic.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from addback.models import AmountFormatError, parse_amount, try_parse_amount

D = Decimal


class Accepted(unittest.TestCase):
    def test_plain_and_signed_integers(self):
        self.assertEqual(parse_amount("1500"), D("1500"))
        self.assertEqual(parse_amount("+1500"), D("1500"))
        self.assertEqual(parse_amount("-750"), D("-750"))

    def test_thousands_separators(self):
        self.assertEqual(parse_amount("12,860"), D("12860"))
        self.assertEqual(parse_amount("-1,234.50"), D("-1234.50"))

    def test_unicode_minus_and_en_dash(self):
        self.assertEqual(parse_amount("−750"), D("-750"))
        self.assertEqual(parse_amount("–750"), D("-750"))

    def test_decimal_and_int_pass_through(self):
        self.assertEqual(parse_amount(D("1.5")), D("1.5"))
        self.assertEqual(parse_amount(7), D("7"))


class Refused(unittest.TestCase):
    def test_float_is_refused_outright(self):
        with self.assertRaises(AmountFormatError):
            parse_amount(1500.0)

    def test_parenthesised_negative_needs_manual_normalisation(self):
        with self.assertRaises(AmountFormatError) as ctx:
            parse_amount("(1,234)")
        self.assertIn("manual normalisation", str(ctx.exception))

    def test_currency_symbols_and_labels_are_refused(self):
        for bad in ("GBP 1500", "1500k", "Less: 750", "", "   ", "n/a", "--750"):
            with self.subTest(value=bad):
                with self.assertRaises(AmountFormatError):
                    parse_amount(bad)

    def test_booleans_are_refused(self):
        with self.assertRaises(AmountFormatError):
            parse_amount(True)


class NonRaisingForm(unittest.TestCase):
    def test_success(self):
        value, error = try_parse_amount("-750")
        self.assertEqual(value, D("-750"))
        self.assertIsNone(error)

    def test_failure_returns_a_message_for_a_flag(self):
        value, error = try_parse_amount("(750)", where="row 7 amount")
        self.assertIsNone(value)
        self.assertIn("row 7 amount", error)


if __name__ == "__main__":
    unittest.main()
