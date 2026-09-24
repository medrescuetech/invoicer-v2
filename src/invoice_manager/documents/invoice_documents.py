from __future__ import annotations

from pathlib import Path

from invoice_manager.config import AppPaths, AppSettings
from invoice_manager.documents.invoice_pdf import InvoicePDF
from invoice_manager.infrastructure.file_store import FileStore
from invoice_manager.persistence.models import Invoice


class InvoiceDocumentStore:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths.ensure()
        self.files = FileStore(self.paths.root)
        self.currency_symbol = AppSettings.load(self.paths.settings_file).currency_symbol

    @staticmethod
    def relative_path(canonical_number: str) -> str:
        return f"documents/invoices/{canonical_number}.pdf"

    def path_for(self, canonical_number: str) -> Path:
        return self.files.managed_path(self.relative_path(canonical_number))

    def render(self, invoice: Invoice, *, draft: bool = False) -> tuple[Path, str]:
        if not invoice.canonical_number:
            raise ValueError("invoice must have a canonical number")
        path = self.path_for(invoice.canonical_number)
        InvoicePDF().generate(
            invoice,
            path,
            currency_symbol=self.currency_symbol,
            draft=draft,
        )
        return path, self.files.sha256(path)

    def render_draft_preview(self, invoice: Invoice) -> Path:
        path = self.paths.exports / "invoice-previews" / "draft-preview.pdf"
        InvoicePDF().generate(
            invoice,
            path,
            currency_symbol=self.currency_symbol,
            draft=True,
        )
        return path
