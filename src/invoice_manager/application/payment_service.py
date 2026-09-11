"""Payment and receipt application service."""

from __future__ import annotations

from datetime import date
from typing import cast

from invoice_manager.application.ledger_service import LedgerService
from invoice_manager.domain.numbering import NumberingService
from invoice_manager.domain.statuses import derive_invoice_status
from invoice_manager.infrastructure.audit import AuditService
from invoice_manager.persistence.models import CreditNote, Invoice, Payment, Receipt
from invoice_manager.persistence.repositories import (
    InvoiceRepository,
    PaymentRepository,
    SettingRepository,
)


class PaymentServiceError(Exception):
    pass


class PaymentService:
    """Record payments, reverse payments, and issue receipts."""

    def __init__(
        self,
        payment_repo: PaymentRepository,
        invoice_repo: InvoiceRepository,
        setting_repo: SettingRepository,
        audit: AuditService,
        ledger_service: LedgerService | None = None,
    ) -> None:
        self._payment_repo = payment_repo
        self._invoice_repo = invoice_repo
        self._setting_repo = setting_repo
        self._audit = audit
        self._ledger_service = ledger_service
        self._numbering = self._load_numbering()

    def _load_numbering(self) -> NumberingService:
        next_receipt = self._setting_repo.get_int("next_receipt_number", 1)
        next_credit = self._setting_repo.get_int("next_credit_note_number", 1)
        next_invoice = self._setting_repo.get_int("next_invoice_number", 1)
        return NumberingService(
            next_invoice=next_invoice,
            next_receipt=next_receipt,
            next_credit_note=next_credit,
        )

    def _persist_numbering(self) -> None:
        self._setting_repo.set("next_receipt_number", str(int(self._numbering.peek("receipt")[4:])))
        self._setting_repo.set(
            "next_credit_note_number", str(int(self._numbering.peek("credit_note")[3:]))
        )

    def record(
        self,
        invoice: Invoice,
        amount_cents: int,
        payment_date: date,
        method: str,
        reference: str | None = None,
        notes: str | None = None,
        generate_receipt: bool = True,
    ) -> Payment:
        if invoice.is_draft:
            raise PaymentServiceError("Cannot record payment against a draft invoice")
        if invoice.is_void:
            raise PaymentServiceError("Cannot record payment against a void invoice")
        if invoice.status == "duplicate":
            raise PaymentServiceError("Cannot record payment against a duplicate invoice")
        if amount_cents <= 0:
            raise PaymentServiceError("Payment amount must be positive")

        payment = self._payment_repo.create(
            invoice_id=invoice.id,
            amount_cents=amount_cents,
            date=payment_date,
            method=method,
            reference=reference,
            notes=notes,
            is_reversed=False,
        )
        if generate_receipt:
            payment.receipt_number = self._numbering.reserve("receipt")
            self._persist_numbering()
        self._update_invoice_status(invoice)
        self._audit.record(
            "payment_recorded",
            "payments",
            payment.id,
            {"invoice": invoice.number, "amount_cents": amount_cents},
        )
        if self._ledger_service is not None:
            self._ledger_service.add_entry(
                entry_date=payment_date,
                entry_type="in",
                category="Invoice Payment",
                description=f"Payment for {invoice.number}",
                amount_cents=amount_cents,
                reference=payment.receipt_number,
                notes=notes,
            )
        return payment

    def record_manual_receipt(
        self,
        client_name: str,
        amount_cents: int,
        receipt_date: date,
        method: str,
        client_id: int | None = None,
        client_address: str | None = None,
        reference: str | None = None,
        description: str | None = None,
        notes: str | None = None,
    ) -> Receipt:
        name = client_name.strip()
        if not name:
            raise PaymentServiceError("Client or payer name is required")
        if amount_cents <= 0:
            raise PaymentServiceError("Receipt amount must be positive")
        number = self._numbering.reserve("receipt")
        receipt = Receipt(
            number=number,
            client_id=client_id,
            client_name=name,
            client_address=client_address,
            date=receipt_date,
            amount_cents=amount_cents,
            method=method.strip(),
            reference=reference,
            description=description,
            notes=notes,
        )
        self._payment_repo._session.add(receipt)
        self._payment_repo._session.flush()
        self._persist_numbering()
        self._audit.record(
            "manual_receipt_recorded",
            "receipts",
            receipt.id,
            {"number": number, "client": name, "amount_cents": amount_cents},
        )
        if self._ledger_service is not None:
            self._ledger_service.add_entry(
                entry_date=receipt_date,
                entry_type="in",
                category="Other Receipt",
                description=description or f"Receipt from {name}",
                amount_cents=amount_cents,
                reference=number,
                notes=notes,
            )
        return receipt

    def list_manual_receipts(self) -> list[Receipt]:
        return list(self._payment_repo._session.query(Receipt).order_by(Receipt.date.desc()).all())

    def reverse(self, payment: Payment, reason: str) -> Payment:
        if payment.is_reversed:
            raise PaymentServiceError("Payment is already reversed")
        payment.is_reversed = True
        payment.reversal_reason = reason
        invoice = payment.invoice
        if invoice is not None:
            self._update_invoice_status(invoice)
        self._audit.record("payment_reversed", "payments", payment.id, {"reason": reason})
        if self._ledger_service is not None and invoice is not None:
            self._ledger_service.add_entry(
                entry_date=date.today(),
                entry_type="out",
                category="Invoice Payment Reversal",
                description=f"Reversal of payment for {invoice.number}",
                amount_cents=payment.amount_cents,
                reference=payment.receipt_number,
                notes=f"Reversed: {reason}",
            )
        return payment

    def set_next_receipt_number(self, value: int) -> None:
        """Adjust the next receipt number."""
        self._numbering.set_next("receipt", max(1, value))
        self._persist_numbering()

    def _update_invoice_status(self, invoice: Invoice) -> None:
        # Query the database directly so newly-created payments are counted even
        # when the invoice object was loaded before the payment was added.
        total_paid = sum(p.amount_cents for p in self.list_by_invoice(invoice) if not p.is_reversed)
        total_credited = sum(
            c.amount_cents
            for c in self._payment_repo._session.query(CreditNote)
            .filter(CreditNote.invoice_id == invoice.id)
            .all()
        )
        balance = invoice.total_cents - total_paid - total_credited
        invoice.status = derive_invoice_status(
            invoice_total_cents=invoice.total_cents,
            balance_cents=balance,
            due_date=cast(date, invoice.due_date),
            is_cancelled=invoice.is_cancelled,
            is_void=invoice.is_void,
        ).value

    def list_by_invoice(self, invoice: Invoice) -> list[Payment]:
        return list(
            self._payment_repo._session.query(Payment)
            .filter(Payment.invoice_id == invoice.id)
            .order_by(Payment.date)
            .all()
        )
