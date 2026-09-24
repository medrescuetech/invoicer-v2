from datetime import date

import pytest

from invoice_manager.domain.statuses import InvoiceStatus, derive_status

TODAY = date(2026, 6, 25)


def test_full_invoice_status_table() -> None:
    assert derive_status(total_cents=100, issued=False) == InvoiceStatus.DRAFT
    assert (
        derive_status(total_cents=100, due_date=date(2026, 6, 26), today=TODAY)
        == InvoiceStatus.ISSUED
    )
    assert (
        derive_status(total_cents=100, payment_cents=25, due_date=date(2026, 6, 26), today=TODAY)
        == InvoiceStatus.PART_PAID
    )
    assert (
        derive_status(total_cents=100, payment_cents=25, due_date=date(2026, 6, 24), today=TODAY)
        == InvoiceStatus.OVERDUE
    )
    assert derive_status(total_cents=100, payment_cents=100, today=TODAY) == InvoiceStatus.PAID
    assert (
        derive_status(total_cents=100, due_date=date(2026, 6, 24), today=TODAY)
        == InvoiceStatus.OVERDUE
    )
    assert derive_status(total_cents=100, credit_cents=100, today=TODAY) == InvoiceStatus.CREDITED
    assert derive_status(total_cents=100, payment_cents=50, credit_cents=50) == InvoiceStatus.PAID
    assert derive_status(total_cents=100, status_override="Cancelled") == InvoiceStatus.CANCELLED
    assert derive_status(total_cents=100, status_override="Void") == InvoiceStatus.VOID


def test_reversal_restores_issued_state() -> None:
    assert derive_status(total_cents=100, payment_cents=100) == InvoiceStatus.PAID
    assert derive_status(total_cents=100) == InvoiceStatus.ISSUED


def test_only_allowed_overrides_are_stored() -> None:
    with pytest.raises(ValueError):
        derive_status(total_cents=100, status_override="Paid")
    with pytest.raises(ValueError):
        derive_status(total_cents=100, status_override="Draft")
