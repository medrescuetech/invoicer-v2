"""Dialog for creating and editing invoices."""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from pathlib import Path
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
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from invoice_manager.documents.invoice_docx import (
    generate_invoice_docx,
    generate_quote_docx,
)
from invoice_manager.documents.invoice_pdf import (
    generate_invoice_pdf,
    generate_quote_pdf,
)
from invoice_manager.documents.invoice_xlsx import (
    generate_invoice_xlsx,
    generate_quote_xlsx,
)
from invoice_manager.documents.reminder_pdf import generate_reminder_pdf
from invoice_manager.domain.invoices import (
    STANDARD_UNITS,
    calculate_discount_cents,
    calculate_line_total,
)
from invoice_manager.domain.money import Money
from invoice_manager.persistence.models import Client, Invoice
from invoice_manager.ui.app_context import AppContext
from invoice_manager.ui.clients_page import ClientDialog
from invoice_manager.ui.invoice_history_dialog import InvoiceHistoryDialog
from invoice_manager.ui.service_items_page import ServiceItemDialog


class InvoiceEditorDialog(QDialog):
    """Create a new invoice or edit an existing draft/issued invoice."""

    def __init__(
        self,
        context: AppContext,
        invoice: Invoice | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._context = context
        self._invoice = invoice
        self.setMinimumSize(700, 500)
        self._clients: list[Client] = []
        self._build_ui()
        self._load_clients()
        self._load_services()
        self._table.itemChanged.connect(self._recalc)
        self._load_invoice()
        self._setup_mode()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        form = QFormLayout()
        client_widget = QWidget()
        client_layout = QHBoxLayout(client_widget)
        client_layout.setContentsMargins(0, 0, 0, 0)
        self._client = QComboBox()
        self._client.setEditable(True)
        self._client.setPlaceholderText("Select or type a one-off client name")
        self._client.currentIndexChanged.connect(self._client_changed)
        client_layout.addWidget(self._client, stretch=1)
        add_client_btn = QPushButton("Add")
        add_client_btn.clicked.connect(self._add_client)
        client_layout.addWidget(add_client_btn)
        edit_client_btn = QPushButton("Edit")
        edit_client_btn.clicked.connect(self._edit_client)
        client_layout.addWidget(edit_client_btn)
        form.addRow("Client:", client_widget)

        self._client_address = QLineEdit()
        self._client_address.setPlaceholderText("Address for this invoice (optional)")
        form.addRow("Client address:", self._client_address)

        self._issue_date = QDateEdit()
        self._issue_date.setCalendarPopup(True)
        self._issue_date.setDate(QDate.currentDate())
        form.addRow("Invoice date:", self._issue_date)

        self._document_type = QComboBox()
        self._document_type.addItems(["Invoice", "Quote"])
        self._document_type.currentIndexChanged.connect(self._document_type_changed)
        form.addRow("Document type:", self._document_type)

        self._due_date_na = QCheckBox("N/A")
        self._due_date_na.stateChanged.connect(self._due_date_na_changed)
        due_date_widget = QWidget()
        due_date_layout = QHBoxLayout(due_date_widget)
        due_date_layout.setContentsMargins(0, 0, 0, 0)
        self._due_date = QDateEdit()
        self._due_date.setCalendarPopup(True)
        self._due_date.setDate(QDate.currentDate())
        due_date_layout.addWidget(self._due_date)
        due_date_layout.addWidget(self._due_date_na)
        form.addRow("Due date:", due_date_widget)

        self._notes = QTextEdit()
        self._notes.setMaximumHeight(60)
        form.addRow("Notes:", self._notes)

        service_widget = QWidget()
        service_layout = QHBoxLayout(service_widget)
        service_layout.setContentsMargins(0, 0, 0, 0)
        self._service_combo = QComboBox()
        self._service_combo.addItem("-- select a service --", 0)
        service_layout.addWidget(self._service_combo, stretch=1)
        add_service_btn = QPushButton("Add to invoice")
        add_service_btn.clicked.connect(self._add_service_line)
        service_layout.addWidget(add_service_btn)
        new_service_btn = QPushButton("New")
        new_service_btn.clicked.connect(self._add_service)
        service_layout.addWidget(new_service_btn)
        edit_service_btn = QPushButton("Edit")
        edit_service_btn.clicked.connect(self._edit_service)
        service_layout.addWidget(edit_service_btn)
        form.addRow("Service:", service_widget)

        layout.addLayout(form)

        layout.addWidget(QLabel("Line items"))
        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(
            ["Description", "Qty", "Unit", "Price", "Taxable", "Discount ($ or %)", "Total"]
        )
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self._table)

        btn_layout = QHBoxLayout()
        add_btn = QPushButton("Add line")
        add_btn.clicked.connect(self._add_line)
        del_btn = QPushButton("Remove line")
        del_btn.clicked.connect(self._remove_line)
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(del_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        totals = QHBoxLayout()
        self._subtotal_lbl = QLabel("Subtotal: $0.00")
        self._gst_lbl = QLabel("GST: $0.00")
        self._total_lbl = QLabel("Total: $0.00")
        totals.addWidget(self._subtotal_lbl)
        totals.addWidget(self._gst_lbl)
        totals.addWidget(self._total_lbl)
        totals.addStretch()
        layout.addLayout(totals)

        self._actions_btn = QToolButton()
        self._actions_btn.setText("Actions")
        self._actions_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._actions_btn.setVisible(False)
        layout.addWidget(self._actions_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        bbox = QDialogButtonBox()
        self._save_draft_btn = bbox.addButton("Save Draft", QDialogButtonBox.ButtonRole.ActionRole)
        self._issue_btn = bbox.addButton("Issue", QDialogButtonBox.ButtonRole.ActionRole)
        self._upgrade_btn = bbox.addButton("Upgrade to Invoice", QDialogButtonBox.ButtonRole.ActionRole)
        self._update_btn = bbox.addButton("Update", QDialogButtonBox.ButtonRole.ActionRole)
        bbox.addButton(QDialogButtonBox.StandardButton.Cancel)
        bbox.rejected.connect(self.reject)
        self._save_draft_btn.clicked.connect(self._save_draft)
        self._issue_btn.clicked.connect(self._issue)
        self._upgrade_btn.clicked.connect(self._upgrade_to_invoice)
        self._update_btn.clicked.connect(self._update)
        layout.addWidget(bbox)

    def _load_clients(self, selected_id: int | None = None) -> None:
        current_text = self._client.currentText()
        self._clients = self._context.client_repo.list_active()
        self._client.blockSignals(True)
        self._client.clear()
        self._client.addItem("", None)
        for client in self._clients:
            self._client.addItem(client.name, client.id)
        if selected_id is not None:
            index = self._client.findData(selected_id)
            self._client.setCurrentIndex(index if index >= 0 else 0)
        elif current_text:
            self._client.setEditText(current_text)
        else:
            self._client.setCurrentIndex(0)
        self._client.blockSignals(False)
        self._client_changed()
        self._update_due_date()
        self._issue_date.dateChanged.connect(self._update_due_date)

    def _load_services(self, selected_id: int | None = None) -> None:
        self._service_combo.clear()
        self._service_combo.addItem("-- select a service --", 0)
        self._service_combo.addItem("Other — enter manually", "other")
        for item in self._context.service_repo.list_active():
            self._service_combo.addItem(item.description, item.id)
        if selected_id is not None:
            index = self._service_combo.findData(selected_id)
            self._service_combo.setCurrentIndex(index if index >= 0 else 0)

    def _client_changed(self) -> None:
        client_id = self._client.currentData()
        client = next((c for c in self._clients if c.id == client_id), None)
        if client is not None:
            self._client_address.setText(client.address or "")

    def _add_client(self) -> None:
        dlg = ClientDialog(self._context, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            clients = self._context.client_repo.list_active()
            selected_id = clients[-1].id if clients else None
            self._load_clients(selected_id)

    def _edit_client(self) -> None:
        client_id = self._client.currentData()
        client = next((c for c in self._clients if c.id == client_id), None)
        if client is None:
            QMessageBox.information(self, "Custom client", "Save this name as a client before editing it.")
            return
        dlg = ClientDialog(self._context, client=client, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._load_clients(client.id)

    def _add_service(self) -> None:
        dlg = ServiceItemDialog(self._context, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            items = self._context.service_repo.list_active()
            self._load_services(items[-1].id if items else None)

    def _edit_service(self) -> None:
        service_id = self._service_combo.currentData()
        item = self._context.service_repo.get(int(service_id)) if service_id else None
        if item is None:
            QMessageBox.information(self, "Select service", "Select a service to edit.")
            return
        dlg = ServiceItemDialog(self._context, item=item, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._load_services(item.id)

    def _load_invoice(self) -> None:
        if self._invoice is None:
            return
        if self._invoice.client_id is not None:
            index = self._client.findData(self._invoice.client_id)
            self._client.setCurrentIndex(index if index >= 0 else 0)
        else:
            self._client.setEditText(self._invoice.client_name)
        self._client_address.setText(self._invoice.client_address or "")
        issue_date = cast(date, self._invoice.issue_date)
        self._issue_date.setDate(QDate(issue_date.year, issue_date.month, issue_date.day))
        is_quote = self._invoice.is_quote
        self._document_type.setCurrentIndex(1 if is_quote else 0)
        if self._invoice.due_date is None:
            self._due_date_na.setChecked(True)
            self._due_date.setEnabled(False)
            self._due_date.setDate(self._issue_date.date())
        else:
            self._due_date_na.setChecked(False)
            self._due_date.setEnabled(True)
            due = cast(date, self._invoice.due_date)
            self._due_date.setDate(QDate(due.year, due.month, due.day))
        if self._invoice.notes:
            self._notes.setPlainText(self._invoice.notes)
        self._table.blockSignals(True)
        for item in self._invoice.items:
            self._add_line(
                description=item.description,
                quantity=item.quantity,
                unit_price_cents=item.unit_price_cents,
                taxable=item.taxable,
                unit=item.unit or "ea",
            )
            row = self._table.rowCount() - 1
            discount_item = self._table.item(row, 5)
            if discount_item is not None:
                discount_item.setText(f"{item.discount_cents / 100:.2f}")
        self._table.blockSignals(False)
        self._recalc()

    def _setup_mode(self) -> None:
        is_quote = self._invoice is not None and self._invoice.is_quote
        if self._invoice is None:
            self.setWindowTitle("New Invoice / Quote")
            self._save_draft_btn.setVisible(True)
            self._issue_btn.setVisible(True)
            self._upgrade_btn.setVisible(False)
            self._update_btn.setVisible(False)
            self._document_type.setEnabled(True)
            return
        if self._invoice.is_draft:
            title = f"Edit Quote Draft {self._invoice.id}" if is_quote else f"Edit Draft {self._invoice.id}"
            self.setWindowTitle(title)
            self._save_draft_btn.setVisible(True)
            self._issue_btn.setVisible(True)
            self._upgrade_btn.setVisible(is_quote)
            self._update_btn.setVisible(False)
            self._document_type.setEnabled(not is_quote)
        else:
            if is_quote:
                self.setWindowTitle(f"Edit Quote {self._invoice.number}")
                self._save_draft_btn.setVisible(False)
                self._issue_btn.setVisible(False)
                self._upgrade_btn.setVisible(True)
                self._update_btn.setVisible(True)
            else:
                self.setWindowTitle(f"Edit Invoice {self._invoice.number}")
                self._save_draft_btn.setVisible(False)
                self._issue_btn.setVisible(False)
                self._upgrade_btn.setVisible(False)
                self._update_btn.setVisible(True)
                self._client.setEnabled(False)
                self._client_address.setEnabled(False)
            self._document_type.setEnabled(False)
        self._actions_btn.setVisible(True)
        self._actions_btn.setMenu(self._build_actions_menu())

    def _update_due_date(self) -> None:
        if self._document_type.currentText() == "Quote" or self._due_date_na.isChecked():
            return
        terms = int(self._context.setting_repo.get("payment_terms_days") or 7)
        self._due_date.setDate(self._issue_date.date().addDays(terms))

    def _document_type_changed(self) -> None:
        is_quote = self._document_type.currentText() == "Quote"
        if is_quote:
            self._due_date_na.setChecked(True)
            self._issue_btn.setText("Save as Quote")
        else:
            self._due_date_na.setChecked(False)
            self._issue_btn.setText("Issue")
        self._due_date_na.setEnabled(not is_quote)
        self._update_due_date()

    def _due_date_na_changed(self) -> None:
        self._due_date.setEnabled(not self._due_date_na.isChecked())
        if not self._due_date_na.isChecked():
            self._update_due_date()

    def _add_line(
        self,
        description: str = "Service",
        quantity: int = 1,
        unit_price_cents: int = 0,
        taxable: bool | None = None,
        unit: str = "ea",
    ) -> None:
        if taxable is None:
            taxable = self._context.setting_repo.get("default_taxable") == "1"
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(description))
        self._table.setItem(row, 1, QTableWidgetItem(str(quantity)))
        unit_combo = QComboBox()
        unit_combo.setEditable(True)
        unit_combo.addItems(list(STANDARD_UNITS))
        unit_combo.setCurrentText(unit)
        self._table.setCellWidget(row, 2, unit_combo)
        self._table.setItem(row, 3, QTableWidgetItem(f"{unit_price_cents / 100:.2f}"))
        chk = QTableWidgetItem()
        chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        chk.setCheckState(Qt.CheckState.Checked if taxable else Qt.CheckState.Unchecked)
        self._table.setItem(row, 4, chk)
        self._table.setItem(row, 5, QTableWidgetItem("0.00"))
        self._table.setItem(row, 6, QTableWidgetItem("$0.00"))
        self._recalc()

    def _add_service_line(self) -> None:
        service_id = self._service_combo.currentData()
        if service_id is None or service_id == 0:
            return
        if service_id == "other":
            self._add_line(description="")
            self._service_combo.setCurrentIndex(0)
            self._table.setCurrentCell(self._table.rowCount() - 1, 0)
            self._table.editItem(self._table.currentItem())
            return
        item = self._context.service_repo.get(int(service_id))
        if item is None:
            return
        self._add_line(
            description=item.description,
            quantity=1,
            unit_price_cents=item.unit_price_cents,
            taxable=item.taxable,
            unit=item.unit or "ea",
        )
        self._service_combo.setCurrentIndex(0)

    def _remove_line(self) -> None:
        rows = sorted({idx.row() for idx in self._table.selectedIndexes()}, reverse=True)
        for row in rows:
            self._table.removeRow(row)
        self._recalc()

    def _recalc(self) -> None:
        gst_rate = Decimal(self._context.setting_repo.get("gst_rate") or "0.0")
        subtotal = 0
        gst = 0
        total = 0
        for row in range(self._table.rowCount()):
            qty = self._int_at(row, 1, 1)
            price = self._cents_at(row, 3)
            discount = self._discount_cents_at(row, qty, price)
            taxable = self._item_check(row, 4)
            s, g, t = calculate_line_total(qty, price, discount, taxable, gst_rate)
            self._set_item_text(row, 6, f"${t / 100:.2f}")
            subtotal += s
            gst += g
            total += t
        self._subtotal_lbl.setText(f"Subtotal: ${subtotal / 100:.2f}")
        self._gst_lbl.setText(f"GST: ${gst / 100:.2f}")
        self._total_lbl.setText(f"Total: ${total / 100:.2f}")

    def _int_at(self, row: int, col: int, default: int) -> int:
        try:
            return int(self._item_text(row, col) or default)
        except (ValueError, AttributeError):
            return default

    def _cents_at(self, row: int, col: int) -> int:
        try:
            return int(Decimal(self._item_text(row, col) or "0") * 100)
        except Exception:
            return 0

    def _discount_cents_at(self, row: int, quantity: int, unit_price_cents: int) -> int:
        return calculate_discount_cents(self._item_text(row, 5), quantity, unit_price_cents)

    def _item_text(self, row: int, col: int, default: str = "") -> str:
        item = self._table.item(row, col)
        return item.text() if item is not None else default

    def _unit_text(self, row: int) -> str:
        widget = self._table.cellWidget(row, 2)
        if isinstance(widget, QComboBox):
            return widget.currentText().strip()
        item = self._table.item(row, 2)
        return item.text().strip() if item is not None else ""

    def _item_check(self, row: int, col: int) -> bool:
        item = self._table.item(row, col)
        return item.checkState() == Qt.CheckState.Checked if item is not None else False

    def _set_item_text(self, row: int, col: int, text: str) -> None:
        item = self._table.item(row, col)
        if item is not None:
            item.setText(text)

    def _collect_lines(self) -> list[dict[str, Any]]:
        lines = []
        for row in range(self._table.rowCount()):
            lines.append(
                {
                    "description": self._item_text(row, 0) or "Item",
                    "quantity": self._int_at(row, 1, 1),
                    "unit": self._unit_text(row) or "ea",
                    "unit_price_cents": self._cents_at(row, 3),
                    "discount_cents": self._discount_cents_at(
                        row, self._int_at(row, 1, 1), self._cents_at(row, 3)
                    ),
                    "taxable": self._item_check(row, 4),
                }
            )
        return lines

    def _selected_due_date(self) -> date | None:
        if self._due_date_na.isChecked() or self._document_type.currentText() == "Quote":
            return None
        return cast(date, self._due_date.date().toPython())

    def _prepare_invoice(self) -> Invoice | None:
        lines = self._collect_lines()
        if not lines or all(line["unit_price_cents"] == 0 for line in lines):
            QMessageBox.warning(self, "No lines", "Add at least one priced line item.")
            return None
        if self._invoice is None:
            client_id = self._client.currentData()
            client_name = self._client.currentText().strip()
            if not client_name:
                QMessageBox.warning(self, "No client", "Enter or select a client name.")
                return None
            invoice_date = cast(date, self._issue_date.date().toPython())
            due_date = self._selected_due_date()
            notes = self._notes.toPlainText().strip() or None
            if client_id is None:
                self._invoice = self._context.invoice_service.create_custom_draft(
                    client_name=client_name,
                    client_address=self._client_address.text().strip() or None,
                    invoice_date=invoice_date,
                    due_date=due_date,
                    notes=notes,
                )
            else:
                self._invoice = self._context.invoice_service.create_draft(
                    client_id=int(client_id),
                    invoice_date=invoice_date,
                    due_date=due_date,
                    notes=notes,
                )
        self._context.invoice_service.update_invoice(
            self._invoice,
            cast(date, self._issue_date.date().toPython()),
            self._selected_due_date(),
            self._notes.toPlainText().strip() or None,
            lines,
        )
        return self._invoice

    def _update_existing(self) -> Invoice | None:
        return self._prepare_invoice()

    def _save_draft(self) -> None:
        invoice = self._prepare_invoice()
        if invoice:
            self._context.session.commit()
            QMessageBox.information(self, "Draft saved", f"Saved {invoice.number}")
            self.accept()

    def _issue(self) -> None:
        invoice = self._prepare_invoice()
        if invoice is None:
            return
        if invoice.is_draft:
            if self._document_type.currentText() == "Quote":
                self._context.invoice_service.issue_quote(invoice)
            else:
                self._context.invoice_service.issue(invoice)
        self._context.session.commit()
        self._generate_pdf(invoice)
        self.accept()

    def _upgrade_to_invoice(self) -> None:
        invoice = self._prepare_invoice()
        if invoice is None:
            return
        try:
            self._context.invoice_service.convert_quote_to_invoice(invoice)
            self._context.session.commit()
            self._generate_pdf(invoice)
            self.accept()
        except Exception as exc:  # noqa: BLE001
            self._context.session.rollback()
            QMessageBox.warning(self, "Upgrade failed", str(exc))

    def _update(self) -> None:
        invoice = self._update_existing()
        if invoice is None:
            return
        self._context.session.commit()
        self._generate_pdf(invoice)
        self.accept()

    def _generate_pdf(self, invoice: Invoice) -> None:
        try:
            settings = self._document_settings()
            folder = "quotes" if invoice.is_quote else "invoices"
            pdf_path = (
                self._context.config.get_documents_directory()
                / folder
                / str(cast(date, invoice.issue_date).year)
                / f"{invoice.number}.pdf"
            )
            if invoice.is_quote:
                generate_quote_pdf(invoice, settings, pdf_path)
            else:
                generate_invoice_pdf(invoice, settings, pdf_path)
            invoice.pdf_path = str(pdf_path)
            self._context.session.commit()
            os.startfile(str(pdf_path))
            doc_label = "Quote" if invoice.is_quote else "Invoice"
            QMessageBox.information(
                self, "Saved", f"{doc_label} {invoice.number} updated and PDF saved."
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "PDF failed", str(exc))

    def _build_actions_menu(self) -> QMenu:
        menu = QMenu(self)
        inv = self._invoice
        assert inv is not None
        is_quote = inv.is_quote

        menu.addAction("Open PDF", self._open_pdf)
        menu.addAction("Regenerate PDF", self._regenerate_pdf)
        menu.addAction("Generate Excel", self._generate_xlsx)
        menu.addAction("Generate Word", self._generate_docx)
        if not is_quote:
            menu.addAction("Generate reminder", self._generate_reminder)
        menu.addSeparator()
        if not is_quote:
            menu.addAction("Record payment", self._record_payment)
            menu.addAction("Issue receipt", self._issue_receipt)
            menu.addAction("Credit note", self._credit_note)
            menu.addAction("Write off balance", self._write_off_balance)
            menu.addSeparator()
        menu.addAction("Duplicate" if is_quote else "Duplicate invoice", self._duplicate_invoice)
        menu.addAction("View history", self._view_history)
        menu.addSeparator()
        menu.addAction("Retract to draft", self._retract_invoice)
        menu.addAction("Reissue", self._reissue_invoice)
        menu.addAction("Cancel", self._cancel_invoice)
        menu.addAction("Void", self._void_invoice)
        return menu

    def _document_settings(self) -> dict[str, Any]:
        keys = [
            "business_name",
            "business_address",
            "gst_rate",
            "bank_name",
            "bank_bsb",
            "bank_account",
            "bank_account_name",
            "thank_you_note",
        ] + [
            "invoice_title_tax",
            "invoice_title",
            "invoice_date_label",
            "invoice_due_date_label",
            "invoice_due_date_na_text",
            "invoice_client_label",
            "invoice_address_label",
            "invoice_description_header",
            "invoice_qty_header",
            "invoice_unit_header",
            "invoice_price_header",
            "invoice_gst_header",
            "invoice_total_header",
            "invoice_subtotal_label",
            "invoice_gst_label",
            "invoice_total_label",
            "invoice_amount_paid_label",
            "invoice_balance_due_label",
            "invoice_payment_details_label",
            "invoice_bank_label",
            "invoice_bsb_label",
            "invoice_account_label",
            "invoice_account_name_label",
            "invoice_notes_label",
            "invoice_thank_you",
            "invoice_payment_terms_note",
            "invoice_gst_footer_note",
        ] + [
            "quote_title",
            "quote_title_tax",
            "quote_date_label",
            "quote_due_date_label",
            "quote_due_date_na_text",
            "quote_subtotal_label",
            "quote_gst_label",
            "quote_total_label",
            "quote_amount_paid_label",
            "quote_balance_due_label",
            "quote_payment_details_label",
            "quote_bank_label",
            "quote_bsb_label",
            "quote_account_label",
            "quote_account_name_label",
            "quote_notes_label",
            "quote_thank_you",
            "quote_footer_note",
        ]
        return {k: self._context.setting_repo.get(k) for k in keys}

    def _document_path(self, folder: str, ext: str) -> Path:
        assert self._invoice is not None
        return (
            self._context.config.get_documents_directory()
            / folder
            / str(cast(date, self._invoice.issue_date).year)
            / f"{self._invoice.number}.{ext}"
        )

    def _open_pdf(self) -> None:
        assert self._invoice is not None
        if not self._invoice.pdf_path:
            label = "quote" if self._invoice.is_quote else "invoice"
            QMessageBox.information(self, "No PDF", f"This {label} does not have a PDF yet.")
            return
        path = Path(self._invoice.pdf_path)
        if not path.exists():
            QMessageBox.warning(self, "Missing", f"PDF not found: {path}")
            return
        os.startfile(str(path))

    def _regenerate_pdf(self) -> None:
        assert self._invoice is not None
        if self._invoice.is_draft:
            QMessageBox.information(self, "Not issued", "Draft documents do not have a PDF.")
            return
        try:
            folder = "quotes" if self._invoice.is_quote else "invoices"
            pdf_path = self._document_path(folder, "pdf")
            if self._invoice.is_quote:
                generate_quote_pdf(self._invoice, self._document_settings(), pdf_path)
            else:
                generate_invoice_pdf(self._invoice, self._document_settings(), pdf_path)
            self._invoice.pdf_path = str(pdf_path)
            self._context.session.commit()
            os.startfile(str(pdf_path))
            QMessageBox.information(self, "PDF regenerated", f"Saved {pdf_path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "PDF failed", str(exc))

    def _generate_xlsx(self) -> None:
        assert self._invoice is not None
        if self._invoice.is_draft:
            QMessageBox.information(self, "Not issued", "Draft documents cannot be exported.")
            return
        try:
            folder = "quotes" if self._invoice.is_quote else "invoices"
            xlsx_path = self._document_path(folder, "xlsx")
            if self._invoice.is_quote:
                generate_quote_xlsx(self._invoice, self._document_settings(), xlsx_path)
            else:
                generate_invoice_xlsx(self._invoice, self._document_settings(), xlsx_path)
            os.startfile(str(xlsx_path))
            QMessageBox.information(self, "Excel saved", f"Saved {xlsx_path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Excel failed", str(exc))

    def _generate_docx(self) -> None:
        assert self._invoice is not None
        if self._invoice.is_draft:
            QMessageBox.information(self, "Not issued", "Draft documents cannot be exported.")
            return
        try:
            folder = "quotes" if self._invoice.is_quote else "invoices"
            docx_path = self._document_path(folder, "docx")
            if self._invoice.is_quote:
                generate_quote_docx(self._invoice, self._document_settings(), docx_path)
            else:
                generate_invoice_docx(self._invoice, self._document_settings(), docx_path)
            os.startfile(str(docx_path))
            QMessageBox.information(self, "Word saved", f"Saved {docx_path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Word failed", str(exc))

    def _generate_reminder(self) -> None:
        assert self._invoice is not None
        if self._invoice.is_quote:
            QMessageBox.information(self, "Cannot remind", "Reminders are not sent for quotes.")
            return
        if self._invoice.is_draft or self._invoice.is_void or self._invoice.is_cancelled:
            QMessageBox.information(
                self, "Cannot remind", "Only issued invoices can receive reminders."
            )
            return
        settings = {
            k: self._context.setting_repo.get(k)
            for k in [
                "business_name",
                "business_address",
                "bank_name",
                "bank_bsb",
                "bank_account",
                "bank_account_name",
                "report_footer",
            ]
        }
        try:
            reminder_path = self._document_path("reminders", "pdf")
            generate_reminder_pdf(self._invoice, settings, reminder_path)
            os.startfile(str(reminder_path))
            QMessageBox.information(self, "Reminder saved", f"Saved {reminder_path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Reminder failed", str(exc))

    def _record_payment(self) -> None:
        from invoice_manager.ui.payments_page import RecordPaymentDialog

        assert self._invoice is not None
        if self._invoice.is_quote:
            QMessageBox.information(self, "Cannot record payment", "Payments cannot be recorded against quotes.")
            return
        dlg = RecordPaymentDialog(self._context, invoice=self._invoice, parent=self)
        if dlg.exec() == 1:
            self.accept()

    def _issue_receipt(self) -> None:
        from invoice_manager.ui.payments_page import IssueReceiptDialog

        assert self._invoice is not None
        if self._invoice.is_quote:
            QMessageBox.information(self, "Cannot issue receipt", "Receipts cannot be issued for quotes.")
            return
        dlg = IssueReceiptDialog(self._context, self._invoice, parent=self)
        if dlg.exec() == 1:
            self.accept()

    def _credit_note(self) -> None:
        from invoice_manager.ui.credit_note_dialog import CreditNoteDialog

        assert self._invoice is not None
        if self._invoice.is_quote:
            QMessageBox.information(self, "Cannot credit", "Credit notes cannot be applied to quotes.")
            return
        dlg = CreditNoteDialog(self._context, self._invoice, parent=self)
        if dlg.exec() == 1:
            self.accept()

    def _write_off_balance(self) -> None:
        assert self._invoice is not None
        if self._invoice.is_quote:
            QMessageBox.information(self, "Cannot write off", "Quotes cannot be written off.")
            return
        if self._invoice.is_draft or self._invoice.is_void or self._invoice.is_cancelled:
            QMessageBox.information(
                self, "Cannot write off", "Only issued invoices can be written off."
            )
            return
        balance = (
            self._invoice.total_cents
            - sum(p.amount_cents for p in self._invoice.payments if not p.is_reversed)
            - sum(c.amount_cents for c in self._invoice.credits)
        )
        if balance <= 0:
            QMessageBox.information(self, "No balance", "This invoice has no outstanding balance.")
            return
        reason, ok = QInputDialog.getText(
            self, "Write off balance", f"Reason for writing off {Money(cents=balance)}:"
        )
        if not ok or not reason.strip():
            return
        try:
            self._context.invoice_service.add_credit_note(
                self._invoice, balance, reason.strip(), date.today()
            )
            self._context.session.commit()
            self.accept()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Write-off failed", str(exc))

    def _duplicate_invoice(self) -> None:
        assert self._invoice is not None
        try:
            self._context.invoice_service.clone_invoice(self._invoice)
            self._context.session.commit()
            self.accept()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Duplicate failed", str(exc))

    def _view_history(self) -> None:
        assert self._invoice is not None
        dlg = InvoiceHistoryDialog(self._context, self._invoice, parent=self)
        dlg.exec()

    def _retract_invoice(self) -> None:
        assert self._invoice is not None
        if self._invoice.is_draft or self._invoice.is_void or self._invoice.is_cancelled:
            label = "quote" if self._invoice.is_quote else "invoice"
            QMessageBox.information(self, "Cannot retract", f"Only issued {label}s can be retracted.")
            return
        try:
            self._context.invoice_service.retract(self._invoice)
            self._context.session.commit()
            self.accept()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Retract failed", str(exc))

    def _reissue_invoice(self) -> None:
        assert self._invoice is not None
        if self._invoice.is_draft or self._invoice.is_void or self._invoice.is_cancelled:
            label = "quote" if self._invoice.is_quote else "invoice"
            QMessageBox.information(self, "Cannot reissue", f"Only issued {label}s can be reissued.")
            return
        try:
            self._context.invoice_service.reissue(self._invoice)
            self._context.session.commit()
            self.accept()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Reissue failed", str(exc))

    def _cancel_invoice(self) -> None:
        assert self._invoice is not None
        if self._invoice.is_draft or self._invoice.is_void or self._invoice.is_cancelled:
            label = "Quote" if self._invoice.is_quote else "Invoice"
            QMessageBox.information(self, "Cannot cancel", f"This {label.lower()} cannot be cancelled.")
            return
        label = "Quote" if self._invoice.is_quote else "Invoice"
        reason, ok = QInputDialog.getText(self, f"Cancel {label.lower()}", "Reason for cancellation:")
        if not ok or not reason.strip():
            return
        try:
            self._context.invoice_service.cancel(self._invoice, reason.strip())
            self._context.session.commit()
            self.accept()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Cancel failed", str(exc))

    def _void_invoice(self) -> None:
        assert self._invoice is not None
        if self._invoice.is_draft or self._invoice.is_void or self._invoice.is_cancelled:
            label = "Quote" if self._invoice.is_quote else "Invoice"
            QMessageBox.information(self, "Cannot void", f"This {label.lower()} cannot be voided.")
            return
        label = "Quote" if self._invoice.is_quote else "Invoice"
        reason, ok = QInputDialog.getText(self, f"Void {label.lower()}", "Reason for voiding:")
        if not ok or not reason.strip():
            return
        try:
            self._context.invoice_service.void(self._invoice, reason.strip())
            self._context.session.commit()
            self.accept()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Void failed", str(exc))
