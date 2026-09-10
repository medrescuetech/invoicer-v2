"""Invoice lifecycle application service."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, cast

from invoice_manager.domain.invoices import InvoiceTotals, calculate_line_total
from invoice_manager.domain.money import Money
from invoice_manager.domain.numbering import NumberingService, parse_number
from invoice_manager.domain.statuses import InvoiceStatus, derive_invoice_status
from invoice_manager.infrastructure.audit import AuditService
from invoice_manager.persistence.models import Client, CreditNote, Invoice, InvoiceItem, Payment
from invoice_manager.persistence.repositories import (
    ClientRepository,
    InvoiceRepository,
    PaymentRepository,
    SettingRepository,
)


class InvoiceServiceError(Exception):
    pass


_UNSET: Any = object()


class InvoiceService:
    """Application service for creating, editing, issuing, and voiding invoices."""

    def __init__(
        self,
        invoice_repo: InvoiceRepository,
        client_repo: ClientRepository,
        payment_repo: PaymentRepository,
        setting_repo: SettingRepository,
        audit: AuditService,
        gst_rate: Decimal = Decimal("0.00"),
        payment_terms_days: int = 7,
    ) -> None:
        self._invoice_repo = invoice_repo
        self._client_repo = client_repo
        self._payment_repo = payment_repo
        self._setting_repo = setting_repo
        self._audit = audit
        self._gst_rate = gst_rate
        self._payment_terms_days = payment_terms_days
        self._numbering = self._load_numbering()

    def _load_numbering(self) -> NumberingService:
        next_invoice = self._setting_repo.get_int("next_invoice_number", 1)
        next_quote = self._setting_repo.get_int("next_quote_number", 1)
        next_receipt = self._setting_repo.get_int("next_receipt_number", 1)
        next_credit = self._setting_repo.get_int("next_credit_note_number", 1)
        return NumberingService(
            next_invoice=next_invoice,
            next_quote=next_quote,
            next_receipt=next_receipt,
            next_credit_note=next_credit,
        )

    def _persist_numbering(self) -> None:
        # NumberingService uses internal ints; map back by peeking next values.
        self._setting_repo.set("next_invoice_number", str(self._numbering.peek("invoice")[4:]))
        self._setting_repo.set("next_quote_number", str(self._numbering.peek("quote")[4:]))
        self._setting_repo.set("next_receipt_number", str(self._numbering.peek("receipt")[4:]))
        self._setting_repo.set(
            "next_credit_note_number", str(self._numbering.peek("credit_note")[3:])
        )

    def create_draft(
        self,
        client_id: int,
        invoice_date: date | None = None,
        due_date: date | None | object = _UNSET,
        notes: str | None = None,
    ) -> Invoice:
        client = (
            self._client_repo._session.query(Client).filter(Client.id == client_id).one_or_none()
        )
        if client is None:
            raise InvoiceServiceError("Client not found")
        today = date.today()
        issue_date = invoice_date or today
        due: date | None
        if due_date is _UNSET:
            due = issue_date + timedelta(days=self._payment_terms_days)
        else:
            due = cast(date | None, due_date)
        invoice = self._invoice_repo.create(
            number="DRAFT",
            sequence_number=-1,
            issue_date=issue_date,
            due_date=due,
            client_id=client.id,
            client_name=client.name,
            client_address=client.address,
            notes=notes,
            subtotal_cents=0,
            gst_cents=0,
            total_cents=0,
            is_draft=True,
            is_void=False,
            is_cancelled=False,
            status="draft",
        )
        self._audit.record("draft_created", "invoices", invoice.id, {"client": client.name})
        return invoice

    def create_custom_draft(
        self,
        client_name: str,
        client_address: str | None = None,
        invoice_date: date | None = None,
        due_date: date | None | object = _UNSET,
        notes: str | None = None,
    ) -> Invoice:
        """Create a draft using one-off client details without saving a client."""
        name = client_name.strip()
        if not name:
            raise InvoiceServiceError("Client name is required")
        issue_date = invoice_date or date.today()
        due: date | None
        if due_date is _UNSET:
            due = issue_date + timedelta(days=self._payment_terms_days)
        else:
            due = cast(date | None, due_date)
        invoice = self._invoice_repo.create(
            number="DRAFT",
            sequence_number=-1,
            issue_date=issue_date,
            due_date=due,
            client_id=None,
            client_name=name,
            client_address=client_address.strip() if client_address else None,
            notes=notes,
            subtotal_cents=0,
            gst_cents=0,
            total_cents=0,
            is_draft=True,
            is_void=False,
            is_cancelled=False,
            status="draft",
        )
        self._audit.record("draft_created", "invoices", invoice.id, {"client": name})
        return invoice

    def add_line(
        self,
        invoice: Invoice,
        description: str,
        quantity: int,
        unit_price_cents: int,
        taxable: bool = True,
        discount_cents: int = 0,
        unit: str = "ea",
    ) -> InvoiceItem:
        if not invoice.is_draft:
            raise InvoiceServiceError("Cannot edit an issued invoice")
        subtotal, gst, total = calculate_line_total(
            quantity,
            unit_price_cents,
            discount_cents,
            taxable,
            self._gst_rate,
        )
        item = InvoiceItem(
            invoice_id=invoice.id,
            description=description.strip(),
            quantity=quantity,
            unit=unit.strip() or "ea",
            unit_price_cents=unit_price_cents,
            discount_cents=discount_cents,
            taxable=taxable,
            subtotal_cents=subtotal,
            gst_cents=gst,
            total_cents=total,
            sort_order=len(invoice.items),
        )
        invoice.items.append(item)
        self._recalc(invoice)
        self._audit.record("line_added", "invoice_items", item.id, {"invoice_id": invoice.id})
        return item

    def remove_line(self, invoice: Invoice, item: InvoiceItem) -> None:
        if not invoice.is_draft:
            raise InvoiceServiceError("Cannot edit an issued invoice")
        invoice.items.remove(item)
        self._recalc(invoice)
        self._audit.record("line_removed", "invoice_items", item.id, {"invoice_id": invoice.id})

    def update_invoice(
        self,
        invoice: Invoice,
        issue_date: date,
        due_date: date | None,
        notes: str | None,
        lines: list[dict[str, Any]],
    ) -> Invoice:
        """Replace line items and recalculate totals for an existing invoice."""
        if invoice.is_void:
            raise InvoiceServiceError("Cannot edit a void invoice")
        if invoice.is_cancelled:
            raise InvoiceServiceError("Cannot edit a cancelled invoice")
        if invoice.status == "duplicate":
            raise InvoiceServiceError("Cannot edit a duplicate invoice")
        if not lines or all(line.get("unit_price_cents", 0) == 0 for line in lines):
            raise InvoiceServiceError("Invoice must have at least one priced line item")
        invoice.issue_date = issue_date  # type: ignore[assignment]
        invoice.due_date = due_date  # type: ignore[assignment]
        invoice.notes = notes
        invoice.items.clear()
        for sort_order, line in enumerate(lines):
            subtotal, gst, total = calculate_line_total(
                line["quantity"],
                line["unit_price_cents"],
                line["discount_cents"],
                line["taxable"],
                self._gst_rate,
            )
            item = InvoiceItem(
                invoice_id=invoice.id,
                description=line["description"].strip(),
                quantity=line["quantity"],
                unit=str(line.get("unit", "ea")).strip() or "ea",
                unit_price_cents=line["unit_price_cents"],
                discount_cents=line["discount_cents"],
                taxable=line["taxable"],
                subtotal_cents=subtotal,
                gst_cents=gst,
                total_cents=total,
                sort_order=sort_order,
            )
            invoice.items.append(item)
        self._recalc(invoice)
        self._update_status(invoice)
        self._audit.record("invoice_updated", "invoices", invoice.id, {"number": invoice.number})
        return invoice

    def issue(self, invoice: Invoice) -> Invoice:
        if not invoice.is_draft:
            raise InvoiceServiceError("Invoice is already issued")
        if not invoice.items:
            raise InvoiceServiceError("Cannot issue an invoice with no line items")
        if invoice.number == "DRAFT":
            number = self._numbering.reserve("invoice")
            invoice.number = number
            invoice.sequence_number = int(number.split("-")[1])
        else:
            # Re-issuing a previously issued (retracted) invoice; keep the number
            # but make sure the numbering service does not reuse it.
            parsed = parse_number(invoice.number)
            if parsed:
                _, seq = parsed
                current = int(self._numbering.peek("invoice").split("-", 1)[1])
                if seq >= current:
                    self._numbering.set_next("invoice", seq + 1)
                invoice.sequence_number = seq
        invoice.is_draft = False
        invoice.status = "issued"
        self._persist_numbering()
        self._update_status(invoice)
        self._audit.record("invoice_issued", "invoices", invoice.id, {"number": invoice.number})
        return invoice

    def issue_quote(self, invoice: Invoice) -> Invoice:
        """Issue a draft as a quote, assigning a QTE- number and quoted status."""
        if not invoice.is_draft:
            raise InvoiceServiceError("Quote is already issued")
        if not invoice.items:
            raise InvoiceServiceError("Cannot issue a quote with no line items")
        if invoice.number == "DRAFT":
            number = self._numbering.reserve("quote")
            invoice.number = number
            invoice.sequence_number = int(number.split("-")[1])
        else:
            # Re-issuing a previously issued/retracted quote; keep the number.
            parsed = parse_number(invoice.number)
            if parsed:
                _, seq = parsed
                current = int(self._numbering.peek("quote").split("-", 1)[1])
                if seq >= current:
                    self._numbering.set_next("quote", seq + 1)
                invoice.sequence_number = seq
        invoice.is_draft = False
        invoice.status = InvoiceStatus.QUOTED.value
        self._persist_numbering()
        self._update_status(invoice)
        self._audit.record("quote_issued", "invoices", invoice.id, {"number": invoice.number})
        return invoice

    def convert_quote_to_invoice(self, invoice: Invoice) -> Invoice:
        """Upgrade a quote to an invoice, allocating an INV- number."""
        if not invoice.is_quote:
            raise InvoiceServiceError("Only quotes can be converted to invoices")
        if invoice.is_void or invoice.is_cancelled:
            raise InvoiceServiceError("Cannot convert void or cancelled quote")
        quote_number = invoice.number
        number = self._numbering.reserve("invoice")
        invoice.number = number
        invoice.sequence_number = int(number.split("-")[1])
        invoice.is_draft = False
        if not invoice.reference:
            invoice.reference = quote_number
        if invoice.due_date is None:
            issue = cast(date, invoice.issue_date)
            due: date | None = issue + timedelta(days=self._payment_terms_days)
            invoice.due_date = due  # type: ignore[assignment]
        self._persist_numbering()
        self._update_status(invoice)
        self._audit.record(
            "quote_converted",
            "invoices",
            invoice.id,
            {"quote_number": quote_number, "invoice_number": number},
        )
        return invoice

    def reissue(self, invoice: Invoice) -> Invoice:
        """Issue or re-issue an invoice/quote that has a number assigned."""
        if not invoice.is_draft:
            raise InvoiceServiceError("Invoice is already issued")
        if invoice.number == "DRAFT":
            raise InvoiceServiceError("Invoice has no number to reissue")
        if invoice.is_void or invoice.is_cancelled:
            raise InvoiceServiceError("Cannot reissue void or cancelled invoice")
        if invoice.is_quote:
            return self.issue_quote(invoice)
        return self.issue(invoice)

    def retract(self, invoice: Invoice) -> Invoice:
        """Revert an issued invoice/quote to draft so it can be edited."""
        if invoice.is_draft:
            raise InvoiceServiceError("Invoice is already a draft")
        if invoice.is_void or invoice.is_cancelled:
            raise InvoiceServiceError("Cannot retract void or cancelled invoice")
        if any(p for p in invoice.payments if not p.is_reversed) or invoice.credits:
            raise InvoiceServiceError("Cannot retract an invoice with payments or credits")
        invoice.is_draft = True
        invoice.status = "draft"
        self._audit.record("invoice_retracted", "invoices", invoice.id, {"number": invoice.number})
        return invoice

    def cancel(self, invoice: Invoice, reason: str) -> Invoice:
        if invoice.is_draft:
            raise InvoiceServiceError("Draft cannot be cancelled")
        if invoice.total_cents <= 0:
            raise InvoiceServiceError("Cannot cancel a zero-value invoice")
        invoice.is_cancelled = True
        self._update_status(invoice)
        self._audit.record("invoice_cancelled", "invoices", invoice.id, {"reason": reason})
        return invoice

    def void(self, invoice: Invoice, reason: str) -> Invoice:
        if invoice.is_draft:
            raise InvoiceServiceError("Draft cannot be voided")
        invoice.is_void = True
        self._update_status(invoice)
        self._audit.record("invoice_voided", "invoices", invoice.id, {"reason": reason})
        return invoice

    def mark_duplicate(self, invoice: Invoice, reason: str) -> Invoice:
        if invoice.is_draft or invoice.is_void or invoice.is_cancelled:
            raise InvoiceServiceError("Only issued invoices can be marked duplicate")
        if invoice.payments or invoice.credits:
            raise InvoiceServiceError("An invoice with payments or credits cannot be marked duplicate")
        invoice.status = "duplicate"
        self._audit.record("invoice_marked_duplicate", "invoices", invoice.id, {"reason": reason})
        return invoice

    def add_credit_note(
        self,
        invoice: Invoice,
        amount_cents: int,
        reason: str,
        credit_date: date,
    ) -> CreditNote:
        """Apply a credit note to an issued invoice."""
        if invoice.is_draft:
            raise InvoiceServiceError("Cannot credit a draft invoice")
        if invoice.is_void or invoice.is_cancelled:
            raise InvoiceServiceError("Cannot credit a void or cancelled invoice")
        if amount_cents <= 0:
            raise InvoiceServiceError("Credit note amount must be positive")
        if amount_cents > invoice.total_cents:
            raise InvoiceServiceError("Credit note cannot exceed invoice total")
        number = self._numbering.reserve("credit_note")
        credit = CreditNote(
            number=number,
            invoice_id=invoice.id,
            amount_cents=amount_cents,
            date=credit_date,
            reason=reason.strip(),
        )
        invoice.credits.append(credit)
        self._persist_numbering()
        self._update_status(invoice)
        self._audit.record(
            "credit_note_added",
            "credit_notes",
            credit.id,
            {"invoice_id": invoice.id, "number": number, "amount_cents": amount_cents},
        )
        return credit

    def clone_invoice(self, invoice: Invoice) -> Invoice:
        """Create a new draft invoice copied from an existing invoice."""
        if invoice.client_id is None:
            raise InvoiceServiceError("Cannot clone an invoice without a linked client")
        draft = self.create_draft(
            client_id=invoice.client_id,
            invoice_date=cast(date, invoice.issue_date),
            due_date=invoice.due_date,
            notes=invoice.notes,
        )
        for item in invoice.items:
            self.add_line(
                draft,
                item.description,
                item.quantity,
                item.unit_price_cents,
                item.taxable,
                item.discount_cents,
                item.unit or "ea",
            )
        self._audit.record(
            "invoice_cloned", "invoices", draft.id, {"source": invoice.number}
        )
        return draft

    def recalc(self, invoice: Invoice) -> None:
        """Recalculate totals and status for an existing invoice."""
        self._recalc(invoice)
        self._update_status(invoice)

    def _recalc(self, invoice: Invoice) -> None:
        subtotal = 0
        gst = 0
        total = 0
        for item in invoice.items:
            s, g, t = calculate_line_total(
                item.quantity,
                item.unit_price_cents,
                item.discount_cents,
                item.taxable,
                self._gst_rate,
            )
            item.subtotal_cents = s
            item.gst_cents = g
            item.total_cents = t
            subtotal += s
            gst += g
            total += t
        invoice.subtotal_cents = subtotal
        invoice.gst_cents = gst
        invoice.total_cents = total

    def _update_status(self, invoice: Invoice) -> None:
        balance = self._balance(invoice)
        invoice.status = derive_invoice_status(
            invoice_total_cents=invoice.total_cents,
            balance_cents=balance.cents,
            due_date=cast(date, invoice.due_date),
            is_cancelled=invoice.is_cancelled,
            is_void=invoice.is_void,
            is_quote=invoice.is_quote,
        ).value

    def _balance(self, invoice: Invoice) -> Money:
        paid = sum(
            p.amount_cents
            for p in self._payment_repo._session.query(Payment)
            .filter(Payment.invoice_id == invoice.id, Payment.is_reversed.is_(False))
            .all()
        )
        credits = sum(c.amount_cents for c in invoice.credits)
        return Money(cents=invoice.total_cents - paid - credits)

    def get(self, invoice_id: int) -> Invoice | None:
        return (
            self._invoice_repo._session.query(Invoice)
            .filter(Invoice.id == invoice_id)
            .one_or_none()
        )

    def list_invoices(self) -> Sequence[Invoice]:
        return list(
            self._invoice_repo._session.query(Invoice)
            .order_by(Invoice.issue_date.desc(), Invoice.sequence_number.desc())
            .all()
        )

    def record_manual_invoice(
        self,
        number: str,
        client_name: str,
        client_address: str | None,
        issue_date: date,
        due_date: date | None,
        subtotal_cents: int,
        gst_cents: int,
        total_cents: int,
        notes: str | None = None,
        paid: bool = False,
        paid_date: date | None = None,
        payment_note: str | None = None,
        lines: list[dict[str, Any]] | None = None,
    ) -> Invoice:
        """Record a historical invoice that was created outside the system."""
        number = number.strip()
        if not number:
            raise InvoiceServiceError("Invoice number is required")
        if self._invoice_repo.get_by_number(number):
            raise InvoiceServiceError(f"Invoice number {number} already exists")

        client = self._client_repo.get_by_name(client_name)
        client_id = client.id if client else None
        client_address = client_address or (client.address if client else None)

        parsed = parse_number(number)
        sequence = 0
        if parsed:
            _, sequence = parsed
            current = int(self._numbering.peek("invoice").split("-", 1)[1])
            if sequence >= current:
                self._numbering.set_next("invoice", sequence + 1)

        invoice = self._invoice_repo.create(
            number=number,
            sequence_number=sequence,
            issue_date=issue_date,
            due_date=due_date,
            client_id=client_id,
            client_name=client_name,
            client_address=client_address,
            reference=None,
            notes=notes,
            subtotal_cents=subtotal_cents,
            gst_cents=gst_cents,
            total_cents=total_cents,
            status="issued",
            is_draft=False,
            is_void=False,
            is_cancelled=False,
        )
        if lines:
            for sort_order, line in enumerate(lines):
                description = str(line.get("description", "")).strip()
                quantity = int(line.get("quantity", 1))
                unit_price_cents = int(line.get("unit_price_cents", 0))
                discount_cents = int(line.get("discount_cents", 0))
                taxable = bool(line.get("taxable", True))
                if not description or quantity <= 0 or unit_price_cents < 0 or discount_cents < 0:
                    raise InvoiceServiceError("Manual invoice lines contain invalid values")
                subtotal, gst, total = calculate_line_total(
                    quantity, unit_price_cents, discount_cents, taxable, self._gst_rate
                )
                invoice.items.append(
                    InvoiceItem(
                        invoice_id=invoice.id,
                        description=description,
                        quantity=quantity,
                        unit=str(line.get("unit", "ea")).strip() or "ea",
                        unit_price_cents=unit_price_cents,
                        discount_cents=discount_cents,
                        taxable=taxable,
                        subtotal_cents=subtotal,
                        gst_cents=gst,
                        total_cents=total,
                        sort_order=sort_order,
                    )
                )
            self._recalc(invoice)
            subtotal_cents = invoice.subtotal_cents
            gst_cents = invoice.gst_cents
            total_cents = invoice.total_cents

        if paid and total_cents > 0:
            payment = self._payment_repo.create(
                invoice_id=invoice.id,
                amount_cents=total_cents,
                date=paid_date or issue_date,
                method="",
                reference=payment_note,
                notes=payment_note,
                is_reversed=False,
            )
            invoice.payments.append(payment)

        self._persist_numbering()
        self._update_status(invoice)
        self._audit.record(
            "manual_invoice_recorded",
            "invoices",
            invoice.id,
            {"number": number, "client": client_name, "line_count": len(lines or [])},
        )
        return invoice

    def set_next_invoice_number(self, value: int) -> None:
        """Adjust the next invoice number to be used for new issues."""
        self._numbering.set_next("invoice", max(1, value))
        self._persist_numbering()

    def set_next_quote_number(self, value: int) -> None:
        """Adjust the next quote number to be used for new issues."""
        self._numbering.set_next("quote", max(1, value))
        self._persist_numbering()

    def set_next_credit_note_number(self, value: int) -> None:
        """Adjust the next credit note number to be used for new credit notes."""
        self._numbering.set_next("credit_note", max(1, value))
        self._persist_numbering()

    @staticmethod
    def totals_for_display(invoice: Invoice) -> InvoiceTotals:
        return InvoiceTotals(
            subtotal_cents=invoice.subtotal_cents,
            gst_cents=invoice.gst_cents,
            total_cents=invoice.total_cents,
        )
