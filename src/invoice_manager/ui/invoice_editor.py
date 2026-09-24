from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QShowEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from invoice_manager.application.client_service import ClientService
from invoice_manager.application.invoice_service import InvoiceItemData, InvoiceService
from invoice_manager.application.service_item_service import ServiceItemService
from invoice_manager.config import AppPaths
from invoice_manager.domain.money import format_aud
from invoice_manager.persistence.models import BusinessProfile, Client, Invoice, ServiceItem


class InvoiceEditorView(QWidget):
    def __init__(
        self,
        session: Session | None = None,
        invoice: Invoice | None = None,
        *,
        invoice_service: InvoiceService | None = None,
        paths: AppPaths | None = None,
        user_id: int | None = None,
    ) -> None:
        super().__init__()
        self.session = session
        self.paths = paths or AppPaths.resolve()
        self.user_id = user_id
        self.service = invoice_service or InvoiceService(paths=self.paths)
        self.clients = ClientService()
        self.services = ServiceItemService()
        self.invoice = invoice
        self.items: list[InvoiceItemData] = []
        self.client_combo = QComboBox()
        self.client_combo.setObjectName("invoiceClient")
        self.service_combo = QComboBox()
        self.service_combo.setObjectName("invoiceService")
        self.description_input = QLineEdit()
        self.description_input.setObjectName("invoiceDescription")
        self.quantity_input = QLineEdit("1")
        self.quantity_input.setObjectName("invoiceQuantity")
        self.unit_input = QLineEdit("each")
        self.price_input = QLineEdit("0")
        self.price_input.setObjectName("invoiceUnitPrice")
        self.taxable_input = QComboBox()
        self.taxable_input.addItems(["No", "Yes"])
        self.discount_input = QLineEdit("0")
        self.invoice_date_input = QLineEdit(date.today().strftime("%d/%m/%Y"))
        self.invoice_date_input.setPlaceholderText("DD/MM/YYYY")
        self.due_date_input = QLineEdit()
        self.due_date_input.setPlaceholderText("DD/MM/YYYY")
        self.reference_input = QLineEdit()
        self.notes_input = QTextEdit()
        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: #b00020;")
        self.error_label.setWordWrap(True)
        form = QFormLayout()
        for label, widget in (
            ("Client", self.client_combo),
            ("Invoice date (DD/MM/YYYY)", self.invoice_date_input),
            ("Due date (DD/MM/YYYY)", self.due_date_input),
            ("Reference", self.reference_input),
            ("Notes", self.notes_input),
        ):
            form.addRow(label, widget)
        line_form = QFormLayout()
        for label, widget in (
            ("Catalogue service", self.service_combo),
            ("Description", self.description_input),
            ("Quantity", self.quantity_input),
            ("Unit", self.unit_input),
            ("Unit price (cents)", self.price_input),
            ("Taxable", self.taxable_input),
            ("Discount (%)", self.discount_input),
        ):
            line_form.addRow(label, widget)
        self.add_line_button = QPushButton("Add line")
        self.add_line_button.clicked.connect(self._add_line)
        self.remove_line_button = QPushButton("Remove selected line")
        self.remove_line_button.clicked.connect(self._remove_line)
        line_actions = QHBoxLayout()
        line_actions.addWidget(self.add_line_button)
        line_actions.addWidget(self.remove_line_button)
        self.lines_table = QTableWidget(0, 7)
        self.lines_table.setObjectName("invoiceLines")
        self.lines_table.setHorizontalHeaderLabels(
            ["Description", "Qty", "Unit", "Price", "Taxable", "GST", "Total"]
        )
        self.lines_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.subtotal_label, self.gst_label, self.total_label = (
            QLabel("$0.00"),
            QLabel("$0.00"),
            QLabel("$0.00"),
        )
        totals = QFormLayout()
        totals.addRow("Subtotal", self.subtotal_label)
        totals.addRow("GST", self.gst_label)
        totals.addRow("Total", self.total_label)
        actions = QHBoxLayout()
        self.save_draft_button = QPushButton("Save draft")
        self.delete_draft_button = QPushButton("Delete draft")
        self.preview_button = QPushButton("Preview draft PDF")
        self.issue_button = QPushButton("Issue invoice")
        self.new_invoice_button = QPushButton("New invoice")
        self.save_draft_button.clicked.connect(self._save)
        self.delete_draft_button.clicked.connect(self._delete)
        self.preview_button.clicked.connect(self._preview)
        self.issue_button.clicked.connect(self._issue)
        self.new_invoice_button.clicked.connect(self._new_invoice)
        for button in (
            self.new_invoice_button,
            self.save_draft_button,
            self.delete_draft_button,
            self.preview_button,
            self.issue_button,
        ):
            actions.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("New Invoice"))
        layout.addWidget(self.error_label)
        layout.addLayout(form)
        layout.addLayout(line_form)
        layout.addLayout(line_actions)
        layout.addWidget(self.lines_table)
        layout.addLayout(totals)
        layout.addLayout(actions)
        self._load_choices()
        self._update_editability()
        self.service_combo.currentIndexChanged.connect(self._apply_service)
        for field in (
            self.description_input,
            self.quantity_input,
            self.unit_input,
            self.price_input,
            self.discount_input,
        ):
            field.textChanged.connect(self._refresh_lines)
        self.taxable_input.currentTextChanged.connect(self._refresh_lines)
        if invoice is not None:
            self.load_invoice(invoice)

    def showEvent(self, event: QShowEvent) -> None:
        self._load_choices()
        super().showEvent(event)

    def _load_choices(self) -> None:
        if self.session is None:
            return
        self.client_combo.clear()
        for client in self.clients.list(self.session, active_only=True):
            self.client_combo.addItem(client.display_name, client.id)
        self.service_combo.clear()
        self.service_combo.addItem("Custom line", None)
        for item in self.services.list(self.session, active_only=True):
            self.service_combo.addItem(f"{item.code} - {item.name}", item.id)

    def _apply_service(self) -> None:
        if self.session is None:
            return
        item = self.session.get(ServiceItem, self.service_combo.currentData())
        if item is not None:
            self.description_input.setText(item.name)
            self.unit_input.setText(item.unit)
            self.price_input.setText(str(item.unit_price_cents))
            self.taxable_input.setCurrentText("Yes" if item.taxable else "No")

    def _line_data(self) -> InvoiceItemData:
        service_id = self.service_combo.currentData()
        discount = self.discount_input.text() or "0"
        return InvoiceItemData(
            description=self.description_input.text(),
            quantity=self.quantity_input.text(),
            unit_price_cents=int(self.price_input.text()),
            unit=self.unit_input.text(),
            service_item_id=service_id,
            taxable=self.taxable_input.currentText() == "Yes",
            discount_type="percentage" if discount not in {"0", "0.0", ""} else "none",
            discount_value=discount,
        )

    def _add_line(self) -> None:
        try:
            self.items.append(self._line_data())
            self._refresh_lines()
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Invoice line", str(exc))

    def _remove_line(self) -> None:
        row = self.lines_table.currentRow()
        if 0 <= row < len(self.items):
            self.items.pop(row)
            self._refresh_lines()

    def _business(self) -> BusinessProfile | None:
        return (
            self.session.scalar(select(BusinessProfile).order_by(BusinessProfile.id))
            if self.session is not None
            else None
        )

    def _client(self) -> Client | None:
        if self.session is None or self.client_combo.currentData() is None:
            return None
        return self.session.get(Client, self.client_combo.currentData())

    def _preview_invoice(self, *, show_error: bool = False) -> Invoice | None:
        client = self._client()
        if self.session is None or client is None or not self.items:
            return None
        business = self._business()
        try:
            invoice_date = self._parse_date(self.invoice_date_input.text())
            due_date = self._parse_date(self.due_date_input.text())
        except ValueError as exc:
            if show_error:
                self._show_error(str(exc))
            return None
        return self.service.preview(
            self.session,
            client,
            self.items,
            invoice_date=invoice_date,
            due_date=due_date,
            business=business,
        )

    def _refresh_lines(self) -> None:
        preview = self._preview_invoice()
        self.lines_table.setRowCount(0)
        if preview is None:
            for label in (self.subtotal_label, self.gst_label, self.total_label):
                label.setText("$0.00")
            return
        for item in preview.items:
            row = self.lines_table.rowCount()
            self.lines_table.insertRow(row)
            values = [
                item.description,
                str(item.quantity_decimal),
                item.unit,
                format_aud(item.unit_price_cents),
                "Yes" if item.taxable else "No",
                format_aud(item.gst_cents),
                format_aud(item.total_cents),
            ]
            for column, value in enumerate(values):
                self.lines_table.setItem(row, column, QTableWidgetItem(value))
        self.subtotal_label.setText(format_aud(preview.subtotal_cents))
        self.gst_label.setText(format_aud(preview.gst_cents))
        self.total_label.setText(format_aud(preview.total_cents))

    @staticmethod
    def _parse_date(value: str) -> date | None:
        cleaned = value.strip()
        if not cleaned:
            return None
        for pattern in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(cleaned, pattern).date()
            except ValueError:
                continue
        raise ValueError("dates must use DD/MM/YYYY (or YYYY-MM-DD)")

    def _save(self) -> bool:
        if self.session is None:
            return False
        client = self._client()
        if client is None:
            self._show_error("Select a client")
            return False
        try:
            self.invoice = self.service.save_draft(
                self.session,
                self.invoice,
                client,
                self.items,
                invoice_date=self._parse_date(self.invoice_date_input.text()),
                due_date=self._parse_date(self.due_date_input.text()),
                business=self._business(),
                reference=self.reference_input.text(),
                visible_notes=self.notes_input.toPlainText(),
                user_id=self.user_id,
            )
            self.session.commit()
            self._clear_error()
            self._update_editability()
            return True
        except (ValueError, TypeError) as exc:
            self._show_error(str(exc))
            return False

    def _delete(self) -> None:
        if self.session is not None and self.invoice is not None:
            try:
                self.service.delete_draft(self.session, self.invoice, user_id=self.user_id)
                self.session.commit()
                self._new_invoice()
            except ValueError as exc:
                QMessageBox.warning(self, "Invoice", str(exc))

    def _preview(self) -> None:
        invoice = self._preview_invoice(show_error=True)
        if invoice is None:
            if not self.error_label.text():
                self._show_error("Add at least one line")
            return
        path = self.service.render_draft_preview(invoice)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _issue(self) -> None:
        if not self._save() or self.session is None or self.invoice is None:
            return
        answer = QMessageBox.question(
            self,
            "Issue invoice",
            "Issue this invoice? Once issued, its number, snapshots, and financial details become immutable.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            try:
                self.service.issue(self.session, self.invoice, user_id=self.user_id)
                self.session.commit()
                self._new_invoice()
            except ValueError as exc:
                self._show_error(str(exc))

    def load_invoice(self, invoice: Invoice) -> None:
        self.invoice = invoice
        self.items = [
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
        index = self.client_combo.findData(invoice.client_id)
        if index >= 0:
            self.client_combo.setCurrentIndex(index)
        self.invoice_date_input.setText(invoice.invoice_date.strftime("%d/%m/%Y"))
        self.due_date_input.setText(invoice.due_date.strftime("%d/%m/%Y"))
        self.reference_input.setText(invoice.reference)
        self.notes_input.setPlainText(invoice.visible_notes)
        self._update_editability()
        self._refresh_lines()

    def _new_invoice(self) -> None:
        self.invoice = None
        self.items.clear()
        self.client_combo.setCurrentIndex(0 if self.client_combo.count() else -1)
        self.service_combo.setCurrentIndex(0)
        self.invoice_date_input.setText(date.today().strftime("%d/%m/%Y"))
        self.due_date_input.clear()
        self.reference_input.clear()
        self.notes_input.clear()
        self.description_input.clear()
        self.quantity_input.setText("1")
        self.unit_input.setText("each")
        self.price_input.setText("0")
        self.taxable_input.setCurrentIndex(0)
        self.discount_input.setText("0")
        self._clear_error()
        self._update_editability()
        self._refresh_lines()

    def _update_editability(self) -> None:
        editable = self.invoice is None or self.invoice.issued_at is None
        for widget in (
            self.client_combo,
            self.invoice_date_input,
            self.due_date_input,
            self.reference_input,
            self.notes_input,
            self.service_combo,
            self.description_input,
            self.quantity_input,
            self.unit_input,
            self.price_input,
            self.taxable_input,
            self.discount_input,
            self.add_line_button,
            self.remove_line_button,
            self.save_draft_button,
            self.delete_draft_button,
            self.issue_button,
        ):
            widget.setEnabled(editable)
        self.new_invoice_button.setEnabled(True)

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()

    def _clear_error(self) -> None:
        self.error_label.clear()
        self.error_label.hide()
