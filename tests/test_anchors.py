"""Evidence verification: the control that catches a fabricated citation."""

from __future__ import annotations

import unittest

from addback import documents
from addback.anchors import verify_anchor
from addback.documents import DocumentSet
from addback.models import Anchor, AnchorStatus

SOURCE = (
    'Section 1.01. "Consolidated EBITDA" means Consolidated Net Income plus '
    "Restructuring Charges, provided that the aggregate amount added back "
    "shall not exceed fifteen per cent. (15%) of Capped Adjustment Base."
)


def docs() -> DocumentSet:
    ds = DocumentSet()
    ds.add(documents.from_text("AGR", SOURCE))
    return ds


class VerifyAnchor(unittest.TestCase):
    def test_correct_offsets_verify(self):
        text = documents.normalise(SOURCE)
        quote = "Restructuring Charges"
        start = text.index(quote)
        a = Anchor(doc_id="AGR", quote=quote, char_start=start, char_end=start + len(quote))
        result = verify_anchor(a, docs())
        self.assertIs(result.status, AnchorStatus.VERIFIED)
        self.assertEqual(result.char_start, start)

    def test_omitted_offsets_still_verify(self):
        # Offsets are optional in the schema.  A unique match on the quote
        # alone is full verification; it is not a "repair".
        a = Anchor(doc_id="AGR", quote="Restructuring Charges")
        result = verify_anchor(a, docs())
        self.assertIs(result.status, AnchorStatus.VERIFIED)
        self.assertIsNotNone(result.char_start)

    def test_wrong_offsets_are_repaired_not_rejected(self):
        a = Anchor(doc_id="AGR", quote="Restructuring Charges", char_start=0, char_end=5)
        result = verify_anchor(a, docs())
        self.assertIs(result.status, AnchorStatus.REPAIRED)
        self.assertEqual(
            documents.normalise(SOURCE)[result.char_start : result.char_end],
            "Restructuring Charges",
        )

    def test_fabricated_quote_is_invalid(self):
        a = Anchor(
            doc_id="AGR",
            quote="shall not exceed twenty per cent. (20%) of Consolidated EBITDA",
        )
        result = verify_anchor(a, docs())
        self.assertIs(result.status, AnchorStatus.INVALID)

    def test_repeated_quote_is_ambiguous(self):
        ds = DocumentSet()
        ds.add(documents.from_text("AGR", "the cap applies. the cap applies."))
        result = verify_anchor(Anchor(doc_id="AGR", quote="the cap applies"), ds)
        self.assertIs(result.status, AnchorStatus.AMBIGUOUS)

    def test_unknown_document_is_invalid(self):
        result = verify_anchor(Anchor(doc_id="NOPE", quote="Restructuring"), docs())
        self.assertIs(result.status, AnchorStatus.INVALID)

    def test_empty_quote_is_invalid(self):
        result = verify_anchor(Anchor(doc_id="AGR", quote="   "), docs())
        self.assertIs(result.status, AnchorStatus.INVALID)

    def test_quote_spanning_a_line_break_still_matches(self):
        ds = DocumentSet()
        ds.add(documents.from_text("AGR", "plus Restructuring\n    Charges, provided"))
        result = verify_anchor(Anchor(doc_id="AGR", quote="Restructuring Charges"), ds)
        self.assertIs(result.status, AnchorStatus.VERIFIED)
        self.assertEqual(result.char_start, len("plus "))

    def test_typographic_quotes_normalise(self):
        ds = DocumentSet()
        ds.add(documents.from_text("AGR", "“Consolidated EBITDA” means"))
        result = verify_anchor(Anchor(doc_id="AGR", quote='"Consolidated EBITDA"'), ds)
        self.assertIn(result.status, (AnchorStatus.VERIFIED, AnchorStatus.REPAIRED))

    def test_hash_is_of_normalised_text(self):
        a = documents.from_text("AGR", "a  b\nc")
        b = documents.from_text("AGR", "a b c")
        self.assertEqual(a.sha256, b.sha256)


if __name__ == "__main__":
    unittest.main()
