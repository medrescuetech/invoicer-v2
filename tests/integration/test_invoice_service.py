from datetime import date, timedelta
from decimal import Decimal

import pytest

from invoice_manager.application.invoice_service import InvoiceService, InvoiceServiceError
from invoice_manager.domain.statuses import InvoiceStatus
from invoice_manager.infrastructure.audit import AuditService
from invoice_manager.persistence.database import Database
from invoice_manager.persistence.repositories import (
    AuditRepository,
    ClientRepository,
    InvoiceRepository,
    PaymentRepository,
    SettingRepository,
)


@pytest.fixture
def invoice_deps(tmp_path):
    db = Database(tmp_path / "test.sqlite3")
    db.create_schema()
    session = db.new_session()
    try:
        client_repo = ClientRepository(session)
        client = client_repo.create(name="Acme Corp")
        setting_repo = SettingRepository(session)
        setting_repo.set("next_invoice_number", "5")
        audit = AuditService(AuditRepository(session))
        service = InvoiceService(
            invoice_repo=InvoiceRepository(session),
            client_repo=client_repo,
            payment_repo=PaymentRepository(session),
            setting_repo=setting_repo,
            audit=audit,
            gst_rate=Decimal("0.10"),
            payment_terms_days=7,
        )
        yield service, client, session
        session.commit()
    finally:
        session.close()
        db.engine.dispose()


def test_create_draft(invoice_deps):
    service, client, session = invoice_deps
    inv = service.create_draft(client.id)
    assert inv.is_draft is True
    assert inv.number == "DRAFT"
    assert inv.status == InvoiceStatus.DRAFT.value


def test_create_custom_draft_without_saved_client(invoice_deps):
    service, _client, _session = invoice_deps
    inv = service.create_custom_draft("One-off Customer", "1 Custom Street")
    assert inv.client_id is None
    assert inv.client_name == "One-off Customer"
    assert inv.client_address == "1 Custom Street"
    assert inv.is_draft is True


def test_create_custom_draft_requires_name(invoice_deps):
    service, _client, _session = invoice_deps
    with pytest.raises(InvoiceServiceError):
        service.create_custom_draft("  ")


def test_add_line_recalculates_totals(invoice_deps):
    service, client, session = invoice_deps
    inv = service.create_draft(client.id)
    service.add_line(inv, "Consulting", 2, 10000, taxable=True)
    session.refresh(inv)
    assert inv.subtotal_cents == 20000
    assert inv.gst_cents == 2000
    assert inv.total_cents == 22000


def test_cannot_edit_issued_invoice(invoice_deps):
    service, client, session = invoice_deps
    inv = service.create_draft(client.id)
    service.add_line(inv, "Work", 1, 10000)
    service.issue(inv)
    with pytest.raises(InvoiceServiceError):
        service.add_line(inv, "Extra", 1, 5000)


def test_issue_assigns_number(invoice_deps):
    service, client, session = invoice_deps
    inv = service.create_draft(client.id)
    service.add_line(inv, "Work", 1, 10000)
    service.issue(inv)
    assert inv.number == "INV-0005"
    assert inv.is_draft is False


def test_status_paid_after_payment(invoice_deps):
    service, client, session = invoice_deps
    inv = service.create_draft(client.id)
    service.add_line(inv, "Work", 1, 10000)
    service.issue(inv)
    service._payment_repo.create(
        invoice_id=inv.id,
        amount_cents=inv.total_cents,
        date=date.today(),
        method="cash",
    )
    service.recalc(inv)
    assert inv.status == InvoiceStatus.PAID.value


def test_cancel_invoice(invoice_deps):
    service, client, session = invoice_deps
    inv = service.create_draft(client.id)
    service.add_line(inv, "Work", 1, 10000)
    service.issue(inv)
    service.cancel(inv, "Client requested")
    assert inv.is_cancelled is True
    assert inv.status == InvoiceStatus.CANCELLED.value


def test_mark_duplicate_sets_terminal_zero_balance_status(invoice_deps):
    service, client, _session = invoice_deps
    inv = service.create_draft(client.id)
    service.add_line(inv, "Duplicate work", 1, 10000)
    service.issue(inv)
    service.mark_duplicate(inv, "Entered twice")
    assert inv.status == InvoiceStatus.DUPLICATE.value


def test_void_invoice(invoice_deps):
    service, client, session = invoice_deps
    inv = service.create_draft(client.id)
    service.add_line(inv, "Work", 1, 10000)
    service.issue(inv)
    service.void(inv, "Mistake")
    assert inv.is_void is True
    assert inv.status == InvoiceStatus.VOID.value


def test_due_date_defaults_to_terms(invoice_deps):
    service, client, session = invoice_deps
    today = date.today()
    inv = service.create_draft(client.id, invoice_date=today)
    assert inv.due_date == today + timedelta(days=7)


def test_update_issued_invoice_recalculates_totals(invoice_deps):
    service, client, session = invoice_deps
    inv = service.create_draft(client.id)
    service.add_line(inv, "Work", 1, 10000)
    service.issue(inv)
    service.update_invoice(
        inv,
        inv.issue_date,
        inv.due_date,
        None,
        [
            {
                "description": "More work",
                "quantity": 2,
                "unit_price_cents": 10000,
                "discount_cents": 0,
                "taxable": True,
            }
        ],
    )
    assert inv.subtotal_cents == 20000
    assert inv.gst_cents == 2000
    assert inv.total_cents == 22000


def test_update_invoice_with_payments_updates_status(invoice_deps):
    service, client, session = invoice_deps
    inv = service.create_draft(client.id)
    service.add_line(inv, "Work", 1, 10000)
    service.issue(inv)
    service._payment_repo.create(
        invoice_id=inv.id,
        amount_cents=11000,
        date=date.today(),
        method="cash",
    )
    service.update_invoice(
        inv,
        inv.issue_date,
        inv.due_date,
        None,
        [
            {
                "description": "Work",
                "quantity": 1,
                "unit_price_cents": 20000,
                "discount_cents": 0,
                "taxable": True,
            }
        ],
    )
    assert inv.status == InvoiceStatus.PART_PAID.value


def test_cannot_update_void_invoice(invoice_deps):
    service, client, session = invoice_deps
    inv = service.create_draft(client.id)
    service.add_line(inv, "Work", 1, 10000)
    service.issue(inv)
    service.void(inv, "Mistake")
    with pytest.raises(InvoiceServiceError):
        service.update_invoice(
            inv,
            inv.issue_date,
            inv.due_date,
            None,
            [
                {
                    "description": "Work",
                    "quantity": 1,
                    "unit_price_cents": 5000,
                    "discount_cents": 0,
                    "taxable": True,
                }
            ],
        )


def test_manual_invoice_with_lines_is_itemised_and_recalculated(invoice_deps):
    service, _client, session = invoice_deps
    inv = service.record_manual_invoice(
        number="INV-0042",
        client_name="Acme Corp",
        client_address=None,
        issue_date=date.today(),
        due_date=date.today() + timedelta(days=7),
        subtotal_cents=1,
        gst_cents=1,
        total_cents=2,
        lines=[
            {
                "description": "Manual consulting",
                "quantity": 2,
                "unit_price_cents": 10000,
                "discount_cents": 1000,
                "taxable": True,
            },
            {
                "description": "Expenses",
                "quantity": 1,
                "unit_price_cents": 5000,
                "discount_cents": 0,
                "taxable": False,
            },
        ],
    )
    session.flush()
    assert len(inv.items) == 2
    assert inv.items[0].description == "Manual consulting"
    assert inv.subtotal_cents == 24000
    assert inv.gst_cents == 1900
    assert inv.total_cents == 25900
    assert inv.is_draft is False


def test_credit_note_reduces_balance_and_status(invoice_deps):
    service, client, session = invoice_deps
    inv = service.create_draft(client.id)
    service.add_line(inv, "Work", 1, 10000)
    service.issue(inv)
    service.add_credit_note(inv, 11000, "Goodwill", date.today())
    session.refresh(inv)
    assert inv.status == InvoiceStatus.PAID.value
    balance = service._balance(inv).cents
    assert balance == 0


def test_cannot_credit_void_or_draft_invoice(invoice_deps):
    service, client, session = invoice_deps
    inv = service.create_draft(client.id)
    service.add_line(inv, "Work", 1, 10000)
    service.issue(inv)
    service.void(inv, "Mistake")
    with pytest.raises(InvoiceServiceError):
        service.add_credit_note(inv, 1000, "Too late", date.today())


def test_retract_and_reissue_preserves_number(invoice_deps):
    service, client, session = invoice_deps
    inv = service.create_draft(client.id)
    service.add_line(inv, "Work", 1, 10000)
    service.issue(inv)
    original = inv.number
    service.retract(inv)
    assert inv.is_draft is True
    assert inv.number == original
    service.reissue(inv)
    assert inv.is_draft is False
    assert inv.number == original


def test_cannot_retract_invoice_with_payment(invoice_deps):
    service, client, session = invoice_deps
    client2 = service._client_repo.create(name="Client 2")
    inv = service.create_draft(client2.id)
    service.add_line(inv, "Work", 1, 10000)
    service.issue(inv)
    service._payment_repo.create(invoice_id=inv.id, amount_cents=1000, date=date.today(), method="Bank")
    session.refresh(inv)
    with pytest.raises(InvoiceServiceError):
        service.retract(inv)


def test_quote_lifecycle_and_conversion(invoice_deps):
    service, client, session = invoice_deps
    quote = service.create_draft(client.id, due_date=None)
    service.add_line(quote, "Quote work", 2, 5000)
    service.issue_quote(quote)
    assert quote.is_quote
    assert quote.number == "QTE-0001"
    assert quote.status == InvoiceStatus.QUOTED.value
    assert quote.due_date is None
    service.convert_quote_to_invoice(quote)
    assert not quote.is_quote
    assert quote.number.startswith("INV")
    assert quote.due_date is not None
    assert quote.status in {InvoiceStatus.ISSUED.value, InvoiceStatus.PAID.value}


def test_invoice_na_due_date_preserved(invoice_deps):
    service, client, session = invoice_deps
    inv = service.create_draft(client.id, due_date=None)
    service.add_line(inv, "Work", 1, 10000)
    service.issue(inv)
    assert inv.due_date is None
    assert inv.status == InvoiceStatus.ISSUED.value
