"""Load a document-level fixture and turn it into engine input.

A fixture directory holds four files:

    agreement.txt       the agreement terms the case needs
    reconciliation.txt  the borrower's report
    extraction.json     hand-written structured data standing in for the
                        extraction layer, which does not exist
    expected.json       the expected engine result, worked out by hand

This loader deliberately lives in ``tests/`` and not in ``src/``. It is test
scaffolding, not the extraction layer. It does no reading of prose and makes
no judgement: it parses JSON, builds the schema objects, and hands every quote
to the real anchor verifier to be checked against the real document text. A
quote that is not in the document fails here exactly as it would in a live
run, which is what fixture 08 relies on.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from addback import documents
from addback.anchors import verify_anchor
from addback.documents import DocumentSet
from addback.models import (
    AgreementLocator,
    AgreementRuleSet,
    Anchor,
    CapBase,
    CapGroup,
    CapType,
    Condition,
    ConditionType,
    Confidence,
    LineItem,
    PermittedCategory,
    Presentation,
    ReconciliationExtract,
    RowLocator,
    Scale,
    SignConvention,
    parse_amount,
)

AGREEMENT_DOC = "AGREEMENT"
RECONCILIATION_DOC = "RECONCILIATION"

FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "data" / "fixtures"


@dataclass(frozen=True)
class LoadedFixture:
    name: str
    title: str
    ruleset: AgreementRuleSet
    extract: ReconciliationExtract
    expected: dict
    docs: DocumentSet


def _agreement_anchor(quote: str, docs: DocumentSet, clause: str = "") -> Anchor:
    anchor = Anchor(
        doc_id=AGREEMENT_DOC,
        quote=quote,
        locator=AgreementLocator(
            section="1.01", defined_term="Consolidated EBITDA", clause_path=clause
        ),
    )
    return verify_anchor(anchor, docs)


def _row_anchor(quote: str, row: int, label: str, docs: DocumentSet) -> Anchor:
    anchor = Anchor(
        doc_id=RECONCILIATION_DOC,
        quote=quote,
        locator=RowLocator(row_index=row, row_label=label),
    )
    return verify_anchor(anchor, docs)


def _conditions(raw: list[dict], docs: DocumentSet) -> tuple[Condition, ...]:
    out = []
    for item in raw:
        out.append(
            Condition(
                type=ConditionType(item["type"]),
                value=item.get("value"),
                quote=item["quote"],
                anchor=_agreement_anchor(item["quote"], docs),
            )
        )
    return tuple(out)


def _build_ruleset(raw: dict, docs: DocumentSet) -> AgreementRuleSet:
    categories = []
    for item in raw["categories"]:
        categories.append(
            PermittedCategory(
                category_id=item["id"],
                label=item["label"],
                definition_quote=item["quote"],
                anchor=_agreement_anchor(item["quote"], docs, item["id"]),
                cap_group_id=item.get("cap_group"),
                conditions=_conditions(item.get("conditions", []), docs),
            )
        )

    cap_groups = []
    for item in raw.get("cap_groups", []):
        cap_value = item.get("cap_value")
        cap_groups.append(
            CapGroup(
                cap_group_id=item["id"],
                member_category_ids=tuple(item["members"]),
                cap_type=CapType(item["cap_type"]),
                cap_base=CapBase(item["cap_base"]),
                cap_value=parse_amount(cap_value) if cap_value is not None else None,
                base_quote=item["base_quote"],
                anchor=_agreement_anchor(item["base_quote"], docs, item["id"]),
            )
        )

    return AgreementRuleSet(
        agreement_id=raw["agreement_id"],
        defined_term_name=raw["defined_term_name"],
        base_metric=raw["base_metric"],
        base_metric_anchor=_agreement_anchor(raw["base_metric_quote"], docs),
        permitted_categories=tuple(categories),
        cap_groups=tuple(cap_groups),
    )


def _build_extract(raw: dict, docs: DocumentSet) -> ReconciliationExtract:
    lines = []
    for item in raw["lines"]:
        justification_quote = item.get("justification_quote")
        justification_anchor: Optional[Anchor] = None
        if justification_quote is not None:
            justification_anchor = _agreement_anchor(justification_quote, docs)

        lines.append(
            LineItem(
                line_id=item["id"],
                row_index=item["row"],
                raw_description=item["description"],
                amount=parse_amount(item["amount"], f"row {item['row']}"),
                presentation=Presentation(item["presentation"]),
                anchor=_row_anchor(
                    item["quote"], item["row"], item["description"], docs
                ),
                category_id=item["category"],
                justification_quote=justification_quote or "",
                justification_anchor=justification_anchor,
                confidence=Confidence(item.get("confidence", "HIGH")),
                realisation_period_months=item.get("months"),
                is_cash=item.get("is_cash"),
                candidate_category_id=item.get("candidate"),
            )
        )

    return ReconciliationExtract(
        borrower=raw["borrower"],
        period=raw["period"],
        currency=raw["currency"],
        scale_declared=Scale(raw["scale"]),
        sign_convention_declared=SignConvention(raw["sign_convention"]),
        starting_metric_label=raw["starting_label"],
        starting_metric_amount=parse_amount(raw["starting_amount"]),
        starting_metric_anchor=_row_anchor(
            raw["starting_quote"], 0, raw["starting_label"], docs
        ),
        line_items=tuple(lines),
        stated_adjusted_ebitda=parse_amount(raw["stated_adjusted_ebitda"]),
        stated_anchor=_row_anchor(
            raw["stated_quote"], 99, "Adjusted EBITDA as reported", docs
        ),
    )


def load(fixture_dir: Path) -> LoadedFixture:
    docs = DocumentSet()
    docs.add(documents.load(fixture_dir / "agreement.txt", AGREEMENT_DOC))
    docs.add(documents.load(fixture_dir / "reconciliation.txt", RECONCILIATION_DOC))

    raw = json.loads((fixture_dir / "extraction.json").read_text(encoding="utf-8"))
    expected = json.loads((fixture_dir / "expected.json").read_text(encoding="utf-8"))

    return LoadedFixture(
        name=fixture_dir.name,
        title=expected.get("_title", ""),
        ruleset=_build_ruleset(raw["agreement"], docs),
        extract=_build_extract(raw["reconciliation"], docs),
        expected=expected,
        docs=docs,
    )


def fixture_dirs() -> list[Path]:
    return sorted(p for p in FIXTURE_ROOT.iterdir() if p.is_dir())
