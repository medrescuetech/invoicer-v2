"""Derived invoice lifecycle statuses."""

from __future__ import annotations

from datetime import date
from enum import StrEnum


class InvoiceStatus(StrEnum):
    DRAFT = "Draft"
    ISSUED = "Issued"
    PART_PAID = "Part Paid"
    PAID = "Paid"
    OVERDUE = "Overdue"
    CREDITED = "Credited"
    CANCELLED = "Cancelled"
    VOID = "Void"


def derive_status(
    *,
    total_cents: int,
    issued: bool = True,
    payment_cents: int = 0,
    credit_cents: int = 0,
    due_date: date | None = None,
    today: date | None = None,
    status_override: str | None = None,
) -> InvoiceStatus:
    if status_override in (InvoiceStatus.CANCELLED, InvoiceStatus.VOID):
        return InvoiceStatus(status_override)
    if status_override:
        raise ValueError("only Cancelled and Void may be stored overrides")
    if not issued:
        return InvoiceStatus.DRAFT
    balance = total_cents - payment_cents - credit_cents
    if balance <= 0:
        return (
            InvoiceStatus.CREDITED
            if credit_cents > 0 and payment_cents == 0
            else InvoiceStatus.PAID
        )
    if due_date is not None and due_date < (today or date.today()):
        return InvoiceStatus.OVERDUE
    if payment_cents > 0 or credit_cents > 0:
        return InvoiceStatus.PART_PAID
    return InvoiceStatus.ISSUED
