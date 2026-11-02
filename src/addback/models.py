"""Schemas for the Covenant EBITDA Add-back Verification Engine.

Four design rules are encoded structurally in this module:

1. Money is ``Decimal``.  ``parse_amount`` refuses ``float`` outright, so a
   float cannot enter the system even by accident.
2. No schema has a field for a *computed* figure.  The extraction layer has
   nowhere to put a calculation, which is how the LLM is kept out of the
   arithmetic rather than merely asked to stay out.
3. A sign/presentation disagreement is NOT raised as a parse error.  It is
   reported by ``engine.validate`` as a BLOCKING flag so that the run still
   produces a reviewable report instead of a stack trace.
4. Only one cap base is supported: BASE_PLUS_UNCAPPED_PERMITTED.  Anything
   else is OTHER_UNSUPPORTED and is escalated, never approximated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional, Union

# ---------------------------------------------------------------------------
# Classification sentinels
# ---------------------------------------------------------------------------
# UNMATCHED and NOT_PERMITTED are deliberately distinct.  UNMATCHED means the
# extractor could not determine the category -> human review.  NOT_PERMITTED is
# a positive determination that the agreement's list is exhaustive and this
# item falls outside it -> excluded from covenant EBITDA.
UNMATCHED = "UNMATCHED"
NOT_PERMITTED = "NOT_PERMITTED"
SENTINEL_CATEGORY_IDS = frozenset({UNMATCHED, NOT_PERMITTED})


class AnchorStatus(str, Enum):
    NOT_VERIFIED = "NOT_VERIFIED"
    VERIFIED = "VERIFIED"
    REPAIRED = "REPAIRED"
    AMBIGUOUS = "AMBIGUOUS"
    INVALID = "INVALID"


class Presentation(str, Enum):
    ADDITION = "ADDITION"
    DEDUCTION = "DEDUCTION"


class SignConvention(str, Enum):
    """Only SIGNED_EXPLICIT is accepted.  Every other convention is flagged for
    manual normalisation and is never silently converted."""

    SIGNED_EXPLICIT = "SIGNED_EXPLICIT"
    UNRECOGNISED = "UNRECOGNISED"


class Scale(str, Enum):
    UNITS = "UNITS"
    THOUSANDS = "THOUSANDS"
    MILLIONS = "MILLIONS"
    UNDETERMINED = "UNDETERMINED"


class CapType(str, Enum):
    PERCENT_OF_BASE = "PERCENT_OF_BASE"
    ABSOLUTE_AMOUNT = "ABSOLUTE_AMOUNT"
    NONE = "NONE"
    UNDETERMINED = "UNDETERMINED"


class CapBase(str, Enum):
    """The only supported base, spelled out so the schema itself states it: the
    starting metric plus every permitted *uncapped* adjustment, determined
    before giving effect to the capped adjustment group.

    This is not generalised to other agreements.  A base defined any other way
    must be returned as OTHER_UNSUPPORTED."""

    BASE_PLUS_UNCAPPED_PERMITTED = "BASE_PLUS_UNCAPPED_PERMITTED"
    OTHER_UNSUPPORTED = "OTHER_UNSUPPORTED"
    UNDETERMINED = "UNDETERMINED"


class ConditionType(str, Enum):
    LOOKFORWARD_MONTHS_MAX = "LOOKFORWARD_MONTHS_MAX"
    NON_CASH_ONLY = "NON_CASH_ONLY"
    WITHIN_PERIOD = "WITHIN_PERIOD"
    REQUIRES_CERTIFICATION = "REQUIRES_CERTIFICATION"
    OTHER = "OTHER"


class ConditionOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EVALUABLE = "NOT_EVALUABLE"


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class LineVerdict(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    ELIGIBLE_CAPPED_GROUP = "ELIGIBLE_CAPPED_GROUP"
    NOT_ELIGIBLE_UNPERMITTED = "NOT_ELIGIBLE_UNPERMITTED"
    NOT_ELIGIBLE_CONDITION = "NOT_ELIGIBLE_CONDITION"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class Effect(str, Enum):
    """Direction in which excluding this line moves covenant EBITDA relative to
    the borrower's claimed figure."""

    INCREASE = "INCREASE"
    DECREASE = "DECREASE"
    NONE = "NONE"


class RunVerdict(str, Enum):
    AGREES = "AGREES"
    DISCREPANCY = "DISCREPANCY"
    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"


class Severity(str, Enum):
    BLOCKING = "BLOCKING"
    REVIEW = "REVIEW"
    INFO = "INFO"


# ---------------------------------------------------------------------------
# Amount parsing
# ---------------------------------------------------------------------------

_AMOUNT_RE = re.compile(r"^[+-]?\d+(\.\d+)?$")


class AmountFormatError(ValueError):
    """Raised at the extraction boundary only.  Callers convert this into a
    BLOCKING flag; the engine itself never parses amounts."""


def parse_amount(value: object, where: str = "amount") -> Decimal:
    """Parse a signed amount.

    Rejects floats, and rejects every sign convention other than an explicit
    leading '-'.  Parenthesised negatives, 'Add:'/'Less:' columns and
    absolute-value presentations are refused rather than converted: deciding
    how to normalise them is a human judgement, not something to guess at.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool) or isinstance(value, float):
        raise AmountFormatError(
            f"{where}: float is not accepted; pass a string or Decimal"
        )
    if isinstance(value, int):
        return Decimal(value)
    if not isinstance(value, str):
        raise AmountFormatError(f"{where}: unsupported type {type(value).__name__}")

    s = value.strip()
    if not s:
        raise AmountFormatError(f"{where}: empty")
    if "(" in s or ")" in s:
        raise AmountFormatError(
            f"{where}: parenthesised negative {s!r} requires manual normalisation"
        )
    s = s.replace(",", "").replace("−", "-").replace("–", "-")
    if not _AMOUNT_RE.match(s):
        raise AmountFormatError(
            f"{where}: {value!r} is not an explicitly signed amount"
        )
    return Decimal(s)


def try_parse_amount(value: object, where: str = "amount"):
    """Non-raising form for the extraction boundary.

    Returns ``(Decimal, None)`` on success or ``(None, message)`` on failure."""
    try:
        return parse_amount(value, where), None
    except AmountFormatError as exc:
        return None, str(exc)


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AgreementLocator:
    section: str
    defined_term: str = ""
    clause_path: str = ""

    def describe(self) -> str:
        parts = [p for p in (self.section, self.defined_term, self.clause_path) if p]
        return " / ".join(parts)


@dataclass(frozen=True)
class RowLocator:
    row_index: int
    row_label: str = ""

    def describe(self) -> str:
        suffix = f" ({self.row_label})" if self.row_label else ""
        return f"row {self.row_index}{suffix}"


Locator = Union[AgreementLocator, RowLocator]


@dataclass(frozen=True)
class Anchor:
    """A claim about where a quoted fact came from.

    ``status`` is written only by ``anchors.verify_anchor`` -- never by the
    extraction layer.  An extractor's own assertion about provenance carries no
    weight until Python has re-found the quote in the source document.
    """

    doc_id: str
    quote: str
    doc_sha256: str = ""
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    locator: Optional[Locator] = None
    status: AnchorStatus = AnchorStatus.NOT_VERIFIED

    @property
    def usable(self) -> bool:
        return self.status in (
            AnchorStatus.VERIFIED,
            AnchorStatus.REPAIRED,
            AnchorStatus.AMBIGUOUS,
        )

    def describe(self) -> str:
        loc = self.locator.describe() if self.locator else self.doc_id
        return f"{loc} [{self.status.value}]"


# ---------------------------------------------------------------------------
# Agreement side
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Condition:
    type: ConditionType
    quote: str
    anchor: Anchor
    value: Optional[str] = None


@dataclass(frozen=True)
class PermittedCategory:
    category_id: str
    label: str
    definition_quote: str
    anchor: Anchor
    cap_group_id: Optional[str] = None
    conditions: tuple[Condition, ...] = ()
    permits_negative: Optional[bool] = None


@dataclass(frozen=True)
class CapGroup:
    cap_group_id: str
    member_category_ids: tuple[str, ...]
    cap_type: CapType
    cap_base: CapBase
    base_quote: str
    anchor: Anchor
    cap_value: Optional[Decimal] = None  # fraction when PERCENT_OF_BASE


@dataclass(frozen=True)
class UnmodelledCondition:
    category_id: str
    text: str
    anchor: Anchor


@dataclass(frozen=True)
class AgreementRuleSet:
    agreement_id: str
    defined_term_name: str
    base_metric: str
    base_metric_anchor: Anchor
    permitted_categories: tuple[PermittedCategory, ...]
    cap_groups: tuple[CapGroup, ...] = ()
    exclusions: tuple[str, ...] = ()
    unmodelled_conditions: tuple[UnmodelledCondition, ...] = ()
    notes: str = ""

    def category(self, category_id: str) -> Optional[PermittedCategory]:
        for c in self.permitted_categories:
            if c.category_id == category_id:
                return c
        return None

    def cap_group(self, cap_group_id: str) -> Optional[CapGroup]:
        for g in self.cap_groups:
            if g.cap_group_id == cap_group_id:
                return g
        return None


# ---------------------------------------------------------------------------
# Borrower side
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LineItem:
    line_id: str
    row_index: int
    raw_description: str
    amount: Decimal                 # signed as presented
    presentation: Presentation
    anchor: Anchor
    category_id: str                # a real id, or UNMATCHED / NOT_PERMITTED
    justification_quote: str = ""
    justification_anchor: Optional[Anchor] = None
    confidence: Confidence = Confidence.MEDIUM
    reasoning: str = ""             # for the human; never parsed
    realisation_period_months: Optional[int] = None
    is_cash: Optional[bool] = None
    candidate_category_id: Optional[str] = None  # best guess when UNMATCHED

    @property
    def sign_agrees(self) -> bool:
        if self.presentation is Presentation.ADDITION:
            return self.amount >= 0
        return self.amount <= 0


@dataclass(frozen=True)
class ReconciliationExtract:
    borrower: str
    period: str
    currency: str
    scale_declared: Scale
    sign_convention_declared: SignConvention
    starting_metric_label: str
    starting_metric_amount: Decimal
    starting_metric_anchor: Anchor
    line_items: tuple[LineItem, ...]
    stated_adjusted_ebitda: Decimal
    stated_anchor: Anchor
    scale_anchor: Optional[Anchor] = None
    sign_convention_anchor: Optional[Anchor] = None


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Flag:
    code: str
    severity: Severity
    message: str
    subject: str = ""


@dataclass(frozen=True)
class LineResult:
    line_id: str
    raw_description: str
    amount: Decimal
    category_id: str
    verdict: LineVerdict
    effect: Effect
    condition_outcome: ConditionOutcome
    cap_group_id: Optional[str] = None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class GroupScenario:
    cap_group_id: str
    cap: Optional[Decimal]      # None means uncapped
    included: Decimal
    allowed: Decimal
    disallowed: Decimal


@dataclass(frozen=True)
class Scenario:
    name: str                   # POINT | LOW | HIGH
    base: Decimal
    groups: tuple[GroupScenario, ...]
    ebitda: Decimal


@dataclass(frozen=True)
class DeltaDecomposition:
    claimed: Decimal
    recomputed: Decimal
    delta: Decimal              # claimed - recomputed; may be negative
    disallowed_total: Decimal   # >= 0
    excluded_sum: Decimal       # signed
    review_sum: Decimal         # signed
    residual: Decimal           # must be exactly 0


@dataclass(frozen=True)
class Recomputation:
    point: Scenario
    low: Scenario
    high: Scenario
    decomposition: DeltaDecomposition
    lines: tuple[LineResult, ...]

    @property
    def covenant_ebitda(self) -> Decimal:
        return self.point.ebitda


@dataclass(frozen=True)
class RunResult:
    verdict: RunVerdict
    flags: tuple[Flag, ...]
    recomputation: Optional[Recomputation]
    lines: tuple[LineResult, ...]
    notes: tuple[str, ...] = ()

    def flags_of(self, severity: Severity) -> tuple[Flag, ...]:
        return tuple(f for f in self.flags if f.severity is severity)

    @property
    def blocked(self) -> bool:
        return any(f.severity is Severity.BLOCKING for f in self.flags)
