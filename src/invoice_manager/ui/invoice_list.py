from __future__ import annotations

import subprocess
from hashlib import sha256
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from invoice_manager.application.invoice_service import InvoiceService
from invoice_manager.config import AppPaths
from invoice_manager.domain.money import format_aud
from invoice_manager.infrastructure.file_store import FileStore
from invoice_manager.persistence.models import Document, Invoice


class InvoiceListView(QWidget):
    invoice_selected = Signal(object)

    def __init__(
        self,
        session: Session | None = None,
        *,
        invoice_service: InvoiceService | None = None,
        paths: AppPaths | None = None,
        user_id: int | None = None,
    ) -> None:
        super().__init__()
        self.session = session
        self.paths = paths or AppPaths.resolve()
        self.user_id = user_id
        self.files = FileStore(self.paths.root)
        self.service = invoice_service or InvoiceService(paths=self.paths)
        self.search = QLineEdit()
        self.search.setObjectName("invoiceSearch")
        self.search.setPlaceholderText("Search invoices")
        self.search.textChanged.connect(self.refresh)
        self.status_filter = QComboBox()
        self.status_filter.addItems(
            [
                "All",
                "Draft",
                "Issued",
                "Part Paid",
                "Paid",
                "Overdue",
                "Credited",
                "Cancelled",
                "Void",
            ]
        )
        self.status_filter.currentTextChanged.connect(self.refresh)
        self.sort = QComboBox()
        self.sort.addItems(["Newest first", "Oldest first", "Total highest", "Total lowest"])
        self.sort.currentTextChanged.connect(self.refresh)
        self.table = QTableWidget(0, 6)
        self.table.setObjectName("invoiceTable")
        self.table.setHorizontalHeaderLabels(["Number", "Client", "Date", "Due", "Status", "Total"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.cellClicked.connect(self._select)
        self.history_button = QPushButton("History")
        self.open_button = QPushButton("Open PDF")
        self.reveal_button = QPushButton("Reveal PDF")
        self.relink_button = QPushButton("Relink PDF")
        self.export_button = QPushButton("Export / copy CSV")
        self.history_button.clicked.connect(self._history)
        self.open_button.clicked.connect(self._open_pdf)
        self.reveal_button.clicked.connect(self._reveal_pdf)
        self.relink_button.clicked.connect(self._relink)
        self.export_button.clicked.connect(self._copy_export)
        actions = QHBoxLayout()
        for button in (
            self.history_button,
            self.open_button,
            self.reveal_button,
            self.relink_button,
            self.export_button,
        ):
            actions.addWidget(button)
        filters = QHBoxLayout()
        filters.addWidget(self.search)
        filters.addWidget(self.status_filter)
        filters.addWidget(self.sort)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Invoices"))
        layout.addLayout(filters)
        layout.addWidget(self.table)
        layout.addLayout(actions)
        self._selected: Invoice | None = None
        self.refresh()

    def showEvent(self, event: QShowEvent) -> None:
        self.refresh()
        super().showEvent(event)

    def _invoices(self) -> list[Invoice]:
        if self.session is None:
            return []
        invoices = self.service.search(self.session, self.search.text())
        selected = self.status_filter.currentText()
        if selected != "All":
            invoices = [
                invoice
                for invoice in invoices
                if self.service.status(self.session, invoice).value == selected
            ]
        selected_sort = self.sort.currentText()
        if selected_sort == "Oldest first":
            invoices.sort(key=lambda invoice: invoice.invoice_date)
        elif selected_sort == "Total highest":
            invoices.sort(key=lambda invoice: invoice.total_cents, reverse=True)
        elif selected_sort == "Total lowest":
            invoices.sort(key=lambda invoice: invoice.total_cents)
        return invoices

    def refresh(self) -> None:
        self.table.setRowCount(0)
        for invoice in self._invoices():
            row = self.table.rowCount()
            self.table.insertRow(row)
            status = self.service.status(self.session, invoice).value if self.session else "Draft"
            values = [
                invoice.canonical_number or "DRAFT",
                invoice.client_name_snapshot,
                invoice.invoice_date.strftime("%d/%m/%Y"),
                invoice.due_date.strftime("%d/%m/%Y"),
                status,
                format_aud(invoice.total_cents),
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))

    def _select(self, row: int, _column: int) -> None:
        invoices = self._invoices()
        self._selected = invoices[row] if row < len(invoices) else None
        if self._selected is not None:
            self.invoice_selected.emit(self._selected)

    def _document(self) -> Document | None:
        if self.session is None or self._selected is None:
            return None
        return self.session.scalar(
            select(Document)
            .where(Document.entity_type == "invoice", Document.entity_id == self._selected.id)
            .order_by(Document.created_at.desc())
        )

    def _open_pdf(self) -> None:
        document = self._document()
        if document is None:
            QMessageBox.information(self, "Invoice", "No PDF is linked to this invoice")
            return
        if document.external_path:
            path = Path(document.external_path)
        elif document.managed_relative_path:
            try:
                path = self.files.managed_path(document.managed_relative_path)
            except ValueError:
                path = Path()
        else:
            path = Path()
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            QMessageBox.warning(self, "Invoice", "The linked PDF is missing")

    def _relink(self) -> None:
        document = self._document()
        if self.session is None or document is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Relink invoice PDF",
            str(self.paths.documents / "invoices"),
            "PDF files (*.pdf)",
        )
        if path:
            chosen = Path(path).resolve()
            document.original_filename = chosen.name
            document.sha256 = sha256(chosen.read_bytes()).hexdigest()
            managed_root = self.paths.documents.resolve()
            if managed_root == chosen or managed_root in chosen.parents:
                document.managed_relative_path = chosen.relative_to(self.paths.root).as_posix()
                document.external_path = None
            else:
                document.managed_relative_path = None
                document.external_path = str(chosen)
            self.session.commit()

    def _pdf_path(self) -> Path | None:
        document = self._document()
        if document is None:
            return None
        if document.external_path:
            path = Path(document.external_path)
        elif document.managed_relative_path:
            try:
                path = self.files.managed_path(document.managed_relative_path)
            except ValueError:
                return None
        else:
            return None
        return path if path.exists() else None

    def _reveal_pdf(self) -> None:
        path = self._pdf_path()
        if path is None:
            QMessageBox.warning(self, "Invoice", "The linked PDF is missing")
            return
        subprocess.Popen(["explorer.exe", f"/select,{path}"])

    def _history(self) -> None:
        if self.session is None or self._selected is None:
            return
        events = self.service.history(self.session, self._selected)
        text = "\n".join(f"{event.timestamp_utc}: {event.summary}" for event in events)
        QMessageBox.information(self, "Invoice history", text or "No history recorded")

    def _copy_export(self) -> None:
        if self.session is None:
            return
        content = self.service.export_csv(self.session, self._invoices())
        QApplication.clipboard().setText(content)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export invoices",
            str(self.paths.exports / "invoices.csv"),
            "CSV files (*.csv)",
        )
        if path:
            Path(path).write_text(content, encoding="utf-8", newline="")
