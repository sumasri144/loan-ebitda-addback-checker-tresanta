"""Signed recomputation of covenant EBITDA, and the uncertainty bounds.

Notation, all amounts signed (positive raises EBITDA):

    S         starting metric
    P_u       permitted uncapped adjustments
    C_g       confirmed permitted adjustments in cap group g
    X         excluded adjustments (unpermitted, or condition breached)
    U         review adjustments
    p         cap percentage, cap_g = p . base

Point estimate
    base       = S + sum(P_u)
    cap_g      = cap_for_base(g, base)
    allowed_g  = min(C_g, cap_g)
    E_covenant = base + sum_g allowed_g

Delta decomposition (exact for any combination of signs)

    E_claimed - E_covenant = sum_g disallowed_g + sum(X) + sum(U)
                             |_ >= 0 _|          |_ signed _|

    with disallowed_g = C_g - allowed_g = max(0, C_g - cap_g) >= 0.
    The residual must be exactly zero.

Uncertainty bounds
    Each scenario is a full re-evaluation of every cap group, so an uncertain
    line that belongs to a capped group is evaluated *inside* that group and
    its effect is damped by the cap, as it would be in reality.  Review lines
    whose candidate category is uncapped move the base instead -- and therefore
    also move a percentage cap, which is correct and not circular, because the
    base does not depend on the cap.

    HIGH  admits uncertain lines with amount > 0, rejects those with amount < 0
    LOW   admits uncertain lines with amount < 0, rejects those with amount > 0

    base_low <= base_point <= base_high, and min() is monotone non-decreasing
    in both arguments, so

        E_low <= E_covenant <= E_high

    holds by construction for any mix of signs.  This is asserted in the tests
    rather than assumed.
"""

from __future__ import annotations

from decimal import Decimal

from ..models import (
    AgreementRuleSet,
    DeltaDecomposition,
    GroupScenario,
    LineItem,
    Recomputation,
    ReconciliationExtract,
    Scenario,
)
from . import caps
from .verdicts import Partition

ZERO = Decimal("0")

POINT = "POINT"
LOW = "LOW"
HIGH = "HIGH"


def _total(lines: tuple[LineItem, ...]) -> Decimal:
    return sum((line.amount for line in lines), ZERO)


def _selected(
    lines: tuple[LineItem, ...],
    include_positive: bool,
    include_negative: bool,
) -> tuple[LineItem, ...]:
    chosen = []
    for line in lines:
        if line.amount > 0 and include_positive:
            chosen.append(line)
        elif line.amount < 0 and include_negative:
            chosen.append(line)
    return tuple(chosen)


def base_amount(extract: ReconciliationExtract, partition: Partition) -> Decimal:
    """The point-estimate cap base: starting metric plus permitted uncapped
    adjustments, before giving effect to the capped group."""
    return extract.starting_metric_amount + _total(partition.uncapped)


def _scenario(
    name: str,
    ruleset: AgreementRuleSet,
    extract: ReconciliationExtract,
    partition: Partition,
    include_positive: bool,
    include_negative: bool,
) -> Scenario:
    extra_free = _selected(partition.review_free, include_positive, include_negative)
    base = base_amount(extract, partition) + _total(extra_free)

    groups: list[GroupScenario] = []
    for group in ruleset.cap_groups:
        confirmed = partition.grouped.get(group.cap_group_id, ())
        uncertain = _selected(
            partition.review_grouped.get(group.cap_group_id, ()),
            include_positive,
            include_negative,
        )
        included = _total(confirmed) + _total(uncertain)
        cap = caps.cap_for_base(group, base)
        allowed = caps.allowed_amount(included, cap)
        groups.append(
            GroupScenario(
                cap_group_id=group.cap_group_id,
                cap=cap,
                included=included,
                allowed=allowed,
                disallowed=included - allowed,
            )
        )

    ebitda = base + sum((g.allowed for g in groups), ZERO)
    return Scenario(name=name, base=base, groups=tuple(groups), ebitda=ebitda)


def _decompose(
    extract: ReconciliationExtract, partition: Partition, point: Scenario
) -> DeltaDecomposition:
    claimed = extract.stated_adjusted_ebitda
    recomputed = point.ebitda
    delta = claimed - recomputed

    disallowed_total = sum((g.disallowed for g in point.groups), ZERO)
    excluded_sum = _total(partition.excluded)
    review_sum = _total(partition.review)

    residual = delta - (disallowed_total + excluded_sum + review_sum)
    return DeltaDecomposition(
        claimed=claimed,
        recomputed=recomputed,
        delta=delta,
        disallowed_total=disallowed_total,
        excluded_sum=excluded_sum,
        review_sum=review_sum,
        residual=residual,
    )


def recompute(
    ruleset: AgreementRuleSet,
    extract: ReconciliationExtract,
    partition: Partition,
) -> Recomputation:
    """Run the three scenarios and decompose the delta.

    Only called on a run with no blocking flags -- an unsupported cap would
    raise ``caps.UnsupportedCapError`` here, which would be a programming
    error rather than a data problem.
    """
    point = _scenario(POINT, ruleset, extract, partition, False, False)
    high = _scenario(HIGH, ruleset, extract, partition, True, False)
    low = _scenario(LOW, ruleset, extract, partition, False, True)
    return Recomputation(
        point=point,
        low=low,
        high=high,
        decomposition=_decompose(extract, partition, point),
        lines=partition.results,
    )
