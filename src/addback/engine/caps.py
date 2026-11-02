"""Cap resolution.

Exactly one percentage base is supported:

    BASE_PLUS_UNCAPPED_PERMITTED
        the starting metric plus the aggregate net amount of every permitted
        *uncapped* adjustment, determined before giving effect to the capped
        adjustment group.

That is the base our synthetic agreement defines in terms, and it is not
generalised.  A base defined any other way -- a percentage of total assets, a
percentage of pro forma EBITDA, a base computed after the capped group -- must
be returned by the extractor as OTHER_UNSUPPORTED, which blocks the run.  The
system detects that the base matters and declines, rather than guessing.

``cap_for_base`` is a pure function of (group, base) and is called three times
per group: once for the point estimate and once for each uncertainty bound.
Flags are raised separately, by ``validate_cap_group``, so that the three calls
cannot produce triplicate flags.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from ..models import CapBase, CapGroup, CapType, Flag, Severity

ZERO = Decimal("0")


class UnsupportedCapError(RuntimeError):
    """Raised if a figure is requested for a cap the engine cannot compute.

    Reaching this is a programming error: ``validate_cap_group`` raises a
    BLOCKING flag for the same condition, and a blocked run never recomputes.
    """


def validate_cap_group(group: CapGroup) -> tuple[Flag, ...]:
    """Structural checks on one cap group.  Called once per run."""
    flags: list[Flag] = []
    subject = group.cap_group_id

    if group.cap_type is CapType.UNDETERMINED:
        flags.append(
            Flag(
                "CAP_TYPE_UNDETERMINED",
                Severity.BLOCKING,
                "the cap type could not be determined from the agreement",
                subject,
            )
        )
        return tuple(flags)

    if group.cap_type is CapType.NONE:
        return ()

    if group.cap_value is None:
        flags.append(
            Flag(
                "CAP_VALUE_MISSING",
                Severity.BLOCKING,
                f"cap type is {group.cap_type.value} but no cap value was extracted",
                subject,
            )
        )

    if group.cap_type is CapType.PERCENT_OF_BASE:
        if group.cap_base is CapBase.OTHER_UNSUPPORTED:
            flags.append(
                Flag(
                    "CAP_BASE_UNSUPPORTED",
                    Severity.BLOCKING,
                    "the agreement defines the cap base in a way this engine "
                    "does not support; no figure will be produced. Operative "
                    f"wording: {group.base_quote!r}",
                    subject,
                )
            )
        elif group.cap_base is CapBase.UNDETERMINED:
            flags.append(
                Flag(
                    "CAP_BASE_UNDETERMINED",
                    Severity.BLOCKING,
                    "the cap base could not be determined from the agreement",
                    subject,
                )
            )
        elif group.cap_value is not None and not (ZERO < group.cap_value < 1):
            flags.append(
                Flag(
                    "CAP_PERCENTAGE_OUT_OF_RANGE",
                    Severity.BLOCKING,
                    f"percentage cap {group.cap_value} is not a fraction "
                    f"strictly between 0 and 1",
                    subject,
                )
            )

    return tuple(flags)


def supported(group: CapGroup) -> bool:
    return not validate_cap_group(group)


def cap_for_base(group: CapGroup, base: Decimal) -> Optional[Decimal]:
    """The cap amount for this group given ``base``.

    Returns ``None`` when the group is uncapped.  A non-positive base yields a
    cap of zero -- a percentage of a non-positive number is not a cap, and
    ``validate_base`` raises a BLOCKING flag for it separately.
    """
    if group.cap_type is CapType.NONE:
        return None
    if group.cap_type is CapType.ABSOLUTE_AMOUNT:
        if group.cap_value is None:
            raise UnsupportedCapError(f"{group.cap_group_id}: absolute cap has no value")
        return group.cap_value
    if group.cap_type is CapType.PERCENT_OF_BASE:
        if group.cap_value is None:
            raise UnsupportedCapError(f"{group.cap_group_id}: percentage cap has no value")
        if group.cap_base is not CapBase.BASE_PLUS_UNCAPPED_PERMITTED:
            raise UnsupportedCapError(
                f"{group.cap_group_id}: cap base {group.cap_base.value} is not supported"
            )
        if base <= ZERO:
            return ZERO
        return group.cap_value * base
    raise UnsupportedCapError(f"{group.cap_group_id}: cap type {group.cap_type.value}")


def validate_base(group: CapGroup, base: Decimal) -> tuple[Flag, ...]:
    """Check the point-estimate base for this group."""
    if group.cap_type is not CapType.PERCENT_OF_BASE:
        return ()
    if base > ZERO:
        return ()
    return (
        Flag(
            "NON_POSITIVE_CAP_BASE",
            Severity.BLOCKING,
            f"the cap base is {base}; a percentage of a non-positive base is "
            f"not a cap, so no figure will be produced",
            group.cap_group_id,
        ),
    )


def allowed_amount(included: Decimal, cap: Optional[Decimal]) -> Decimal:
    """How much of ``included`` the cap admits.

    ``min`` handles signs without a special case.  A cap limits how far a
    category may *raise* EBITDA, so a group whose net is at or below the cap --
    including any negative net -- is admitted in full.  A cap never forces a
    deduction to be ignored.
    """
    if cap is None:
        return included
    return min(included, cap)
