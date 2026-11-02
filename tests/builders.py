"""Small constructors so the tests read as arithmetic rather than as plumbing.

Anchors default to VERIFIED here.  Anchor verification itself is exercised in
``test_anchors`` and ``test_validate``; the engine tests are about the signed
arithmetic and should not be cluttered by evidence setup.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional, Sequence

from addback.models import (
    AgreementLocator,
    AgreementRuleSet,
    Anchor,
    AnchorStatus,
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
)

AGREEMENT_DOC = "AGR"
RECON_DOC = "REC"

D = Decimal


def anchor(
    doc_id: str = AGREEMENT_DOC,
    quote: str = "quoted text",
    status: AnchorStatus = AnchorStatus.VERIFIED,
    row: Optional[int] = None,
) -> Anchor:
    locator = (
        RowLocator(row_index=row)
        if row is not None
        else AgreementLocator(section="1.01")
    )
    return Anchor(doc_id=doc_id, quote=quote, status=status, locator=locator)


def lookforward(months: int) -> Condition:
    return Condition(
        type=ConditionType.LOOKFORWARD_MONTHS_MAX,
        value=str(months),
        quote=f"within {months} months",
        anchor=anchor(),
    )


def non_cash() -> Condition:
    return Condition(
        type=ConditionType.NON_CASH_ONLY,
        value=None,
        quote="non-cash charges",
        anchor=anchor(),
    )


def category(
    category_id: str,
    cap_group_id: Optional[str] = None,
    conditions: Sequence[Condition] = (),
) -> PermittedCategory:
    return PermittedCategory(
        category_id=category_id,
        label=category_id.replace("_", " "),
        definition_quote=f"clause for {category_id}",
        anchor=anchor(),
        cap_group_id=cap_group_id,
        conditions=tuple(conditions),
    )


def percent_group(
    cap_group_id: str,
    members: Sequence[str],
    percent: str,
    cap_base: CapBase = CapBase.BASE_PLUS_UNCAPPED_PERMITTED,
) -> CapGroup:
    return CapGroup(
        cap_group_id=cap_group_id,
        member_category_ids=tuple(members),
        cap_type=CapType.PERCENT_OF_BASE,
        cap_base=cap_base,
        cap_value=D(percent),
        base_quote="determined before giving effect to any add-back",
        anchor=anchor(),
    )


def ruleset(
    categories: Sequence[PermittedCategory],
    cap_groups: Sequence[CapGroup] = (),
    unmodelled: Sequence = (),
) -> AgreementRuleSet:
    return AgreementRuleSet(
        agreement_id="AGR-TEST",
        defined_term_name="Consolidated EBITDA",
        base_metric="Consolidated Net Income",
        base_metric_anchor=anchor(),
        permitted_categories=tuple(categories),
        cap_groups=tuple(cap_groups),
        unmodelled_conditions=tuple(unmodelled),
    )


def line(
    line_id: str,
    amount: str,
    category_id: str,
    row: int = 1,
    confidence: Confidence = Confidence.HIGH,
    months: Optional[int] = None,
    is_cash: Optional[bool] = None,
    candidate: Optional[str] = None,
    presentation: Optional[Presentation] = None,
    justification_status: AnchorStatus = AnchorStatus.VERIFIED,
) -> LineItem:
    value = D(amount)
    if presentation is None:
        presentation = (
            Presentation.DEDUCTION if value < 0 else Presentation.ADDITION
        )
    return LineItem(
        line_id=line_id,
        row_index=row,
        raw_description=f"line {line_id}",
        amount=value,
        presentation=presentation,
        anchor=anchor(RECON_DOC, f"line {line_id}", row=row),
        category_id=category_id,
        justification_quote="clause quote",
        justification_anchor=anchor(status=justification_status),
        confidence=confidence,
        realisation_period_months=months,
        is_cash=is_cash,
        candidate_category_id=candidate,
    )


def extract(
    starting: str,
    lines: Sequence[LineItem],
    stated: Optional[str] = None,
    scale: Scale = Scale.THOUSANDS,
    sign_convention: SignConvention = SignConvention.SIGNED_EXPLICIT,
) -> ReconciliationExtract:
    start = D(starting)
    total = start + sum((item.amount for item in lines), D("0"))
    return ReconciliationExtract(
        borrower="Synthetic Borrower Ltd",
        period="Q2 FY2026",
        currency="GBP",
        scale_declared=scale,
        sign_convention_declared=sign_convention,
        starting_metric_label="Consolidated Net Income",
        starting_metric_amount=start,
        starting_metric_anchor=anchor(RECON_DOC, "Consolidated Net Income", row=0),
        line_items=tuple(lines),
        stated_adjusted_ebitda=D(stated) if stated is not None else total,
        stated_anchor=anchor(RECON_DOC, "Adjusted EBITDA as reported"),
        scale_anchor=anchor(RECON_DOC, "SCALE: THOUSANDS"),
        sign_convention_anchor=anchor(RECON_DOC, "SIGN CONVENTION: SIGNED_EXPLICIT"),
    )
