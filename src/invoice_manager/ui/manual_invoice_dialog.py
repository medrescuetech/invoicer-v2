"""Dialog for recording a manual/historical invoice."""

from __future__ import annotations

import os
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, cast

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
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

from invoice_manager.documents.invoice_pdf import generate_invoice_pdf
from invoice_manager.domain.invoices import (
    STANDARD_UNITS,
    calculate_discount_cents,
    calculate_line_total,
)
from invoice_manager.persistence.models import Client, Invoice
from invoice_manager.ui.app_context import AppContext


class ManualInvoiceDialog(QDialog):
    """Record an invoice that was created outside the application."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._clients: list[Client] = []
        self.setWindowTitle("Record Manual Invoice")
        self.setMinimumSize(760, 680)
        self._build_ui()
        self._load_clients()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._number = QLineEdit()
        self._number.setPlaceholderText("e.g. INV-0005 or 0005")
        form.addRow("Invoice number:", self._number)

        self._client = QComboBox()
        self._client.setEditable(True)
        self._client.currentTextChanged.connect(self._on_client_changed)
        form.addRow("Client:", self._client)

        self._client_address = QLineEdit()
        form.addRow("Client address:", self._client_address)

        self._issue_date = QDateEdit()
        self._issue_date.setCalendarPopup(True)
        self._issue_date.setDate(QDate.currentDate())
        form.addRow("Invoice date:", self._issue_date)

        self._due_date = QDateEdit()
        self._due_date.setCalendarPopup(True)
        self._due_date.setDate(QDate.currentDate().addDays(7))
        form.addRow("Due date:", self._due_date)

        self._subtotal = QLineEdit("0.00")
        form.addRow("Subtotal ($):", self._subtotal)

        self._gst = QLineEdit("0.00")
        form.addRow("GST ($):", self._gst)

        self._total = QLineEdit("0.00")
        form.addRow("Total ($):", self._total)

        self._paid = QCheckBox("Already paid")
        self._paid.stateChanged.connect(self._on_paid_changed)
        form.addRow(self._paid)

        self._paid_date = QDateEdit()
        self._paid_date.setCalendarPopup(True)
        self._paid_date.setDate(QDate.currentDate())
        self._paid_date.setEnabled(False)
        form.addRow("Paid date:", self._paid_date)

        self._payment_note = QLineEdit()
        form.addRow("Payment note:", self._payment_note)

        self._notes = QTextEdit()
        self._notes.setMaximumHeight(60)
        form.addRow("Notes:", self._notes)

        layout.addLayout(form)

        layout.addWidget(QLabel("Invoice line items (optional for historical total-only records)"))
        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(
            ["Description", "Qty", "Unit", "Price", "Taxable", "Discount ($ or %)", "Total"]
        )
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.itemChanged.connect(self._recalculate_lines)
        layout.addWidget(self._table)

        line_buttons = QHBoxLayout()
        add_line = QPushButton("Add line")
        add_line.clicked.connect(self._add_line)
        remove_line = QPushButton("Remove line")
        remove_line.clicked.connect(self._remove_line)
        line_buttons.addWidget(add_line)
        line_buttons.addWidget(remove_line)
        line_buttons.addStretch()
        layout.addLayout(line_buttons)

        self._generate_pdf = QCheckBox("Generate and open invoice PDF after saving")
        self._generate_pdf.setChecked(True)
        layout.addWidget(self._generate_pdf)

        bbox = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        bbox.accepted.connect(self._save)
        bbox.rejected.connect(self.reject)
        layout.addWidget(bbox)

    def _load_clients(self) -> None:
        self._clients = self._context.client_repo.list_active()
        for client in self._clients:
            self._client.addItem(client.name, client.id)

    def _on_client_changed(self, text: str) -> None:
        for client in self._clients:
            if client.name == text:
                self._client_address.setText(client.address or "")
                return

    def _on_paid_changed(self, state: int) -> None:
        self._paid_date.setEnabled(state != 0)

    def _to_cents(self, text: str) -> int:
        try:
            return int(
                (Decimal(text.strip() or "0") * 100).to_integral_value(rounding=ROUND_HALF_UP)
            )
        except Exception:
            return 0

    def _add_line(self) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem("Service"))
        self._table.setItem(row, 1, QTableWidgetItem("1"))
        unit_combo = QComboBox()
        unit_combo.setEditable(True)
        unit_combo.addItems(list(STANDARD_UNITS))
        unit_combo.setCurrentText("ea")
        self._table.setCellWidget(row, 2, unit_combo)
        self._table.setItem(row, 3, QTableWidgetItem("0.00"))
        taxable = QTableWidgetItem()
        taxable.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        taxable.setCheckState(Qt.CheckState.Checked)
        self._table.setItem(row, 4, taxable)
        self._table.setItem(row, 5, QTableWidgetItem("0.00"))
        total = QTableWidgetItem("$0.00")
        total.setFlags(total.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, 6, total)
        self._recalculate_lines()

    def _remove_line(self) -> None:
        rows = sorted({index.row() for index in self._table.selectedIndexes()}, reverse=True)
        for row in rows:
            self._table.removeRow(row)
        self._recalculate_lines()

    def _line_text(self, row: int, column: int) -> str:
        item = self._table.item(row, column)
        return item.text().strip() if item is not None else ""

    def _unit_text(self, row: int) -> str:
        widget = self._table.cellWidget(row, 2)
        if isinstance(widget, QComboBox):
            return widget.currentText().strip()
        item = self._table.item(row, 2)
        return item.text().strip() if item is not None else ""

    def _discount_cents(self, row: int, quantity: int, unit_price_cents: int) -> int:
        return calculate_discount_cents(self._line_text(row, 5), quantity, unit_price_cents)

    def _collect_lines(self) -> list[dict[str, Any]]:
        lines: list[dict[str, Any]] = []
        for row in range(self._table.rowCount()):
            price = self._to_cents(self._line_text(row, 3))
            description = self._line_text(row, 0)
            if price == 0 and (not description or description == "Service"):
                continue
            try:
                quantity = int(self._line_text(row, 1) or "1")
            except ValueError:
                quantity = 0
            taxable_item = self._table.item(row, 4)
            lines.append(
                {
                    "description": description,
                    "quantity": quantity,
                    "unit": self._unit_text(row) or "ea",
                    "unit_price_cents": price,
                    "discount_cents": self._discount_cents(row, quantity, price),
                    "taxable": taxable_item is not None
                    and taxable_item.checkState() == Qt.CheckState.Checked,
                }
            )
        return lines

    def _recalculate_lines(self) -> None:
        gst_rate = Decimal(self._context.setting_repo.get("gst_rate") or "0.0")
        subtotal = gst = total = 0
        self._table.blockSignals(True)
        for row in range(self._table.rowCount()):
            try:
                quantity = int(self._line_text(row, 1) or "1")
            except ValueError:
                quantity = 0
            taxable_item = self._table.item(row, 4)
            line_subtotal, line_gst, line_total = calculate_line_total(
                quantity,
                self._to_cents(self._line_text(row, 3)),
                self._discount_cents(
                    row, quantity, self._to_cents(self._line_text(row, 3))
                ),
                taxable_item is not None and taxable_item.checkState() == Qt.CheckState.Checked,
                gst_rate,
            )
            total_item = self._table.item(row, 6)
            if total_item is not None:
                total_item.setText(f"${line_total / 100:.2f}")
            subtotal += line_subtotal
            gst += line_gst
            total += line_total
        self._table.blockSignals(False)
        if any(line["unit_price_cents"] for line in self._collect_lines()):
            self._subtotal.setText(f"{subtotal / 100:.2f}")
            self._gst.setText(f"{gst / 100:.2f}")
            self._total.setText(f"{total / 100:.2f}")

    def _invoice_settings(self) -> dict[str, Any]:
        keys = [
            "business_name", "business_address", "business_abn", "business_phone",
            "business_email", "gst_rate", "bank_name", "bank_bsb", "bank_account",
            "bank_account_name", "invoice_title_tax", "invoice_title", "invoice_date_label",
            "invoice_due_date_label", "invoice_client_label", "invoice_address_label",
            "invoice_description_header", "invoice_qty_header", "invoice_unit_header",
            "invoice_price_header", "invoice_gst_header", "invoice_total_header",
            "invoice_subtotal_label", "invoice_gst_label", "invoice_total_label",
            "invoice_amount_paid_label", "invoice_balance_due_label",
            "invoice_payment_details_label", "invoice_bank_label", "invoice_bsb_label",
            "invoice_account_label", "invoice_account_name_label", "invoice_notes_label",
            "invoice_payment_terms_note", "invoice_gst_footer_note", "invoice_thank_you",
        ]
        return {key: self._context.setting_repo.get(key) for key in keys}

    def _generate_invoice_pdf(self, invoice: Invoice) -> None:
        path = (
            self._context.config.get_documents_directory()
            / "invoices"
            / str(cast(date, invoice.issue_date).year)
            / f"{invoice.number}.pdf"
        )
        generate_invoice_pdf(invoice, self._invoice_settings(), path)
        invoice.pdf_path = str(path)
        self._context.session.commit()
        os.startfile(str(path))

    def _save(self) -> None:
        number = self._number.text().strip()
        client_name = self._client.currentText().strip()
        if not number or not client_name:
            QMessageBox.warning(self, "Missing", "Invoice number and client are required.")
            return

        lines = self._collect_lines()
        if any(
            not line["description"]
            or line["quantity"] <= 0
            or line["unit_price_cents"] < 0
            or line["discount_cents"] < 0
            for line in lines
        ):
            QMessageBox.warning(self, "Invalid", "Check each line description, quantity and amount.")
            return
        subtotal = self._to_cents(self._subtotal.text())
        gst = self._to_cents(self._gst.text())
        total = self._to_cents(self._total.text())
        if total <= 0:
            QMessageBox.warning(self, "Invalid", "Total must be greater than zero.")
            return

        try:
            invoice = self._context.invoice_service.record_manual_invoice(
                number=number,
                client_name=client_name,
                client_address=self._client_address.text().strip() or None,
                issue_date=cast(date, self._issue_date.date().toPython()),
                due_date=cast(date, self._due_date.date().toPython()),
                subtotal_cents=subtotal,
                gst_cents=gst,
                total_cents=total,
                notes=self._notes.toPlainText().strip() or None,
                paid=self._paid.isChecked(),
                paid_date=(
                    cast(date, self._paid_date.date().toPython())
                    if self._paid.isChecked()
                    else None
                ),
                payment_note=self._payment_note.text().strip() or None,
                lines=lines or None,
            )
            self._context.session.commit()
            if self._generate_pdf.isChecked():
                self._generate_invoice_pdf(invoice)
            QMessageBox.information(self, "Saved", f"Invoice {invoice.number} recorded.")
            self.accept()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Failed", str(exc))
