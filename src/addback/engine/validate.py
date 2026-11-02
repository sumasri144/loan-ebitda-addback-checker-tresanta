"""The validation gate.

Nothing reaches the arithmetic on the extractor's word alone.  Every check here
is deterministic and every failure is a named flag, so a refusal is always
explainable to a reviewer.

Severities:
    BLOCKING  no figure is produced at all
    REVIEW    a figure is produced, but a human must resolve the item
    INFO      recorded for transparency only
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

from ..models import (
    AgreementRuleSet,
    AnchorStatus,
    CapType,
    Flag,
    ReconciliationExtract,
    Scale,
    Severity,
    SignConvention,
)

ZERO = Decimal("0")


def _anchor_flags(label: str, anchor, subject: str = "") -> list[Flag]:
    if anchor is None:
        return [
            Flag(
                "ANCHOR_MISSING",
                Severity.BLOCKING,
                f"{label}: no source anchor was provided",
                subject,
            )
        ]
    if anchor.status is AnchorStatus.INVALID:
        return [
            Flag(
                "ANCHOR_INVALID",
                Severity.BLOCKING,
                f"{label}: the quoted text could not be found in "
                f"{anchor.doc_id!r}; the fact is discarded",
                subject,
            )
        ]
    if anchor.status is AnchorStatus.NOT_VERIFIED:
        return [
            Flag(
                "ANCHOR_NOT_VERIFIED",
                Severity.BLOCKING,
                f"{label}: anchor was never verified against a source document",
                subject,
            )
        ]
    if anchor.status is AnchorStatus.AMBIGUOUS:
        return [
            Flag(
                "ANCHOR_AMBIGUOUS",
                Severity.REVIEW,
                f"{label}: the quoted text appears more than once in "
                f"{anchor.doc_id!r}; a reviewer must confirm which occurrence",
                subject,
            )
        ]
    if anchor.status is AnchorStatus.REPAIRED:
        return [
            Flag(
                "ANCHOR_REPAIRED",
                Severity.INFO,
                f"{label}: the quote was found but at different offsets than "
                f"claimed; offsets corrected",
                subject,
            )
        ]
    return []


def validate_reconciliation(extract: ReconciliationExtract) -> tuple[Flag, ...]:
    flags: list[Flag] = []

    # --- input conventions ---------------------------------------------------
    # Any convention other than explicitly signed amounts is refused for manual
    # normalisation.  Converting it automatically would mean guessing which
    # rows are additions and which are deductions.
    if extract.sign_convention_declared is not SignConvention.SIGNED_EXPLICIT:
        flags.append(
            Flag(
                "SIGN_CONVENTION_REQUIRES_MANUAL_NORMALISATION",
                Severity.BLOCKING,
                "the reconciliation does not declare the SIGNED_EXPLICIT "
                "convention (additions positive, deductions negative); it must "
                "be normalised by hand before it can be processed",
            )
        )
    if extract.scale_declared is Scale.UNDETERMINED:
        flags.append(
            Flag(
                "SCALE_UNDETERMINED",
                Severity.BLOCKING,
                "the reconciliation does not declare a units scale",
            )
        )
    if not extract.currency.strip():
        flags.append(
            Flag("CURRENCY_MISSING", Severity.BLOCKING, "no currency was extracted")
        )

    # --- required evidence ---------------------------------------------------
    flags.extend(_anchor_flags("starting metric", extract.starting_metric_anchor))
    flags.extend(_anchor_flags("stated Adjusted EBITDA", extract.stated_anchor))

    # --- per-line integrity --------------------------------------------------
    ids = Counter(line.line_id for line in extract.line_items)
    for line_id, count in ids.items():
        if count > 1:
            flags.append(
                Flag(
                    "DUPLICATE_LINE_ID",
                    Severity.BLOCKING,
                    f"line id {line_id!r} appears {count} times",
                    line_id,
                )
            )

    descriptions = Counter(
        line.raw_description.strip().casefold() for line in extract.line_items
    )
    for description, count in descriptions.items():
        if count > 1:
            flags.append(
                Flag(
                    "DUPLICATE_DESCRIPTION",
                    Severity.REVIEW,
                    f"{count} lines share the description {description!r}; "
                    f"a reviewer should confirm this is not double counting",
                )
            )

    for line in extract.line_items:
        flags.extend(_anchor_flags("line amount", line.anchor, line.line_id))
        if not line.sign_agrees:
            flags.append(
                Flag(
                    "SIGN_PRESENTATION_MISMATCH",
                    Severity.BLOCKING,
                    f"presented as {line.presentation.value} but the amount is "
                    f"{line.amount}; the label and the sign must agree",
                    line.line_id,
                )
            )

    # --- borrower's own arithmetic -------------------------------------------
    total = extract.starting_metric_amount + sum(
        (line.amount for line in extract.line_items), ZERO
    )
    if total != extract.stated_adjusted_ebitda:
        flags.append(
            Flag(
                "BORROWER_SUM_MISMATCH",
                Severity.BLOCKING,
                f"the starting metric plus the extracted lines total {total}, "
                f"but the reconciliation states {extract.stated_adjusted_ebitda}; "
                f"either the document is inconsistent or a line was missed",
            )
        )

    return tuple(flags)


def validate_ruleset(
    ruleset: AgreementRuleSet, scale: Scale
) -> tuple[Flag, ...]:
    flags: list[Flag] = []

    flags.extend(
        _anchor_flags(f"definition of {ruleset.defined_term_name}", ruleset.base_metric_anchor)
    )

    known_groups = {g.cap_group_id for g in ruleset.cap_groups}

    # A category may belong to at most one cap group, and the two sides of the
    # relationship must agree.
    membership: dict[str, list[str]] = {}
    for group in ruleset.cap_groups:
        for category_id in group.member_category_ids:
            membership.setdefault(category_id, []).append(group.cap_group_id)

    for category_id, group_ids in membership.items():
        if len(group_ids) > 1:
            flags.append(
                Flag(
                    "CAP_GROUP_CONFLICT",
                    Severity.BLOCKING,
                    f"category {category_id!r} is claimed by cap groups "
                    f"{', '.join(sorted(group_ids))}",
                    category_id,
                )
            )

    for category in ruleset.permitted_categories:
        flags.extend(
            _anchor_flags(
                f"category {category.category_id}", category.anchor, category.category_id
            )
        )
        if category.cap_group_id and category.cap_group_id not in known_groups:
            flags.append(
                Flag(
                    "CAP_GROUP_UNKNOWN",
                    Severity.BLOCKING,
                    f"category {category.category_id!r} references cap group "
                    f"{category.cap_group_id!r}, which was not extracted",
                    category.category_id,
                )
            )
        declared = membership.get(category.category_id, [])
        if declared and category.cap_group_id not in declared:
            flags.append(
                Flag(
                    "CAP_GROUP_MEMBERSHIP_INCONSISTENT",
                    Severity.BLOCKING,
                    f"cap group {declared[0]!r} lists category "
                    f"{category.category_id!r}, but the category records "
                    f"{category.cap_group_id!r}",
                    category.category_id,
                )
            )
        if not declared and category.cap_group_id:
            flags.append(
                Flag(
                    "CAP_GROUP_MEMBERSHIP_INCONSISTENT",
                    Severity.BLOCKING,
                    f"category {category.category_id!r} records cap group "
                    f"{category.cap_group_id!r}, which does not list it as a member",
                    category.category_id,
                )
            )

    for group in ruleset.cap_groups:
        flags.extend(
            _anchor_flags(f"cap group {group.cap_group_id}", group.anchor, group.cap_group_id)
        )
        # An absolute cap is stated in currency units; the reconciliation may be
        # in thousands or millions.  Rescaling is a human decision.
        if group.cap_type is CapType.ABSOLUTE_AMOUNT and scale is not Scale.UNITS:
            flags.append(
                Flag(
                    "ABSOLUTE_CAP_SCALE_MISMATCH",
                    Severity.BLOCKING,
                    f"cap group {group.cap_group_id!r} has an absolute cap but "
                    f"the reconciliation is presented in {scale.value}; the cap "
                    f"must be rescaled by hand",
                    group.cap_group_id,
                )
            )

    for unmodelled in ruleset.unmodelled_conditions:
        flags.append(
            Flag(
                "UNMODELLED_CONDITION",
                Severity.REVIEW,
                f"category {unmodelled.category_id!r} carries a condition the "
                f"engine does not model: {unmodelled.text!r}",
                unmodelled.category_id,
            )
        )

    return tuple(flags)


def validate(
    ruleset: AgreementRuleSet, extract: ReconciliationExtract
) -> tuple[Flag, ...]:
    return validate_ruleset(ruleset, extract.scale_declared) + validate_reconciliation(
        extract
    )
