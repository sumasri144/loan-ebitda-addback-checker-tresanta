"""Properties that must hold for every input, and the structural guard on the
LLM/arithmetic boundary.

The randomised test is seeded, so a failure is reproducible.
"""

from __future__ import annotations

import ast
import random
import unittest
from decimal import Decimal
from pathlib import Path

from addback.engine.assess import assess
from addback.models import NOT_PERMITTED, UNMATCHED, Confidence

from . import builders as b

D = Decimal

ENGINE_DIR = Path(__file__).resolve().parent.parent / "src" / "addback" / "engine"

#: The engine must not be able to reach a network, the filesystem, or the
#: extraction layer.  Enforcing this by parsing imports is what makes the
#: separation a property of the code rather than a convention.
FORBIDDEN_IMPORTS = {
    "anthropic",
    "http",
    "httpx",
    "io",
    "os",
    "pathlib",
    "requests",
    "socket",
    "subprocess",
    "urllib",
}
FORBIDDEN_PACKAGE_PARTS = {"extraction", "report"}


def _random_case(rng: random.Random):
    categories = [
        b.category("interest_expense"),
        b.category("disposal_gains"),
        b.category("restructuring_charges", cap_group_id="cg_1"),
        b.category("cost_savings", cap_group_id="cg_1"),
    ]
    rules = b.ruleset(
        categories=categories,
        cap_groups=[
            b.percent_group(
                "cg_1", ["restructuring_charges", "cost_savings"], "0.15"
            )
        ],
    )

    choices = [
        "interest_expense",
        "disposal_gains",
        "restructuring_charges",
        "cost_savings",
        UNMATCHED,
        NOT_PERMITTED,
    ]
    lines = []
    for i in range(rng.randint(0, 8)):
        category_id = rng.choice(choices)
        amount = str(rng.randint(-500, 500))
        candidate = (
            rng.choice(["restructuring_charges", "interest_expense", None])
            if category_id == UNMATCHED
            else None
        )
        confidence = rng.choice(
            [Confidence.HIGH, Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW]
        )
        lines.append(
            b.line(
                f"L{i}",
                amount,
                category_id,
                row=i + 1,
                candidate=candidate,
                confidence=confidence,
            )
        )

    extract = b.extract(str(rng.randint(-200, 2000)), lines)
    return rules, extract


class Properties(unittest.TestCase):
    def test_properties_hold_over_randomised_signed_inputs(self):
        rng = random.Random(20261102)
        checked = 0
        for case in range(400):
            rules, extract = _random_case(rng)
            result = assess(rules, extract, cap_base_confirmed=True)

            if result.recomputation is None:
                # A blocked run must produce no figure at all.
                self.assertTrue(result.blocked, f"case {case}: no figure but not blocked")
                continue

            checked += 1
            r = result.recomputation
            with self.subTest(case=case):
                # The explanation of the difference must add up exactly.
                self.assertEqual(
                    r.decomposition.residual, D("0"), "delta decomposition residual"
                )
                # Bounds must bracket the point estimate for any mix of signs.
                self.assertLessEqual(r.low.ebitda, r.point.ebitda, "low <= point")
                self.assertLessEqual(r.point.ebitda, r.high.ebitda, "point <= high")
                # A disallowance is never negative, in any scenario.
                for scenario in (r.point, r.low, r.high):
                    for group in scenario.groups:
                        self.assertGreaterEqual(
                            group.disallowed, D("0"), f"{scenario.name} disallowed"
                        )
                        self.assertLessEqual(
                            group.allowed, group.included, f"{scenario.name} allowed"
                        )
        self.assertGreater(checked, 100, "too few cases produced a figure to test")

    def test_assessment_is_deterministic(self):
        rules, extract = _random_case(random.Random(7))
        first = assess(rules, extract, cap_base_confirmed=True)
        second = assess(rules, extract, cap_base_confirmed=True)
        self.assertEqual(first, second)


class EngineBoundary(unittest.TestCase):
    def test_engine_modules_cannot_reach_the_outside_world(self):
        modules = sorted(p for p in ENGINE_DIR.glob("*.py"))
        self.assertGreaterEqual(len(modules), 6, "engine modules not found")
        for path in modules:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                for name in names:
                    root = name.split(".")[0]
                    with self.subTest(module=path.name, imported=name):
                        self.assertNotIn(root, FORBIDDEN_IMPORTS)
                        self.assertFalse(
                            FORBIDDEN_PACKAGE_PARTS & set(name.split(".")),
                            f"{path.name} imports {name}",
                        )


if __name__ == "__main__":
    unittest.main()
