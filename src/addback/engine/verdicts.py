"""Per-line classification into the partition the arithmetic operates on, and
the run-level verdict.

The partition is the only place where "what is this line?" is decided.  Four
destinations:

    uncapped   permitted, no cap group, conditions pass
    grouped    permitted, in a cap group, conditions pass
    excluded   positively determined not eligible (unpermitted, or a condition
               definitely breached)
    review     anything indeterminate

Review lines are split by whether their candidate category belongs to a cap
group, because an uncertain line in a capped group must be evaluated *inside*
that group when the uncertainty bounds are computed -- not added alongside it.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from ..models import (
    NOT_PERMITTED,
    UNMATCHED,
    AgreementRuleSet,
    CapType,
    Confidence,
    ConditionOutcome,
    Effect,
    Flag,
    LineItem,
    LineResult,
    LineVerdict,
    Recomputation,
    ReconciliationExtract,
    RunVerdict,
    Severity,
)
from . import conditions


@dataclass(frozen=True)
class Partition:
    uncapped: tuple[LineItem, ...]
    grouped: dict[str, tuple[LineItem, ...]]
    excluded: tuple[LineItem, ...]
    review: tuple[LineItem, ...]
    review_grouped: dict[str, tuple[LineItem, ...]]
    review_free: tuple[LineItem, ...]
    results: tuple[LineResult, ...]


def _effect_of_exclusion(amount) -> Effect:
    """Direction in which leaving this line out moves covenant EBITDA relative
    to the borrower's claim.

    A positive line that is left out lowers the figure; a negative one raises
    it.  This is why covenant EBITDA can legitimately exceed the claim.
    """
    if amount > 0:
        return Effect.DECREASE
    if amount < 0:
        return Effect.INCREASE
    return Effect.NONE


def _candidate_cap_group(
    ruleset: AgreementRuleSet, line: LineItem
) -> Optional[str]:
    """The cap group a review line would join if it were accepted."""
    candidate_id = line.category_id
    if candidate_id in (UNMATCHED, NOT_PERMITTED):
        candidate_id = line.candidate_category_id
    if not candidate_id:
        return None
    category = ruleset.category(candidate_id)
    return category.cap_group_id if category else None


def classify(
    ruleset: AgreementRuleSet, extract: ReconciliationExtract
) -> tuple[Partition, tuple[Flag, ...]]:
    uncapped: list[LineItem] = []
    grouped: dict[str, list[LineItem]] = defaultdict(list)
    excluded: list[LineItem] = []
    review: list[LineItem] = []
    review_grouped: dict[str, list[LineItem]] = defaultdict(list)
    review_free: list[LineItem] = []
    results: list[LineResult] = []
    flags: list[Flag] = []

    unmodelled_by_category: dict[str, list[str]] = defaultdict(list)
    for unmodelled in ruleset.unmodelled_conditions:
        unmodelled_by_category[unmodelled.category_id].append(unmodelled.text)

    for line in extract.line_items:
        reasons: list[str] = []
        outcome = ConditionOutcome.PASS
        verdict: LineVerdict
        cap_group_id: Optional[str] = None

        def to_review(reason: str) -> None:
            reasons.append(reason)

        # --- evidence checks -------------------------------------------------
        justification_unsupported = (
            line.justification_anchor is not None
            and not line.justification_anchor.usable
        )
        if justification_unsupported:
            to_review(
                "the agreement quote offered for this classification could not "
                "be found in the agreement"
            )

        category = ruleset.category(line.category_id)

        # --- destination -----------------------------------------------------
        if line.category_id == UNMATCHED:
            to_review("the extractor could not match this description to a category")
            verdict = LineVerdict.NEEDS_REVIEW

        elif line.category_id == NOT_PERMITTED:
            if line.confidence is Confidence.LOW:
                to_review(
                    "determined not permitted, but at low confidence"
                )
                verdict = LineVerdict.NEEDS_REVIEW
            else:
                reasons.append(
                    "the agreement's list of permitted adjustments is "
                    "exhaustive and does not cover this item"
                )
                verdict = LineVerdict.NOT_ELIGIBLE_UNPERMITTED

        elif category is None:
            flags.append(
                Flag(
                    "UNKNOWN_CATEGORY_ID",
                    Severity.BLOCKING,
                    f"classified to {line.category_id!r}, which is not a "
                    f"category in this agreement's rule set",
                    line.line_id,
                )
            )
            to_review("classified to a category that does not exist")
            verdict = LineVerdict.NEEDS_REVIEW

        else:
            outcome, condition_reasons = conditions.evaluate(
                category.conditions, line
            )
            reasons.extend(condition_reasons)

            if unmodelled_by_category.get(category.category_id):
                to_review(
                    "the agreement attaches a condition to this category that "
                    "the engine does not model"
                )
                verdict = LineVerdict.NEEDS_REVIEW
            elif outcome is ConditionOutcome.FAIL:
                verdict = LineVerdict.NOT_ELIGIBLE_CONDITION
            elif outcome is ConditionOutcome.NOT_EVALUABLE:
                verdict = LineVerdict.NEEDS_REVIEW
            elif justification_unsupported or line.confidence is Confidence.LOW:
                if line.confidence is Confidence.LOW:
                    to_review("classified at low confidence")
                verdict = LineVerdict.NEEDS_REVIEW
            elif category.cap_group_id:
                cap_group_id = category.cap_group_id
                verdict = LineVerdict.ELIGIBLE_CAPPED_GROUP
            else:
                verdict = LineVerdict.ELIGIBLE

        # --- route -----------------------------------------------------------
        if verdict is LineVerdict.ELIGIBLE:
            uncapped.append(line)
            effect = Effect.NONE
        elif verdict is LineVerdict.ELIGIBLE_CAPPED_GROUP:
            assert cap_group_id is not None
            grouped[cap_group_id].append(line)
            effect = Effect.NONE
        elif verdict is LineVerdict.NEEDS_REVIEW:
            review.append(line)
            cap_group_id = _candidate_cap_group(ruleset, line)
            if cap_group_id:
                review_grouped[cap_group_id].append(line)
            else:
                review_free.append(line)
            effect = _effect_of_exclusion(line.amount)
            # One code, with the precise reasons carried in the message -- the
            # review queue needs the reason text, not a taxonomy.
            flags.append(
                Flag(
                    "LINE_NEEDS_REVIEW",
                    Severity.REVIEW,
                    "; ".join(reasons) or "indeterminate",
                    line.line_id,
                )
            )
        else:
            excluded.append(line)
            effect = _effect_of_exclusion(line.amount)

        results.append(
            LineResult(
                line_id=line.line_id,
                raw_description=line.raw_description,
                amount=line.amount,
                category_id=line.category_id,
                verdict=verdict,
                effect=effect,
                condition_outcome=outcome,
                cap_group_id=cap_group_id,
                reasons=tuple(reasons),
            )
        )

    partition = Partition(
        uncapped=tuple(uncapped),
        grouped={k: tuple(v) for k, v in grouped.items()},
        excluded=tuple(excluded),
        review=tuple(review),
        review_grouped={k: tuple(v) for k, v in review_grouped.items()},
        review_free=tuple(review_free),
        results=tuple(results),
    )
    return partition, tuple(flags)


def requires_cap_base_confirmation(ruleset: AgreementRuleSet) -> bool:
    """True when a percentage cap is in play, so the base is load-bearing.

    The cap base is the one extracted field the engine never auto-accepts: the
    anchor verifier can prove the clause was quoted correctly but not that it
    was read correctly, and the whole disallowance turns on it.
    """
    return any(
        g.cap_type is CapType.PERCENT_OF_BASE for g in ruleset.cap_groups
    )


def run_verdict(
    flags: tuple[Flag, ...],
    recomputation: Optional[Recomputation],
) -> RunVerdict:
    """Three-valued run outcome.

    Materiality is decided by the bounds themselves: if the low and high
    scenarios give the same figure, no open item can change the answer.
    """
    if any(f.severity is Severity.BLOCKING for f in flags):
        return RunVerdict.INSUFFICIENT_INFORMATION
    if recomputation is None:
        return RunVerdict.INSUFFICIENT_INFORMATION
    if recomputation.low.ebitda != recomputation.high.ebitda:
        return RunVerdict.INSUFFICIENT_INFORMATION
    if recomputation.decomposition.delta == 0:
        return RunVerdict.AGREES
    return RunVerdict.DISCREPANCY
