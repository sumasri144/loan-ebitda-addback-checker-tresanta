"""The 12 document-level examples.

Each one starts from a real agreement file and a real borrower report file,
has every quote checked against those files by the real anchor verifier, and
is then run through the real engine. The expected answers in each
``expected.json`` were worked out by hand from the agreement, not read back
out of the engine.

One test method is generated per fixture, so each example is reported
separately. These are the 12 examples; the other test files are unit tests and
are not counted among them.

The LLM extraction layer does not exist and has never been run. The
``extraction.json`` in each fixture is hand-written and stands in for it.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from addback.engine.assess import assess
from addback.models import Effect, LineVerdict, RunVerdict

from . import fixture_loader

D = Decimal

EXPECTED_COUNT = 12


def _check(case: unittest.TestCase, fixture) -> None:
    expected = fixture.expected
    result = assess(
        fixture.ruleset,
        fixture.extract,
        cap_base_confirmed=expected.get("cap_base_confirmed", False),
    )
    codes = {f.code for f in result.flags}

    case.assertIs(
        result.verdict,
        RunVerdict(expected["verdict"]),
        f"{fixture.name}: verdict. flags={sorted(codes)}",
    )

    for code in expected.get("required_flags", []):
        case.assertIn(code, codes, f"{fixture.name}: expected flag {code}")

    if "recomputation" in expected and expected["recomputation"] is None:
        case.assertIsNone(
            result.recomputation,
            f"{fixture.name}: a blocked run must produce no figure",
        )
        return

    r = result.recomputation
    case.assertIsNotNone(r, f"{fixture.name}: expected a figure")

    checks = {
        "covenant_ebitda": r.covenant_ebitda,
        "claimed": r.decomposition.claimed,
        "delta": r.decomposition.delta,
        "low": r.low.ebitda,
        "high": r.high.ebitda,
        "base": r.point.base,
        "disallowed_total": r.decomposition.disallowed_total,
        "excluded_sum": r.decomposition.excluded_sum,
        "review_sum": r.decomposition.review_sum,
    }
    for key, actual in checks.items():
        if key in expected:
            case.assertEqual(
                actual, D(expected[key]), f"{fixture.name}: {key}"
            )

    if "cap" in expected:
        case.assertEqual(
            r.point.groups[0].cap, D(expected["cap"]), f"{fixture.name}: cap"
        )
    if "group_included" in expected:
        case.assertEqual(
            r.point.groups[0].included,
            D(expected["group_included"]),
            f"{fixture.name}: group included",
        )
    if expected.get("no_cap_groups"):
        case.assertEqual(r.point.groups, (), f"{fixture.name}: expected no cap groups")
    if expected.get("covenant_above_claimed"):
        case.assertGreater(
            r.covenant_ebitda,
            r.decomposition.claimed,
            f"{fixture.name}: covenant should exceed the claim",
        )

    by_id = {line.line_id: line for line in result.lines}
    for line_id, verdict in expected.get("line_verdicts", {}).items():
        case.assertIn(line_id, by_id, f"{fixture.name}: no line {line_id}")
        case.assertIs(
            by_id[line_id].verdict,
            LineVerdict(verdict),
            f"{fixture.name}: {line_id} verdict",
        )
    for line_id, effect in expected.get("line_effects", {}).items():
        case.assertIs(
            by_id[line_id].effect, Effect(effect), f"{fixture.name}: {line_id} effect"
        )

    # Properties that must hold for every example that produces a figure.
    case.assertEqual(
        r.decomposition.residual, D("0"), f"{fixture.name}: delta must balance"
    )
    case.assertLessEqual(r.low.ebitda, r.point.ebitda, f"{fixture.name}: low <= point")
    case.assertLessEqual(r.point.ebitda, r.high.ebitda, f"{fixture.name}: point <= high")
    for group in r.point.groups:
        case.assertGreaterEqual(
            group.disallowed, D("0"), f"{fixture.name}: disallowed >= 0"
        )


class DocumentLevelExamples(unittest.TestCase):
    """One generated test per fixture; the methods are attached below."""

    def test_there_are_twelve_examples(self):
        names = [p.name for p in fixture_loader.fixture_dirs()]
        self.assertEqual(
            len(names), EXPECTED_COUNT, f"expected {EXPECTED_COUNT} fixtures, got {names}"
        )

    def test_every_fixture_has_all_four_files(self):
        for path in fixture_loader.fixture_dirs():
            for name in (
                "agreement.txt",
                "reconciliation.txt",
                "extraction.json",
                "expected.json",
            ):
                with self.subTest(fixture=path.name, file=name):
                    self.assertTrue((path / name).is_file(), f"{path.name}/{name}")

    def test_borrower_totals_foot_in_every_document(self):
        # The documents must be internally consistent, otherwise a fixture
        # would be testing the wrong thing.
        for path in fixture_loader.fixture_dirs():
            fixture = fixture_loader.load(path)
            extract = fixture.extract
            total = extract.starting_metric_amount + sum(
                (line.amount for line in extract.line_items), D("0")
            )
            with self.subTest(fixture=path.name):
                self.assertEqual(total, extract.stated_adjusted_ebitda)


def _attach_fixture_tests() -> None:
    for path in fixture_loader.fixture_dirs():
        def make(p):
            def test(self):
                fixture = fixture_loader.load(p)
                _check(self, fixture)

            test.__doc__ = p.name
            return test

        setattr(DocumentLevelExamples, f"test_example_{path.name}", make(path))


_attach_fixture_tests()


if __name__ == "__main__":
    unittest.main()
