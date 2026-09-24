from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256

import pytest
from sqlalchemy import select

from invoice_manager.application.client_service import ClientService
from invoice_manager.application.invoice_service import InvoiceItemData, InvoiceService
from invoice_manager.application.service_item_service import ServiceItemService
from invoice_manager.config import AppPaths
from invoice_manager.persistence.clock import utc_now
from invoice_manager.persistence.models import (
    AuditEvent,
    BusinessProfile,
    CreditNoteItem,
    Document,
    Invoice,
    NumberSequence,
    Payment,
)


def test_clients_services_and_invoice_snapshots(session) -> None:
    clients = ClientService()
    services = ServiceItemService()
    invoices = InvoiceService()
    client = clients.create(session, display_name="Snapshot Client", email="a@example.com")
    item = services.create(
        session, code="WEB", name="Website", unit_price_cents=10000, taxable=True
    )
    business = BusinessProfile(
        business_name="Alex Gillam",
        abn="12345678901",
        email="business@example.com",
        gst_registered=True,
        gst_rate=Decimal("0.1"),
    )
    session.add(business)
    session.flush()
    draft = invoices.create_draft(
        session,
        client,
        [
            InvoiceItemData(
                description=item.name,
                quantity=2,
                unit_price_cents=item.unit_price_cents,
                service_item_id=item.id,
                service_code=item.code,
                taxable=item.taxable,
                gst_rate=business.gst_rate,
            ),
            InvoiceItemData(description="Custom", quantity=1, unit_price_cents=500, taxable=False),
        ],
        invoice_date=date(2026, 6, 1),
        due_date=date(2026, 6, 15),
        business=business,
    )
    assert draft.total_cents == 22500
    invoices.issue(session, draft)
    session.commit()
    client.display_name = "Changed client"
    item.name = "Changed service"
    session.commit()
    session.refresh(draft)
    assert draft.client_name_snapshot == "Snapshot Client"
    assert draft.items[0].description == "Website"
    with pytest.raises(ValueError, match="immutable"):
        invoices.save_draft(session, draft, client, [])


def test_save_draft_omitted_fields_preserve_existing_values(session) -> None:
    clients = ClientService()
    invoices = InvoiceService()
    client = clients.create(session, display_name="Notes Client")
    business = BusinessProfile(
        business_name="Notes Business",
        gst_registered=False,
        gst_rate=Decimal("0"),
    )
    session.add(business)
    session.flush()
    draft = invoices.create_draft(
        session,
        client,
        [InvoiceItemData(description="Work", quantity=1, unit_price_cents=100)],
        reference="REF-1",
        visible_notes="Visible note",
        internal_notes="Keep this note",
        business=business,
    )

    invoices.save_draft(
        session,
        draft,
        client,
        [InvoiceItemData(description="Updated work", quantity=1, unit_price_cents=200)],
        reference=draft.reference,
        visible_notes=draft.visible_notes,
    )

    assert draft.reference == "REF-1"
    assert draft.visible_notes == "Visible note"
    assert draft.internal_notes == "Keep this note"
    assert draft.business_name_snapshot == "Notes Business"

    invoices.save_draft(
        session,
        draft,
        client,
        [InvoiceItemData(description="Updated work", quantity=1, unit_price_cents=200)],
        reference="",
        visible_notes="",
        internal_notes="",
    )
    assert draft.reference == ""
    assert draft.visible_notes == ""
    assert draft.internal_notes == ""


def test_client_duplicate_merge_delete_and_rollup(session) -> None:
    service = ClientService()
    first = service.create(session, display_name="Same Person", email="same@example.com")
    with pytest.raises(ValueError, match="duplicate"):
        service.create(session, display_name="Same Person", email="same@example.com")
    second = service.create(session, display_name="Replacement")
    invoice = Invoice(
        invoice_date=date(2026, 1, 1),
        due_date=date.today() - timedelta(days=1),
        client_id=first.id,
        total_cents=100,
        subtotal_cents=100,
        client_name_snapshot=first.display_name,
        issued_at=utc_now(),
    )
    session.add(invoice)
    session.flush()
    service.merge(session, first, second)
    assert invoice.client_id == second.id
    assert first.active is False
    assert service.rollup(session, second).billed_cents == 100
    with pytest.raises(ValueError, match="referenced"):
        service.delete(session, second)
    assert session.scalar(select(AuditEvent).where(AuditEvent.entity_type == "client")) is not None


def test_invoice_corrections_and_registration(session) -> None:
    clients = ClientService()
    invoices = InvoiceService()
    client = clients.create(session, display_name="Corrections")
    external = invoices.register_external(session, client, "EXT-10", date(2026, 1, 1), 500)
    with pytest.raises(ValueError, match="already exists"):
        invoices.register_external(session, client, "EXT-10", date(2026, 1, 1), 500)
    invoices.cancel(session, external, "Entered in error")
    assert invoices.status(session, external).value == "Cancelled"
    note = invoices.create_credit_note(
        session,
        external,
        [InvoiceItemData(description="Correction", quantity=1, unit_price_cents=100)],
        "Refund",
    )
    assert note.total_cents == 100
    assert (
        session.scalar(select(CreditNoteItem).where(CreditNoteItem.credit_note_id == note.id))
        is not None
    )


def test_catalogue_inheritance_allows_false_and_zero(session) -> None:
    client = ClientService().create(session, display_name="Inheritance")
    service = ServiceItemService().create(
        session, name="Catalogue", unit_price_cents=500, taxable=True
    )
    invoice = InvoiceService().create_draft(
        session,
        client,
        [
            InvoiceItemData(
                description=None,
                quantity=1,
                unit_price_cents=0,
                service_item_id=service.id,
                taxable=False,
            )
        ],
    )
    assert invoice.items[0].unit_price_cents == 0
    assert invoice.items[0].taxable is False


def test_external_gst_split_and_terms_due_date(session) -> None:
    client = ClientService().create(
        session,
        display_name="External",
    )
    client.default_terms_days = 30
    business = BusinessProfile(gst_registered=True, gst_rate=Decimal("0.1"))
    session.add(business)
    session.flush()
    invoice = InvoiceService().register_external(
        session,
        client,
        "EXT-GST",
        date(2026, 1, 1),
        1100,
        business=business,
    )
    assert invoice.subtotal_cents == 1000
    assert invoice.gst_cents == 100
    assert invoice.due_date == date(2026, 1, 31)


def test_reissue_renders_document_without_reserving_number(session, tmp_path) -> None:
    client = ClientService().create(session, display_name="Reissue")
    service = InvoiceService()
    invoice = service.create_draft(session, client, [InvoiceItemData("Work", 1, 1000)])
    service.issue(session, invoice)
    before = session.scalar(
        select(NumberSequence.next_value).where(NumberSequence.sequence_type == "invoice")
    )
    path = tmp_path / "reissued.pdf"
    assert (
        service.reissue(session, invoice, "Requested copy", destination=path)
        == invoice.canonical_number
    )
    assert path.exists()
    assert (
        session.scalar(
            select(NumberSequence.next_value).where(NumberSequence.sequence_type == "invoice")
        )
        == before
    )
    document = session.scalar(select(Document).where(Document.entity_id == invoice.id))
    assert document is not None


def test_issue_persists_managed_invoice_document(session, tmp_path) -> None:
    paths = AppPaths.resolve(tmp_path)
    client = ClientService().create(session, display_name="Issued PDF")
    service = InvoiceService(paths=paths)
    invoice = service.create_draft(session, client, [InvoiceItemData("Work", 1, 1000)])

    service.issue(session, invoice)

    document = session.scalar(
        select(Document)
        .where(Document.entity_type == "invoice", Document.entity_id == invoice.id)
        .order_by(Document.created_at.desc())
    )
    assert document is not None
    assert document.managed_relative_path == f"documents/invoices/{invoice.canonical_number}.pdf"
    assert document.external_path is None
    assert document.mime_type == "application/pdf"
    path = paths.root / document.managed_relative_path
    assert path.is_file()
    assert paths.root.resolve() in path.resolve().parents
    assert document.sha256 == sha256(path.read_bytes()).hexdigest()


def test_reissue_rewrites_managed_document_without_reserving_number(session, tmp_path) -> None:
    paths = AppPaths.resolve(tmp_path)
    client = ClientService().create(session, display_name="Managed Reissue")
    service = InvoiceService(paths=paths)
    invoice = service.create_draft(session, client, [InvoiceItemData("Work", 1, 1000)])
    service.issue(session, invoice)
    before_sequence = session.scalar(
        select(NumberSequence.next_value).where(NumberSequence.sequence_type == "invoice")
    )
    first_document = session.scalar(
        select(Document)
        .where(Document.entity_type == "invoice", Document.entity_id == invoice.id)
        .order_by(Document.created_at.desc())
    )
    assert first_document is not None and first_document.managed_relative_path is not None
    path = paths.root / first_document.managed_relative_path
    first_bytes = path.read_bytes()

    assert service.reissue(session, invoice, "Requested copy") == invoice.canonical_number

    documents = list(
        session.scalars(
            select(Document)
            .where(Document.entity_type == "invoice", Document.entity_id == invoice.id)
            .order_by(Document.created_at)
        )
    )
    assert len(documents) == 2
    latest = documents[-1]
    assert latest.managed_relative_path == first_document.managed_relative_path
    assert path.read_bytes() != first_bytes
    assert latest.sha256 == sha256(path.read_bytes()).hexdigest()
    assert (
        session.scalar(
            select(NumberSequence.next_value).where(NumberSequence.sequence_type == "invoice")
        )
        == before_sequence
    )


def test_draft_delete_void_duplicate_and_credit_gst(session) -> None:
    clients = ClientService()
    invoices = InvoiceService()
    client = clients.create(session, display_name="Lifecycle")
    draft = invoices.create_draft(session, client, [InvoiceItemData("Line", 1, 100)])
    invoices.delete_draft(session, draft)
    session.flush()
    assert session.get(Invoice, draft.id) is None
    invoice = invoices.create_draft(
        session,
        client,
        [InvoiceItemData("Taxed", 1, 1000, taxable=True, gst_rate=Decimal("0.1"))],
    )
    invoices.issue(session, invoice)
    duplicate = invoices.duplicate_as_draft(session, invoice)
    assert duplicate.canonical_number is None
    assert len(duplicate.items) == 1
    assert (
        invoices.create_credit_note(
            session,
            invoice,
            [InvoiceItemData("Taxed", 1, 1000, taxable=True, gst_rate=Decimal("0.1"))],
            "Refund",
        ).gst_cents
        == 100
    )
    invoices.void(session, invoice, "Duplicate source")
    assert invoice.status_override == "Void"


def test_deleted_invoice_id_is_not_reused_for_audit_history(session) -> None:
    client = ClientService().create(session, display_name="Audit IDs")
    service = InvoiceService()
    first = service.create_draft(session, client, [InvoiceItemData("First", 1, 100)])
    first_id = first.id
    service.delete_draft(session, first)
    session.flush()

    second = service.create_draft(session, client, [InvoiceItemData("Second", 1, 100)])
    assert second.id > first_id
    service.save_draft(
        session,
        second,
        client,
        [InvoiceItemData("Second", 1, 100)],
    )
    session.flush()
    history = service.history(session, second)
    assert history
    assert all(event.entity_id == second.id for event in history)
    old_events = list(
        session.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_type == "invoice",
                AuditEvent.entity_id == first_id,
            )
        )
    )
    assert old_events


def test_rollup_tracks_paid_balance_and_overdue(session) -> None:
    client = ClientService().create(session, display_name="Rollup")
    invoice = Invoice(
        invoice_date=date.today() - timedelta(days=10),
        due_date=date.today() - timedelta(days=1),
        client_id=client.id,
        client_name_snapshot=client.display_name,
        subtotal_cents=1000,
        total_cents=1000,
        issued_at=utc_now(),
    )
    session.add(invoice)
    session.flush()
    session.add(Payment(invoice_id=invoice.id, amount_cents=400))
    session.flush()
    rollup = ClientService().rollup(session, client)
    assert rollup.billed_cents == 1000
    assert rollup.paid_cents == 400
    assert rollup.balance_cents == 600
    assert rollup.overdue_cents == 600


def test_rollup_excludes_drafts_and_cancelled_or_voided_invoices(session) -> None:
    clients = ClientService()
    invoices = InvoiceService()
    client = clients.create(session, display_name="Issued Only")
    issued_date = date.today() - timedelta(days=5)
    issued = Invoice(
        invoice_date=issued_date,
        due_date=date.today() - timedelta(days=1),
        client_id=client.id,
        client_name_snapshot=client.display_name,
        subtotal_cents=1000,
        total_cents=1000,
        issued_at=utc_now(),
    )
    draft = Invoice(
        invoice_date=date.today(),
        due_date=date.today(),
        client_id=client.id,
        client_name_snapshot=client.display_name,
        subtotal_cents=2000,
        total_cents=2000,
    )
    voided = Invoice(
        invoice_date=date.today(),
        due_date=date.today() - timedelta(days=1),
        client_id=client.id,
        client_name_snapshot=client.display_name,
        subtotal_cents=3000,
        total_cents=3000,
        issued_at=utc_now(),
    )
    session.add_all([issued, draft, voided])
    session.flush()
    invoices.void(session, voided, "entered in error")

    rollup = clients.rollup(session, client)

    assert rollup.invoice_count == 1
    assert rollup.billed_cents == 1000
    assert rollup.paid_cents == 0
    assert rollup.balance_cents == 1000
    assert rollup.overdue_cents == 1000
    assert rollup.last_invoice_date == issued_date


def test_deactivated_service_stays_valid_on_invoice_snapshot(session) -> None:
    client = ClientService().create(session, display_name="Catalogue")
    catalogue = ServiceItemService().create(session, code="KEEP", name="Keep", unit_price_cents=100)
    invoice = InvoiceService().create_draft(
        session,
        client,
        [InvoiceItemData(None, 1, None, service_item_id=catalogue.id)],
    )
    ServiceItemService().set_active(session, catalogue, False)
    assert ServiceItemService().list(session, active_only=True) == []
    assert invoice.items[0].service_item_id == catalogue.id
    assert invoice.items[0].description == "Keep"


def test_issued_invoice_mutations_raise_at_service_boundary(session) -> None:
    client = ClientService().create(session, display_name="Immutable")
    service = InvoiceService()
    invoice = service.create_draft(session, client, [InvoiceItemData("Work", 1, 100)])
    service.issue(session, invoice)
    with pytest.raises(ValueError, match="immutable"):
        service.save_draft(session, invoice, client, [InvoiceItemData("Changed", 1, 200)])
    with pytest.raises(ValueError, match="immutable"):
        service.delete_draft(session, invoice)
