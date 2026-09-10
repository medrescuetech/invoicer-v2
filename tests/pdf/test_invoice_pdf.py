from datetime import date
from decimal import Decimal

import pdfplumber

from invoice_manager.documents.invoice_pdf import generate_invoice_pdf
from invoice_manager.persistence.models import Client, Invoice, InvoiceItem


def test_invoice_pdf_contains_number_and_total(tmp_path):
    client = Client(name="Acme Corp", address="123 Main St")
    invoice = Invoice(
        number="INV-0001",
        sequence_number=1,
        issue_date=date(2026, 1, 15),
        due_date=date(2026, 2, 15),
        client=client,
        client_name=client.name,
        client_address=client.address,
        subtotal_cents=10000,
        gst_cents=1000,
        total_cents=11000,
        is_draft=False,
    )
    invoice.items.append(
        InvoiceItem(
            description="Consulting",
            quantity=1,
            unit="ea",
            unit_price_cents=10000,
            taxable=True,
            subtotal_cents=10000,
            gst_cents=1000,
            total_cents=11000,
            sort_order=0,
        )
    )
    settings = {
        "business_name": "Test Business",
        "business_address": "456 Market St",
        "gst_rate": Decimal("0.10"),
        "bank_name": "Test Bank",
        "bank_bsb": "000-000",
        "bank_account": "12345678",
        "bank_account_name": "Test Business",
        "thank_you_note": "Thanks!",
    }
    output = tmp_path / "invoice.pdf"
    generate_invoice_pdf(invoice, settings, output)

    assert output.exists()
    with pdfplumber.open(output) as pdf:
        text = " ".join(page.extract_text() or "" for page in pdf.pages)
    assert "INV-0001" in text
    assert "Acme Corp" in text
    assert "$110.00" in text
    assert text.count("Consulting") == 1
    assert text.count("Description") == 1


def test_invoice_pdf_includes_custom_unit(tmp_path):
    client = Client(name="Acme Corp")
    invoice = Invoice(
        number="INV-0002",
        sequence_number=2,
        issue_date=date(2026, 1, 15),
        due_date=date(2026, 2, 15),
        client=client,
        client_name=client.name,
        client_address="",
        subtotal_cents=10000,
        gst_cents=1000,
        total_cents=11000,
        is_draft=False,
    )
    invoice.items.append(
        InvoiceItem(
            description="Consulting",
            quantity=1,
            unit="hour",
            unit_price_cents=10000,
            taxable=True,
            subtotal_cents=10000,
            gst_cents=1000,
            total_cents=11000,
            sort_order=0,
        )
    )
    settings = {"business_name": "Test", "gst_rate": Decimal("0.10")}
    output = tmp_path / "invoice.pdf"
    generate_invoice_pdf(invoice, settings, output)
    with pdfplumber.open(output) as pdf:
        text = " ".join(page.extract_text() or "" for page in pdf.pages)
    assert "hour" in text


def test_quote_pdf_title_and_na_due_date(tmp_path):
    from invoice_manager.documents.invoice_pdf import generate_quote_pdf

    client = Client(name="Acme Corp")
    quote = Invoice(
        number="QTE-0001",
        sequence_number=1,
        issue_date=date(2026, 1, 15),
        due_date=None,
        client=client,
        client_name=client.name,
        client_address="123 Main St",
        subtotal_cents=10000,
        gst_cents=1000,
        total_cents=11000,
        is_draft=False,
    )
    quote.items.append(
        InvoiceItem(
            description="Quote item",
            quantity=1,
            unit="ea",
            unit_price_cents=10000,
            taxable=True,
            subtotal_cents=10000,
            gst_cents=1000,
            total_cents=11000,
            sort_order=0,
        )
    )
    settings = {
        "business_name": "Test Business",
        "gst_rate": Decimal("0.10"),
        "quote_title": "QUOTE",
        "quote_date_label": "Quote date:",
        "quote_due_date_label": "Valid until:",
        "quote_due_date_na_text": "N/A",
    }
    output = tmp_path / "quote.pdf"
    generate_quote_pdf(quote, settings, output)
    with pdfplumber.open(output) as pdf:
        text = " ".join(page.extract_text() or "" for page in pdf.pages)
    assert "QTE-0001" in text
    assert "QUOTE" in text
    assert "N/A" in text
    assert "Quote date:" in text
    # Payment details should not appear on quotes
    assert "Payment details" not in text
    # Amount paid/balance due should not appear on quotes
    assert "Amount Paid" not in text
