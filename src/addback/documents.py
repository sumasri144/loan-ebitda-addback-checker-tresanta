"""Document loading, normalisation and hashing.

Normalisation happens exactly once, here, and every downstream character
offset and quote comparison is against the normalised form.  Doing it in one
place is what makes the anchor verifier trustworthy: if the extractor's quote
and the source text were normalised differently, a correct quote could fail to
match and a wrong one could pass.

All whitespace runs -- including newlines -- collapse to a single space, so a
quote that spans a line break in the source still matches.  Row positions are
carried separately in ``RowLocator`` and never derived from offsets.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

_WHITESPACE = re.compile(r"\s+")

# Typographic characters that appear in agreements and would otherwise cause a
# verbatim quote to miss.  Deliberately a small, explicit table rather than
# NFKC, which would also rewrite things we want left alone (e.g. fractions).
_PUNCTUATION = {
    "‘": "'",
    "’": "'",
    "‚": "'",
    "‛": "'",
    "“": '"',
    "”": '"',
    "„": '"',
    "–": "-",
    "—": "-",
    "―": "-",
    "−": "-",
    " ": " ",
    "…": "...",
}


def normalise(text: str) -> str:
    """Return the canonical form used for hashing, offsets and quote matching."""
    text = unicodedata.normalize("NFC", text)
    for src, dst in _PUNCTUATION.items():
        text = text.replace(src, dst)
    return _WHITESPACE.sub(" ", text).strip()


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class NormalisedDoc:
    doc_id: str
    text: str          # normalised
    sha256: str        # of the normalised text
    raw_text: str
    source_path: str = ""

    def count(self, quote: str) -> int:
        needle = normalise(quote)
        if not needle:
            return 0
        total = 0
        start = 0
        while True:
            found = self.text.find(needle, start)
            if found < 0:
                return total
            total += 1
            start = found + 1          # overlapping occurrences still count

    def find_all(self, quote: str, limit: int = 8) -> list[tuple[int, int]]:
        needle = normalise(quote)
        if not needle:
            return []
        spans: list[tuple[int, int]] = []
        start = 0
        while len(spans) < limit:
            found = self.text.find(needle, start)
            if found < 0:
                break
            spans.append((found, found + len(needle)))
            start = found + 1
        return spans


def from_text(doc_id: str, raw_text: str, source_path: str = "") -> NormalisedDoc:
    normalised = normalise(raw_text)
    return NormalisedDoc(
        doc_id=doc_id,
        text=normalised,
        sha256=sha256_of(normalised),
        raw_text=raw_text,
        source_path=source_path,
    )


def load(path: str | Path, doc_id: str | None = None) -> NormalisedDoc:
    p = Path(path)
    raw = p.read_text(encoding="utf-8")
    return from_text(doc_id or p.stem, raw, source_path=str(p))


class DocumentSet:
    """The documents a single run is allowed to cite."""

    def __init__(self, docs: dict[str, NormalisedDoc] | None = None) -> None:
        self._docs: dict[str, NormalisedDoc] = dict(docs or {})

    def add(self, doc: NormalisedDoc) -> None:
        self._docs[doc.doc_id] = doc

    def get(self, doc_id: str) -> NormalisedDoc | None:
        return self._docs.get(doc_id)

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._docs))

    def hashes(self) -> dict[str, str]:
        return {doc_id: d.sha256 for doc_id, d in sorted(self._docs.items())}
