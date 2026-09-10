"""Document numbering rules for invoices, receipts, and credit notes."""

from __future__ import annotations

import re
from collections.abc import Iterable

_PREFIXES = {
    "invoice": "INV",
    "quote": "QTE",
    "receipt": "RCT",
    "credit_note": "CN",
}


class NumberingService:
    """Reserve canonical document numbers sequentially.

    The canonical display form is ``PREFIX-0001``.  Internal records store the
    integer sequence number and prefix separately so numbers are never reused
    and can be rendered consistently.
    """

    def __init__(
        self,
        next_invoice: int = 1,
        next_quote: int = 1,
        next_receipt: int = 1,
        next_credit_note: int = 1,
    ) -> None:
        self._next = {
            "invoice": max(1, next_invoice),
            "quote": max(1, next_quote),
            "receipt": max(1, next_receipt),
            "credit_note": max(1, next_credit_note),
        }

    def reserve(self, doc_type: str) -> str:
        """Return the next canonical number for ``doc_type`` and advance."""
        prefix = _PREFIXES[doc_type]
        num = self._next[doc_type]
        self._next[doc_type] = num + 1
        return format_number(prefix, num)

    def peek(self, doc_type: str) -> str:
        """Return the next canonical number without advancing."""
        prefix = _PREFIXES[doc_type]
        return format_number(prefix, self._next[doc_type])

    def set_next(self, doc_type: str, value: int) -> None:
        """Set the next number to be reserved for ``doc_type``."""
        self._next[doc_type] = max(1, value)


class NumberInUseError(Exception):
    pass


def format_number(prefix: str, number: int, width: int = 4) -> str:
    """Canonical display form: ``PREFIX-0001``."""
    return f"{prefix}-{number:0{width}d}"


def parse_number(value: str) -> tuple[str, int] | None:
    """Parse ``PREFIX-0001`` or ``0001`` into (prefix, number).

    Returns None for unrecognised formats.
    """
    s = (value or "").strip().upper()
    if not s:
        return None
    # INV-0001, INV 0001, INV_0001
    m = re.match(r"^(INV|QTE|RCT|CN)[\s_-]*(\d+)$", s)
    if m:
        return m.group(1), int(m.group(2))
    # plain digits
    if re.match(r"^\d+$", s):
        return "", int(s)
    return None


def highest_used(prefix: str, used_numbers: Iterable[int]) -> int:
    """Return the highest used sequence number for a prefix, or 0."""
    nums = list(used_numbers)
    return max(nums) if nums else 0
