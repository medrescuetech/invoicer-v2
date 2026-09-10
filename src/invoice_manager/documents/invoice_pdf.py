"""Generate a professional A4 invoice PDF with ReportLab."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from invoice_manager.domain.money import Money
from invoice_manager.domain.statuses import invoice_balance_cents
from invoice_manager.persistence.models import Invoice


class InvoicePDFBuilder:
    """Build an invoice or quote PDF from an Invoice model."""

    def __init__(self, invoice: Invoice, settings: dict[str, Any], is_quote: bool = False) -> None:
        self.invoice = invoice
        self.settings = settings
        self.is_quote = is_quote

    def _fmt(self, cents: int) -> str:
        return Money(cents=cents).__str__()

    def _get(self, key: str, default: str = "") -> str:
        value = self.settings.get(key, default)
        if not value:
            return default
        return str(value)

    def _label(self, key: str, default: str = "") -> str:
        """Return a quote-specific label if available, otherwise the invoice label."""
        if self.is_quote:
            quote_key = f"quote_{key.removeprefix('invoice_')}"
            value = self.settings.get(quote_key)
            if value:
                return str(value)
        return self._get(key, default)

    def build(self, output_path: Path) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=A4,
            rightMargin=20 * mm,
            leftMargin=20 * mm,
            topMargin=20 * mm,
            bottomMargin=20 * mm,
        )
        styles = getSampleStyleSheet()
        story: list[Any] = []

        # Header
        story.append(Paragraph(self._get("business_name", "Invoice"), styles["Title"]))
        abn = self._get("business_abn")
        if abn:
            story.append(Paragraph(f"ABN: {abn}", styles["Normal"]))
        phone = self._get("business_phone")
        email = self._get("business_email")
        contact_bits = [b for b in [phone, email] if b]
        if contact_bits:
            story.append(Paragraph("  |  ".join(contact_bits), styles["Normal"]))
        story.append(Paragraph(self._get("business_address"), styles["Normal"]))
        story.append(Spacer(1, 6 * mm))

        # Document meta
        gst_rate = Decimal(self._get("gst_rate", "0.0") or "0.0")
        if self.is_quote:
            doc_title = (
                self._get("quote_title_tax", "TAX QUOTE")
                if gst_rate > 0
                else self._get("quote_title", "QUOTE")
            )
            date_label = self._get("quote_date_label", "Quote date:")
            due_label = self._get("quote_due_date_label", "Valid until:")
            due_value = str(self.invoice.due_date) if self.invoice.due_date else self._get("quote_due_date_na_text", "N/A")
        else:
            doc_title = (
                self._get("invoice_title_tax", "TAX INVOICE")
                if gst_rate > 0
                else self._get("invoice_title", "INVOICE")
            )
            date_label = self._get("invoice_date_label", "Date:")
            due_label = self._get("invoice_due_date_label", "Due date:")
            due_value = str(self.invoice.due_date) if self.invoice.due_date else self._get("invoice_due_date_na_text", "N/A")
        story.append(Paragraph(f"<b>{doc_title}</b> — {self.invoice.number}", styles["Heading2"]))
        meta = [
            [date_label, str(self.invoice.issue_date)],
            [due_label, due_value],
            [
                self._label("invoice_client_label", "Client:"),
                self.invoice.client_name,
            ],
            [
                self._label("invoice_address_label", "Address:"),
                self.invoice.client_address or "",
            ],
        ]
        story.append(Table(meta, colWidths=[30 * mm, 120 * mm]))
        story.append(Spacer(1, 8 * mm))

        # Line items
        data: list[list[Any]] = [
            [
                self._label("invoice_description_header", "Description"),
                self._label("invoice_qty_header", "Qty"),
                self._label("invoice_unit_header", "Unit"),
                self._label("invoice_price_header", "Price"),
                self._label("invoice_gst_header", "GST"),
                self._label("invoice_total_header", "Total"),
            ]
        ]
        for item in self.invoice.items:
            data.append(
                [
                    item.description,
                    str(item.quantity),
                    item.unit or "ea",
                    self._fmt(item.unit_price_cents),
                    self._fmt(item.gst_cents),
                    self._fmt(item.total_cents),
                ]
            )
        data.append(
            ["", "", "", self._label("invoice_subtotal_label", "Subtotal"), "", self._fmt(self.invoice.subtotal_cents)]
        )
        data.append(
            ["", "", "", self._label("invoice_gst_label", "GST"), "", self._fmt(self.invoice.gst_cents)]
        )
        data.append(
            ["", "", "", self._label("invoice_total_label", "Total"), "", self._fmt(self.invoice.total_cents)]
        )

        # Payment summary (invoices only)
        if not self.is_quote:
            paid_cents = sum(
                p.amount_cents for p in self.invoice.payments if not p.is_reversed
            )
            credit_cents = sum(c.amount_cents for c in self.invoice.credits)
            amount_paid = paid_cents + credit_cents
            balance_due = invoice_balance_cents(self.invoice)
            data.append(
                ["", "", "", self._label("invoice_amount_paid_label", "Amount Paid"), "", self._fmt(amount_paid)]
            )
            data.append(
                ["", "", "", self._label("invoice_balance_due_label", "Balance Due"), "", self._fmt(balance_due)]
            )

        table = Table(data, colWidths=[70 * mm, 15 * mm, 20 * mm, 25 * mm, 20 * mm, 25 * mm])
        summary_rows = 3 if self.is_quote else 5
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, -summary_rows), (-1, -1), "Helvetica-Bold"),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 8 * mm))

        # Payment details / notes
        if not self.is_quote:
            bank_name = self._get("bank_name")
            bsb = self._get("bank_bsb")
            account = self._get("bank_account")
            account_name = self._get("bank_account_name")
            if bank_name or account:
                story.append(
                    Paragraph(
                        f"<b>{self._label('invoice_payment_details_label', 'Payment details')}</b>",
                        styles["Heading3"],
                    )
                )
                story.append(
                    Paragraph(
                        f"{self._label('invoice_bank_label', 'Bank:')} {bank_name}  |  "
                        f"{self._label('invoice_bsb_label', 'BSB:')} {bsb}  |  "
                        f"{self._label('invoice_account_label', 'Account:')} {account}  |  "
                        f"{self._label('invoice_account_name_label', 'Name:')} {account_name}",
                        styles["Normal"],
                    )
                )
                story.append(Spacer(1, 4 * mm))

            payment_terms_note = self._get("invoice_payment_terms_note", "")
            if payment_terms_note:
                story.append(
                    Paragraph(f"<b>Payment Terms:</b> {payment_terms_note}", styles["Normal"])
                )
                story.append(Spacer(1, 2 * mm))

        if self.invoice.notes:
            story.append(
                Paragraph(
                    f"<b>{self._label('invoice_notes_label', 'Notes:')}</b> {self.invoice.notes}",
                    styles["Normal"],
                )
            )

        if self.is_quote:
            quote_footer = self._get("quote_footer_note", "")
            if quote_footer:
                story.append(Spacer(1, 4 * mm))
                story.append(Paragraph(quote_footer, styles["Normal"]))
        else:
            gst_footer = self._get("invoice_gst_footer_note", "")
            if gst_footer:
                story.append(Spacer(1, 4 * mm))
                story.append(Paragraph(gst_footer, styles["Normal"]))

        thank_you = self._label("invoice_thank_you", "Thank you for your business!")
        if thank_you:
            story.append(Spacer(1, 8 * mm))
            story.append(Paragraph(thank_you, styles["Normal"]))

        doc.build(story)
        return output_path


def generate_invoice_pdf(invoice: Invoice, settings: dict[str, Any], output_path: Path) -> Path:
    return InvoicePDFBuilder(invoice, settings, is_quote=False).build(output_path)


def generate_quote_pdf(invoice: Invoice, settings: dict[str, Any], output_path: Path) -> Path:
    return InvoicePDFBuilder(invoice, settings, is_quote=True).build(output_path)


class ReportPDFBuilder:
    """Build a simple PDF from the textual report output."""

    def __init__(self, title: str, lines: list[str]) -> None:
        self.title = title
        self.lines = lines

    def build(self, output_path: Path) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=A4,
            rightMargin=20 * mm,
            leftMargin=20 * mm,
            topMargin=20 * mm,
            bottomMargin=20 * mm,
        )
        styles = getSampleStyleSheet()
        story: list[Any] = []
        story.append(Paragraph(f"<b>{self.title}</b>", styles["Title"]))
        story.append(Spacer(1, 6 * mm))
        for line in self.lines:
            story.append(Paragraph(line or " ", styles["Normal"]))
        doc.build(story)
        return output_path


def generate_report_pdf(title: str, lines: list[str], output_path: Path) -> Path:
    return ReportPDFBuilder(title, lines).build(output_path)
