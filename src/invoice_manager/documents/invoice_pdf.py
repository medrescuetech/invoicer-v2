from __future__ import annotations

from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate,
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from invoice_manager.domain.money import format_aud
from invoice_manager.persistence.models import Invoice


def _display_date(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value else ""


class InvoicePDF:
    """Render an invoice exclusively from its stored snapshots."""

    def generate(
        self,
        invoice: Invoice,
        destination: Path,
        *,
        currency_symbol: str = "$",
        draft: bool | None = None,
    ) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        is_draft = draft if draft is not None else invoice.issued_at is None
        styles = getSampleStyleSheet()
        body = styles["BodyText"]
        small = styles["BodyText"].clone("small")
        small.fontSize = 8
        small.leading = 10
        right = small.clone("right")
        right.alignment = TA_RIGHT
        title = styles["Title"].clone("invoice-title")
        title.fontSize = 20
        title.leading = 24

        def on_page(canvas: Canvas, doc: BaseDocTemplate) -> None:
            canvas.saveState()
            canvas.setFont("Helvetica", 8)
            canvas.setFillColor(colors.grey)
            canvas.drawRightString(195 * mm, 10 * mm, f"Page {doc.page}")
            if is_draft:
                canvas.setFont("Helvetica-Bold", 42)
                canvas.setFillColorRGB(0.88, 0.88, 0.88)
                canvas.saveState()
                canvas.translate(105 * mm, 145 * mm)
                canvas.rotate(35)
                canvas.drawCentredString(0, 0, "DRAFT")
                canvas.restoreState()
            canvas.restoreState()

        doc = SimpleDocTemplate(
            str(destination),
            pagesize=A4,
            rightMargin=15 * mm,
            leftMargin=15 * mm,
            topMargin=14 * mm,
            bottomMargin=16 * mm,
            title=f"Invoice {invoice.canonical_number or 'DRAFT'}",
        )
        story: list[object] = []
        business_name = invoice.business_name_snapshot or ""
        business_abn = invoice.business_abn_snapshot or ""
        business_address = (invoice.business_address_snapshot or "").replace("\n", "<br/>")
        business_contact = "<br/>".join(
            value
            for value in (
                invoice.business_phone_snapshot or "",
                invoice.business_email_snapshot or "",
            )
            if value
        )
        client_name = invoice.client_name_snapshot or ""
        client_abn = invoice.client_abn_snapshot or ""
        client_contact = invoice.client_contact_snapshot or ""
        client_address = (invoice.client_address_snapshot or "").replace("\n", "<br/>")
        business = [
            Paragraph(f"<b>{business_name}</b>", body),
            Paragraph(f"ABN: {business_abn}" if business_abn else "", small),
            Paragraph(business_address, small),
            Paragraph(business_contact, small),
        ]
        metadata = [
            Paragraph(
                f"<b>{'TAX INVOICE' if invoice.gst_registered_snapshot else 'INVOICE'}</b>",
                title,
            ),
            Paragraph(f"<b>Number:</b> {invoice.canonical_number or 'DRAFT'}", small),
            Paragraph(f"<b>Date:</b> {_display_date(invoice.invoice_date)}", small),
            Paragraph(f"<b>Due:</b> {_display_date(invoice.due_date)}", small),
        ]
        header = Table([[business, metadata]], colWidths=[105 * mm, 65 * mm])
        header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.extend([header, Spacer(1, 7 * mm), HRFlowable(width="100%"), Spacer(1, 5 * mm)])
        story.append(Paragraph("<b>Bill To</b>", body))
        story.append(
            Paragraph(
                (
                    f"{client_name}<br/>"
                    f"{f'ABN: {client_abn}<br/>' if client_abn else ''}"
                    f"{client_contact}<br/>"
                    f"{client_address}"
                ),
                small,
            )
        )
        story.append(Spacer(1, 5 * mm))
        if invoice.reference:
            story.append(Paragraph(f"<b>Reference:</b> {invoice.reference}", body))
            story.append(Spacer(1, 3 * mm))

        headers = ["Description", "Qty", "Unit", "Unit price", "Discount"]
        if invoice.gst_registered_snapshot:
            headers.append("GST")
        headers.append("Total")
        rows = [headers]
        for item in sorted(invoice.items, key=lambda value: value.position):
            row = [
                Paragraph(item.description.replace("&", "&amp;"), small),
                str(item.quantity_decimal),
                item.unit,
                format_aud(item.unit_price_cents, currency_symbol),
                format_aud(item.discount_cents, currency_symbol),
            ]
            if invoice.gst_registered_snapshot:
                row.append(format_aud(item.gst_cents, currency_symbol))
            row.append(format_aud(item.total_cents, currency_symbol))
            rows.append(row)
        widths = [60 * mm, 15 * mm, 18 * mm, 24 * mm, 22 * mm]
        if invoice.gst_registered_snapshot:
            widths.append(18 * mm)
        widths.append(24 * mm)
        item_table = Table(
            rows,
            repeatRows=1,
            colWidths=widths,
        )
        item_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4e79")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#f4f7fa")],
                    ),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
                    ("TOPPADDING", (0, 0), (-1, 0), 5),
                ]
            )
        )
        story.extend([item_table, Spacer(1, 5 * mm)])
        totals = [["Subtotal", format_aud(invoice.subtotal_cents, currency_symbol)]]
        if invoice.gst_registered_snapshot:
            totals.append(["GST", format_aud(invoice.gst_cents, currency_symbol)])
        totals.append(["Total", format_aud(invoice.total_cents, currency_symbol)])
        totals_table = Table(totals, colWidths=[35 * mm, 35 * mm], hAlign="RIGHT")
        totals_table.setStyle(
            TableStyle(
                [
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                    ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(totals_table)
        if invoice.bank_instructions_snapshot:
            story.extend(
                [
                    Spacer(1, 6 * mm),
                    Paragraph("<b>Payment details</b>", body),
                    Paragraph(invoice.bank_instructions_snapshot.replace("\n", "<br/>"), small),
                ]
            )
        if invoice.visible_notes:
            story.extend([Spacer(1, 4 * mm), Paragraph(invoice.visible_notes, small)])
        doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
        return destination


def generate_invoice_pdf(
    invoice: Invoice,
    destination: Path,
    *,
    currency_symbol: str = "$",
    draft: bool | None = None,
) -> Path:
    return InvoicePDF().generate(invoice, destination, currency_symbol=currency_symbol, draft=draft)
