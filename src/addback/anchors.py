"""Evidence verification.

This is the control that catches a fabricated citation, and it involves no
model judgement at all: Python re-locates the quoted text in the source
document and sets the anchor's status from what it finds.

    found at the stated offsets      -> VERIFIED
    found exactly once, offsets off  -> REPAIRED   (offsets corrected)
    found more than once             -> AMBIGUOUS  (usable, flagged)
    not found                        -> INVALID    (the fact is discarded)

What this does *not* do is check interpretation.  A clause quoted correctly but
read wrongly passes verification cleanly.  That residual risk is handled
elsewhere, by making the cap base a mandatory human confirmation.
"""

from __future__ import annotations

from dataclasses import replace

from .documents import DocumentSet, normalise
from .models import Anchor, AnchorStatus


def verify_anchor(anchor: Anchor, docs: DocumentSet) -> Anchor:
    """Return a copy of ``anchor`` with ``status`` and offsets set by Python."""
    doc = docs.get(anchor.doc_id)
    if doc is None:
        return replace(anchor, status=AnchorStatus.INVALID)

    needle = normalise(anchor.quote)
    if not needle:
        return replace(anchor, status=AnchorStatus.INVALID)

    spans = doc.find_all(needle, limit=3)
    if not spans:
        return replace(anchor, status=AnchorStatus.INVALID, doc_sha256=doc.sha256)

    if len(spans) > 1:
        # Ambiguous evidence is still evidence, but a reviewer has to pick the
        # occurrence; we point at the first and say so.
        start, end = spans[0]
        return replace(
            anchor,
            status=AnchorStatus.AMBIGUOUS,
            char_start=start,
            char_end=end,
            doc_sha256=doc.sha256,
        )

    start, end = spans[0]
    if anchor.char_start is None and anchor.char_end is None:
        # Offsets are optional.  Nothing was claimed, so nothing was repaired:
        # a unique match on the quote alone is full verification.  Treating
        # this as REPAIRED would bury the genuine wrong-offset signal under
        # every anchor that simply omitted them.
        status = AnchorStatus.VERIFIED
    elif anchor.char_start == start and anchor.char_end == end:
        status = AnchorStatus.VERIFIED
    else:
        status = AnchorStatus.REPAIRED
    return replace(
        anchor,
        status=status,
        char_start=start,
        char_end=end,
        doc_sha256=doc.sha256,
    )


def verify_optional(anchor: Anchor | None, docs: DocumentSet) -> Anchor | None:
    return None if anchor is None else verify_anchor(anchor, docs)


def summarise(anchors: list[Anchor]) -> dict[str, int]:
    """Counts by status, for the run manifest."""
    counts = {s.value: 0 for s in AnchorStatus}
    for a in anchors:
        counts[a.status.value] += 1
    return counts
