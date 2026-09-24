from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from hashlib import sha256
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from invoice_manager.application.audit import AuditService
from invoice_manager.application.numbering import NumberingService
from invoice_manager.config import AppPaths
from invoice_manager.documents.invoice_documents import InvoiceDocumentStore
from invoice_manager.documents.invoice_pdf import InvoicePDF
from invoice_manager.domain.invoice_calculations import calculate_invoice, calculate_line
from invoice_manager.domain.statuses import InvoiceStatus, derive_status
from invoice_manager.persistence.clock import utc_now
from invoice_manager.persistence.models import (
    AuditEvent,
    BusinessProfile,
    Client,
    CreditNote,
    CreditNoteItem,
    Document,
    Invoice,
    InvoiceItem,
    Payment,
    ServiceItem,
)


@dataclass(frozen=True)
class InvoiceItemData:
    description: str | None
    quantity: Decimal | str | int
    unit_price_cents: int | None
    unit: str | None = None
    service_item_id: int | None = None
    service_code: str = ""
    discount_type: str = "none"
    discount_value: Decimal | str | int = 0
    taxable: bool | None = None
    gst_rate: Decimal | str | int | None = None


def _snapshot_client(invoice: Invoice, client: Client) -> None:
    invoice.client_id = client.id
    invoice.client_name_snapshot = client.display_name
    invoice.client_abn_snapshot = client.abn
    invoice.client_contact_snapshot = client.contact_name
    invoice.client_email_snapshot = client.email
    invoice.client_phone_snapshot = client.phone
    invoice.client_address_snapshot = client.billing_address


def _snapshot_business(invoice: Invoice, business: BusinessProfile | None) -> None:
    if business is None:
        return
    invoice.business_name_snapshot = business.business_name
    invoice.business_abn_snapshot = business.abn
    invoice.business_address_snapshot = business.address
    invoice.business_phone_snapshot = business.phone
    invoice.business_email_snapshot = business.email
    invoice.bank_instructions_snapshot = business.bank_instructions
    invoice.gst_registered_snapshot = business.gst_registered
    invoice.gst_rate_snapshot = business.gst_rate


class InvoiceService:
    def __init__(
        self,
        numbering: NumberingService | None = None,
        audit: AuditService | None = None,
        *,
        paths: AppPaths | None = None,
        document_store: InvoiceDocumentStore | None = None,
    ) -> None:
        self.numbering = numbering or NumberingService()
        self.audit = audit or AuditService()
        self.document_store = document_store or InvoiceDocumentStore(paths or AppPaths.resolve())

    def _assert_draft(self, invoice: Invoice) -> None:
        if invoice.issued_at is not None or invoice.canonical_number is not None:
            raise ValueError("issued invoices are immutable")

    def _build_items(
        self, session: Session, invoice: Invoice, items: Iterable[InvoiceItemData]
    ) -> None:
        calculations = []
        values = list(items)
        if not values:
            raise ValueError("at least one invoice item is required")
        invoice.items.clear()
        for position, data in enumerate(values, 1):
            if data.service_item_id is not None:
                service = session.get(ServiceItem, data.service_item_id)
                if service is None:
                    raise ValueError("service item no longer exists")
                data = replace(
                    data,
                    description=data.description or service.name,
                    unit=data.unit or service.unit,
                    unit_price_cents=(
                        data.unit_price_cents
                        if data.unit_price_cents is not None
                        else service.unit_price_cents
                    ),
                    service_code=data.service_code or service.code,
                    taxable=data.taxable if data.taxable is not None else service.taxable,
                )
            if not data.description or not data.description.strip():
                raise ValueError("item description is required")
            if data.unit_price_cents is None:
                raise ValueError("item price is required")
            taxable = data.taxable if data.taxable is not None else False
            gst_rate = (
                data.gst_rate
                if data.gst_rate is not None
                else (invoice.gst_rate_snapshot or Decimal("0"))
            )
            calculation = calculate_line(
                data.quantity,
                data.unit_price_cents,
                discount_type=data.discount_type,
                discount_value=data.discount_value,
                taxable=taxable,
                gst_rate=gst_rate,
            )
            calculations.append(calculation)
            invoice.items.append(
                InvoiceItem(
                    position=position,
                    service_item_id=data.service_item_id,
                    service_code_snapshot=data.service_code,
                    description=data.description,
                    quantity_decimal=Decimal(str(data.quantity)),
                    unit=data.unit or "each",
                    unit_price_cents=data.unit_price_cents,
                    discount_type=data.discount_type,
                    discount_value=Decimal(str(data.discount_value)),
                    discount_cents=calculation.discount_cents,
                    taxable=taxable,
                    gst_rate_decimal=Decimal(str(gst_rate)),
                    subtotal_cents=calculation.subtotal_cents,
                    gst_cents=calculation.gst_cents,
                    total_cents=calculation.total_cents,
                )
            )
        totals = calculate_invoice(calculations)
        invoice.subtotal_cents = totals.subtotal_cents
        invoice.gst_cents = totals.gst_cents
        invoice.total_cents = totals.total_cents

    def create_draft(
        self,
        session: Session,
        client: Client,
        items: Iterable[InvoiceItemData],
        *,
        invoice_date: date | None = None,
        due_date: date | None = None,
        business: BusinessProfile | None = None,
        reference: str = "",
        visible_notes: str = "",
        internal_notes: str = "",
        created_by: int | None = None,
    ) -> Invoice:
        effective_invoice_date = invoice_date or date.today()
        invoice = Invoice(
            invoice_date=effective_invoice_date,
            due_date=due_date or effective_invoice_date + timedelta(days=client.default_terms_days),
            client_id=client.id,
            reference=reference,
            visible_notes=visible_notes,
            internal_notes=internal_notes,
            created_by=created_by,
        )
        _snapshot_client(invoice, client)
        _snapshot_business(invoice, business)
        self._build_items(session, invoice, items)
        session.add(invoice)
        session.flush()
        self.audit.record(
            session,
            action="create",
            entity_type="invoice",
            entity_id=invoice.id,
            summary="Created invoice draft",
            user_id=created_by,
        )
        return invoice

    def preview(
        self,
        session: Session,
        client: Client,
        items: Iterable[InvoiceItemData],
        *,
        invoice_date: date | None = None,
        due_date: date | None = None,
        business: BusinessProfile | None = None,
    ) -> Invoice:
        effective_date = invoice_date or date.today()
        invoice = Invoice(
            invoice_date=effective_date,
            due_date=due_date or effective_date + timedelta(days=client.default_terms_days),
        )
        _snapshot_client(invoice, client)
        _snapshot_business(invoice, business)
        self._build_items(session, invoice, items)
        return invoice

    def render_draft_preview(self, invoice: Invoice) -> Path:
        return self.document_store.render_draft_preview(invoice)

    def save_draft(
        self,
        session: Session,
        invoice: Invoice | None,
        client: Client,
        items: Iterable[InvoiceItemData],
        *,
        invoice_date: date | None = None,
        due_date: date | None = None,
        reference: str | None = None,
        visible_notes: str | None = None,
        internal_notes: str | None = None,
        business: BusinessProfile | None = None,
        user_id: int | None = None,
    ) -> Invoice:
        if invoice is None:
            return self.create_draft(
                session,
                client,
                items,
                invoice_date=invoice_date,
                due_date=due_date,
                reference=reference or "",
                visible_notes=visible_notes or "",
                internal_notes=internal_notes or "",
                business=business,
                created_by=user_id,
            )
        self._assert_draft(invoice)
        before = {"total_cents": invoice.total_cents, "reference": invoice.reference}
        _snapshot_client(invoice, client)
        _snapshot_business(invoice, business)
        if invoice_date is not None:
            invoice.invoice_date = invoice_date
        if due_date is not None:
            invoice.due_date = due_date
        if reference is not None:
            invoice.reference = reference
        if visible_notes is not None:
            invoice.visible_notes = visible_notes
        if internal_notes is not None:
            invoice.internal_notes = internal_notes
        self._build_items(session, invoice, items)
        invoice.updated_at = utc_now()
        self.audit.record(
            session,
            action="update",
            entity_type="invoice",
            entity_id=invoice.id,
            summary="Updated invoice draft",
            before=before,
            after={"total_cents": invoice.total_cents, "reference": invoice.reference},
            user_id=user_id,
        )
        return invoice

    def delete_draft(
        self, session: Session, invoice: Invoice, *, user_id: int | None = None
    ) -> None:
        self._assert_draft(invoice)
        session.delete(invoice)
        self.audit.record(
            session,
            action="delete",
            entity_type="invoice",
            entity_id=invoice.id,
            summary="Deleted invoice draft",
            user_id=user_id,
        )

    def issue(self, session: Session, invoice: Invoice, *, user_id: int | None = None) -> Invoice:
        self._assert_draft(invoice)
        if not invoice.items:
            raise ValueError("cannot issue an invoice without items")
        invoice.canonical_number = self.numbering.reserve(session, "invoice")
        invoice.issued_at = utc_now()
        invoice.status_override = None
        invoice.updated_at = invoice.issued_at
        output, digest = self.document_store.render(invoice)
        session.add(
            Document(
                entity_type="invoice",
                entity_id=invoice.id,
                document_type="invoice_pdf",
                managed_relative_path=self.document_store.relative_path(invoice.canonical_number),
                original_filename=output.name,
                sha256=digest,
                mime_type="application/pdf",
            )
        )
        session.flush()
        self.audit.record(
            session,
            action="issue",
            entity_type="invoice",
            entity_id=invoice.id,
            summary=f"Issued {invoice.canonical_number}",
            user_id=user_id,
        )
        return invoice

    def _payments(self, session: Session, invoice_id: int) -> int:
        return sum(
            payment.amount_cents
            for payment in session.scalars(
                select(Payment).where(Payment.invoice_id == invoice_id)
            ).all()
            if payment.reversed_at is None
        )

    def _credits(self, session: Session, invoice_id: int) -> int:
        return sum(
            credit.total_cents
            for credit in session.scalars(
                select(CreditNote).where(CreditNote.invoice_id == invoice_id)
            ).all()
            if not credit.voided
        )

    def status(
        self, session: Session, invoice: Invoice, *, today: date | None = None
    ) -> InvoiceStatus:
        return derive_status(
            total_cents=invoice.total_cents,
            issued=invoice.issued_at is not None,
            payment_cents=self._payments(session, invoice.id),
            credit_cents=self._credits(session, invoice.id),
            due_date=invoice.due_date,
            today=today,
            status_override=invoice.status_override,
        )

    def balance(self, session: Session, invoice: Invoice) -> int:
        return (
            invoice.total_cents
            - self._payments(session, invoice.id)
            - self._credits(session, invoice.id)
        )

    def cancel(
        self, session: Session, invoice: Invoice, reason: str, *, user_id: int | None = None
    ) -> None:
        if not reason.strip():
            raise ValueError("reason is required")
        if invoice.status_override == "Void":
            raise ValueError("void invoice cannot be cancelled")
        invoice.status_override = "Cancelled"
        invoice.correction_reason = reason
        invoice.cancelled_at = utc_now()
        self.audit.record(
            session,
            action="cancel",
            entity_type="invoice",
            entity_id=invoice.id,
            summary="Cancelled invoice",
            user_id=user_id,
            after={"reason": reason},
        )

    def void(
        self, session: Session, invoice: Invoice, reason: str, *, user_id: int | None = None
    ) -> None:
        if not reason.strip():
            raise ValueError("reason is required")
        if invoice.issued_at is None:
            raise ValueError("only issued invoices can be voided")
        invoice.status_override = "Void"
        invoice.correction_reason = reason
        invoice.voided_at = utc_now()
        self.audit.record(
            session,
            action="void",
            entity_type="invoice",
            entity_id=invoice.id,
            summary="Voided invoice",
            user_id=user_id,
            after={"reason": reason},
        )

    def duplicate_as_draft(
        self, session: Session, invoice: Invoice, *, user_id: int | None = None
    ) -> Invoice:
        items = [
            InvoiceItemData(
                description=item.description,
                quantity=item.quantity_decimal,
                unit_price_cents=item.unit_price_cents,
                unit=item.unit,
                service_item_id=item.service_item_id,
                service_code=item.service_code_snapshot,
                discount_type=item.discount_type,
                discount_value=item.discount_value,
                taxable=item.taxable,
                gst_rate=item.gst_rate_decimal,
            )
            for item in invoice.items
        ]
        client = session.get(Client, invoice.client_id)
        if client is None:
            raise ValueError("invoice client no longer exists")
        duplicate = self.create_draft(
            session,
            client,
            items,
            invoice_date=date.today(),
            due_date=invoice.due_date,
            reference=invoice.reference,
            visible_notes=invoice.visible_notes,
            internal_notes=invoice.internal_notes,
            created_by=user_id,
        )
        self.audit.record(
            session,
            action="duplicate",
            entity_type="invoice",
            entity_id=duplicate.id,
            summary=f"Duplicated invoice {invoice.canonical_number or invoice.id}",
            user_id=user_id,
        )
        return duplicate

    def reissue(
        self,
        session: Session,
        invoice: Invoice,
        reason: str,
        *,
        user_id: int | None = None,
        destination: Path | None = None,
        currency_symbol: str = "$",
    ) -> str:
        if invoice.issued_at is None or not invoice.canonical_number:
            raise ValueError("only issued invoices can be reissued")
        if not reason.strip():
            raise ValueError("reason is required")
        if destination is None:
            output, digest = self.document_store.render(invoice)
            managed_relative_path = self.document_store.relative_path(invoice.canonical_number)
            external_path = None
        else:
            InvoicePDF().generate(
                invoice, destination, currency_symbol=currency_symbol, draft=False
            )
            output = destination
            digest = sha256(output.read_bytes()).hexdigest()
            managed_relative_path = None
            external_path = str(output)
        document = Document(
            entity_type="invoice",
            entity_id=invoice.id,
            document_type="invoice_pdf",
            managed_relative_path=managed_relative_path,
            external_path=external_path,
            original_filename=output.name,
            sha256=digest,
            mime_type="application/pdf",
        )
        session.add(document)
        session.flush()
        self.audit.record(
            session,
            action="reissue",
            entity_type="invoice",
            entity_id=invoice.id,
            summary=f"Reissued {invoice.canonical_number}",
            user_id=user_id,
            after={"reason": reason},
        )
        return invoice.canonical_number

    def register_external(
        self,
        session: Session,
        client: Client,
        canonical_number: str,
        invoice_date: date,
        total_cents: int,
        *,
        due_date: date | None = None,
        gst_cents: int | None = None,
        business: BusinessProfile | None = None,
        user_id: int | None = None,
    ) -> Invoice:
        if session.scalar(select(Invoice.id).where(Invoice.canonical_number == canonical_number)):
            raise ValueError("invoice number already exists")
        if gst_cents is None and business is not None and business.gst_registered:
            rate = Decimal(str(business.gst_rate))
            if not 0 <= rate <= 1:
                raise ValueError("GST rate must be a decimal fraction between 0 and 1")
            subtotal_cents = int(
                (Decimal(total_cents) / (Decimal("1") + rate)).quantize(Decimal("1"), ROUND_HALF_UP)
            )
            gst_cents = total_cents - subtotal_cents
        else:
            gst_cents = gst_cents or 0
            subtotal_cents = total_cents - gst_cents
        if subtotal_cents < 0 or gst_cents < 0:
            raise ValueError("GST split cannot exceed invoice total")
        invoice = Invoice(
            canonical_number=canonical_number,
            original_number=canonical_number,
            invoice_date=invoice_date,
            due_date=due_date or invoice_date + timedelta(days=client.default_terms_days),
            client_id=client.id,
            client_name_snapshot=client.display_name,
            client_abn_snapshot=client.abn,
            client_contact_snapshot=client.contact_name,
            client_email_snapshot=client.email,
            client_phone_snapshot=client.phone,
            client_address_snapshot=client.billing_address,
            gst_registered_snapshot=business.gst_registered if business else False,
            gst_rate_snapshot=business.gst_rate if business else Decimal("0"),
            total_cents=total_cents,
            subtotal_cents=subtotal_cents,
            gst_cents=gst_cents,
            issued_at=utc_now(),
            source="external",
            created_by=user_id,
        )
        session.add(invoice)
        session.flush()
        self.audit.record(
            session,
            action="register",
            entity_type="invoice",
            entity_id=invoice.id,
            summary=f"Registered external invoice {canonical_number}",
            user_id=user_id,
        )
        return invoice

    def create_credit_note(
        self,
        session: Session,
        invoice: Invoice,
        items: Iterable[InvoiceItemData],
        reason: str,
        *,
        credit_date: date | None = None,
        user_id: int | None = None,
    ) -> CreditNote:
        if not reason.strip():
            raise ValueError("reason is required")
        values = list(items)
        if not values:
            raise ValueError("at least one credit note item is required")
        for item in values:
            if not item.description or not item.description.strip():
                raise ValueError("item description is required")
            if item.unit_price_cents is None:
                raise ValueError("item price is required")
        calculations = []
        for item in values:
            unit_price_cents = item.unit_price_cents
            if unit_price_cents is None:
                raise ValueError("item price is required")
            calculations.append(
                calculate_line(
                    item.quantity,
                    unit_price_cents,
                    discount_type=item.discount_type,
                    discount_value=item.discount_value,
                    taxable=item.taxable if item.taxable is not None else False,
                    gst_rate=(
                        item.gst_rate
                        if item.gst_rate is not None
                        else (invoice.gst_rate_snapshot or Decimal("0"))
                    ),
                )
            )
        totals = calculate_invoice(calculations)
        note = CreditNote(
            canonical_number=self.numbering.reserve(session, "credit_note"),
            invoice_id=invoice.id,
            credit_date=credit_date or date.today(),
            reason=reason,
            subtotal_cents=totals.subtotal_cents,
            gst_cents=totals.gst_cents,
            total_cents=totals.total_cents,
            created_by=user_id,
        )
        session.add(note)
        session.flush()
        note_items = [
            CreditNoteItem(
                credit_note_id=note.id,
                position=index,
                description=item.description,
                quantity_decimal=Decimal(str(item.quantity)),
                unit_price_cents=unit_price_cents,
                taxable=item.taxable,
                gst_cents=calculation.gst_cents,
                total_cents=calculation.total_cents,
            )
            for index, (item, calculation) in enumerate(zip(values, calculations, strict=True), 1)
        ]
        session.add_all(note_items)
        session.flush()
        self.audit.record(
            session,
            action="create",
            entity_type="credit_note",
            entity_id=note.id,
            summary=f"Created credit note {note.canonical_number}",
            user_id=user_id,
        )
        return note

    def history(self, session: Session, invoice: Invoice) -> list[AuditEvent]:
        return list(
            session.scalars(
                select(AuditEvent)
                .where(AuditEvent.entity_type == "invoice", AuditEvent.entity_id == invoice.id)
                .order_by(AuditEvent.timestamp_utc)
            ).all()
        )

    def search(self, session: Session, term: str = "") -> list[Invoice]:
        stmt = (
            select(Invoice)
            .options(selectinload(Invoice.items))
            .order_by(Invoice.invoice_date.desc())
        )
        if term.strip():
            value = f"%{term.strip()}%"
            stmt = stmt.join(Client).where(
                Invoice.canonical_number.ilike(value)
                | Invoice.original_number.ilike(value)
                | Invoice.client_name_snapshot.ilike(value)
                | Client.display_name.ilike(value)
            )
        return list(session.scalars(stmt).unique().all())

    def export_csv(self, session: Session, invoices: list[Invoice] | None = None) -> str:
        output = io.StringIO()
        fields = [
            "canonical_number",
            "invoice_date",
            "due_date",
            "client_name_snapshot",
            "total_cents",
        ]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for invoice in invoices or self.search(session):
            writer.writerow(
                {
                    "canonical_number": invoice.canonical_number,
                    "invoice_date": invoice.invoice_date,
                    "due_date": invoice.due_date,
                    "client_name_snapshot": invoice.client_name_snapshot,
                    "total_cents": invoice.total_cents,
                }
            )
        return output.getvalue()
