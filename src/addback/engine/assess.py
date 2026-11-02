"""Engine entry point.

Takes a rule set and a reconciliation extract whose anchors have already been
verified, and returns a ``RunResult``.  Touches no network and reads no files:
everything the engine needs is in its arguments, which is what makes the
LLM/arithmetic boundary enforceable rather than aspirational.

Order matters:

    1. pre-computation validation   -> may block
    2. partition the lines          -> may block
    3. cap structure and base       -> may block
    4. recompute                    (only if nothing blocked)
    5. post-computation identity    -> may block, discarding the figures
    6. verdict
"""

from __future__ import annotations

from typing import Optional

from ..models import (
    AgreementRuleSet,
    Flag,
    Recomputation,
    ReconciliationExtract,
    RunResult,
    RunVerdict,
    Severity,
)
from . import caps, recompute as recompute_mod, validate as validate_mod, verdicts


def _blocked(flags: list[Flag]) -> bool:
    return any(f.severity is Severity.BLOCKING for f in flags)


def assess(
    ruleset: AgreementRuleSet,
    extract: ReconciliationExtract,
    cap_base_confirmed: bool = False,
) -> RunResult:
    """Assess one borrower reconciliation against one agreement rule set.

    ``cap_base_confirmed`` records that a human has read the agreement's
    operative cap-base wording and confirmed the engine read it correctly.
    Without it a run that would otherwise agree is held at
    INSUFFICIENT_INFORMATION, because the anchor verifier can prove the clause
    was quoted but not that it was understood.
    """
    flags: list[Flag] = list(validate_mod.validate(ruleset, extract))

    partition, partition_flags = verdicts.classify(ruleset, extract)
    flags.extend(partition_flags)

    base = recompute_mod.base_amount(extract, partition)
    for group in ruleset.cap_groups:
        group_flags = caps.validate_cap_group(group)
        flags.extend(group_flags)
        if not group_flags:
            flags.extend(caps.validate_base(group, base))

    notes: list[str] = []
    recomputation: Optional[Recomputation] = None

    if not _blocked(flags):
        recomputation = recompute_mod.recompute(ruleset, extract, partition)
        if recomputation.decomposition.residual != 0:
            flags.append(
                Flag(
                    "DELTA_RESIDUAL_NONZERO",
                    Severity.BLOCKING,
                    f"the explanation of the difference does not add up: "
                    f"residual {recomputation.decomposition.residual}. No figure "
                    f"is reported.",
                )
            )
            recomputation = None

    verdict = verdicts.run_verdict(tuple(flags), recomputation)

    # The cap base is never auto-accepted while a percentage cap is in play.
    if verdicts.requires_cap_base_confirmation(ruleset) and not cap_base_confirmed:
        if verdict is RunVerdict.AGREES:
            flags.append(
                Flag(
                    "CAP_BASE_CONFIRMATION_REQUIRED",
                    Severity.REVIEW,
                    "a reviewer must confirm the agreement's cap-base wording "
                    "was read correctly before this run can be recorded as "
                    "agreeing with the borrower",
                )
            )
            verdict = RunVerdict.INSUFFICIENT_INFORMATION
        elif verdict is RunVerdict.DISCREPANCY:
            flags.append(
                Flag(
                    "CAP_BASE_UNCONFIRMED",
                    Severity.REVIEW,
                    "the size of the disallowance depends entirely on the cap "
                    "base; a reviewer should confirm the operative wording",
                )
            )
            notes.append(
                "Disallowance is contingent on the unconfirmed cap base."
            )

    return RunResult(
        verdict=verdict,
        flags=tuple(flags),
        recomputation=recomputation,
        lines=partition.results,
        notes=tuple(notes),
    )
