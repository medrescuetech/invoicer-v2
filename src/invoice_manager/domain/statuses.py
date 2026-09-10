"""Invoice lifecycle status rules."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any


class InvoiceStatus(StrEnum):
    DRAFT = "draft"
    QUOTED = "quoted"
    ISSUED = "issued"
    PART_PAID = "part_paid"
    PAID = "paid"
    OVERDUE = "overdue"
    CREDITED = "credited"
    DUPLICATE = "duplicate"
    CANCELLED = "cancelled"
    VOID = "void"


def invoice_balance_cents(invoice: Any) -> int:
    if invoice.status in {InvoiceStatus.PAID.value, InvoiceStatus.DUPLICATE.value}:
        return 0
    paid = sum(int(payment.amount_cents) for payment in invoice.payments if not payment.is_reversed)
    credits = sum(int(credit.amount_cents) for credit in invoice.credits)
    return max(0, int(invoice.total_cents) - paid - credits)


def derive_invoice_status(
    invoice_total_cents: int,
    balance_cents: int,
    due_date: date | str | None,
    is_cancelled: bool = False,
    is_void: bool = False,
    is_quote: bool = False,
    today: date | None = None,
) -> InvoiceStatus:
    """Derive the display status from financial facts only.

    The order of precedence is: void > cancelled > paid/credited > part paid >
    overdue > issued > quoted > draft.
    Quotes are treated as a distinct status unless they have been voided or
    cancelled.
    """
    if today is None:
        today = date.today()
    if is_void:
        return InvoiceStatus.VOID
    if is_cancelled:
        return InvoiceStatus.CANCELLED
    if is_quote:
        return InvoiceStatus.QUOTED
    if balance_cents <= 0:
        if invoice_total_cents <= 0:
            return InvoiceStatus.CANCELLED
        return InvoiceStatus.PAID
    # balance > 0
    if balance_cents < invoice_total_cents:
        return InvoiceStatus.PART_PAID
    due = _to_date(due_date)
    if due is not None and due < today:
        return InvoiceStatus.OVERDUE
    return InvoiceStatus.ISSUED


def _to_date(value: date | str | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    from invoice_manager.domain.validation import parse_date

    parsed = parse_date(str(value))
    return parsed
