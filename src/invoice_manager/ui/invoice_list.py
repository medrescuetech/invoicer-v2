"""Invoice list page."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
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
from invoice_manager.domain.money import Money
from invoice_manager.domain.statuses import invoice_balance_cents
from invoice_manager.persistence.models import Invoice
from invoice_manager.ui.app_context import AppContext
from invoice_manager.ui.credit_note_dialog import CreditNoteDialog
from invoice_manager.ui.invoice_editor import InvoiceEditorDialog
from invoice_manager.ui.invoice_history_dialog import InvoiceHistoryDialog
from invoice_manager.ui.manual_invoice_dialog import ManualInvoiceDialog
from invoice_manager.ui.payments_page import IssueReceiptDialog, RecordPaymentDialog


class InvoiceListPage(QWidget):
    """Page showing issued invoices with actions."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._invoices: list[Invoice] = []
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Invoices"))

        toolbar = QHBoxLayout()
        new_btn = QPushButton("New Invoice")
        new_btn.clicked.connect(self._new_invoice)
        new_quote_btn = QPushButton("New Quote")
        new_quote_btn.clicked.connect(self._new_quote)
        manual_btn = QPushButton("Record Manual Invoice")
        manual_btn.clicked.connect(self._record_manual)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(new_btn)
        toolbar.addWidget(new_quote_btn)
        toolbar.addWidget(manual_btn)
        toolbar.addWidget(refresh_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        filter_bar = QHBoxLayout()
        self._filter_text = QLineEdit()
        self._filter_text.setPlaceholderText("Filter by number or client...")
        self._filter_text.textChanged.connect(self._apply_filter)
        self._status_filter = QComboBox()
        self._status_filter.addItem("All", None)
        for label, value in [
            ("Draft", "draft"),
            ("Quoted", "quoted"),
            ("Issued", "issued"),
            ("Part paid", "part_paid"),
            ("Paid", "paid"),
            ("Duplicate", "duplicate"),
            ("Overdue", "overdue"),
            ("Cancelled", "cancelled"),
            ("Void", "void"),
        ]:
            self._status_filter.addItem(label, value)
        self._status_filter.currentTextChanged.connect(self._apply_filter)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._clear_filter)
        filter_bar.addWidget(QLabel("Search:"))
        filter_bar.addWidget(self._filter_text)
        filter_bar.addWidget(QLabel("Status:"))
        filter_bar.addWidget(self._status_filter)
        filter_bar.addWidget(clear_btn)
        filter_bar.addStretch()
        layout.addLayout(filter_bar)

        self._table = QTableWidget(0, 8)
        self._table.setHorizontalHeaderLabels(
            ["Number", "Date", "Due", "Client", "Total", "Balance", "Status", "PDF"]
        )
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.doubleClicked.connect(self._edit_invoice)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self._table)

        action_bar = QHBoxLayout()
        edit_btn = QPushButton("Edit")
        edit_btn.clicked.connect(self._edit_invoice)
        dup_btn = QPushButton("Duplicate")
        dup_btn.clicked.connect(self._duplicate_invoice)
        upgrade_btn = QPushButton("Upgrade to Invoice")
        upgrade_btn.clicked.connect(self._upgrade_quote)
        history_btn = QPushButton("History")
        history_btn.clicked.connect(self._show_history)
        open_pdf_btn = QPushButton("Open PDF")
        open_pdf_btn.clicked.connect(self._open_pdf)
        xlsx_btn = QPushButton("Excel")
        xlsx_btn.clicked.connect(self._generate_xlsx)
        docx_btn = QPushButton("Word")
        docx_btn.clicked.connect(self._generate_docx)
        credit_btn = QPushButton("Credit note")
        credit_btn.clicked.connect(self._credit_note)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self._cancel_invoice)
        void_btn = QPushButton("Void")
        void_btn.clicked.connect(self._void_invoice)
        regen_btn = QPushButton("Regenerate PDF")
        regen_btn.clicked.connect(self._regenerate_pdf)
        action_bar.addWidget(edit_btn)
        action_bar.addWidget(dup_btn)
        action_bar.addWidget(upgrade_btn)
        action_bar.addWidget(history_btn)
        action_bar.addWidget(open_pdf_btn)
        action_bar.addWidget(xlsx_btn)
        action_bar.addWidget(docx_btn)
        action_bar.addWidget(credit_btn)
        action_bar.addWidget(cancel_btn)
        action_bar.addWidget(void_btn)
        action_bar.addWidget(regen_btn)
        action_bar.addStretch()
        layout.addLayout(action_bar)

    def refresh(self) -> None:
        self._all_invoices = list(self._context.invoice_service.list_invoices())
        self._apply_filter()

    def _balance(self, inv: Invoice) -> int:
        return invoice_balance_cents(inv)

    def _apply_filter(self) -> None:
        text = self._filter_text.text().strip().lower()
        status = self._status_filter.currentData()
        self._invoices = [
            inv
            for inv in self._all_invoices
            if (not text or text in inv.number.lower() or text in inv.client_name.lower())
            and (status is None or inv.status == status)
        ]
        self._table.setRowCount(len(self._invoices))
        na_text = self._context.setting_repo.get("invoice_due_date_na_text") or "N/A"
        for row, inv in enumerate(self._invoices):
            self._table.setItem(row, 0, QTableWidgetItem(inv.number))
            self._table.setItem(row, 1, QTableWidgetItem(str(inv.issue_date)))
            self._table.setItem(row, 2, QTableWidgetItem(str(inv.due_date) if inv.due_date else na_text))
            self._table.setItem(row, 3, QTableWidgetItem(inv.client_name))
            self._table.setItem(row, 4, QTableWidgetItem(f"${inv.total_cents / 100:.2f}"))
            self._table.setItem(row, 5, QTableWidgetItem(f"${self._balance(inv) / 100:.2f}"))
            status_combo = QComboBox()
            status_combo.addItem(inv.status.replace("_", " ").title(), inv.status)
            if inv.is_quote:
                if inv.is_draft:
                    status_combo.addItem("Issued", "issued")
                else:
                    status_combo.addItem("Draft", "draft")
                status_combo.addItem("Upgrade to invoice", "upgrade")
            elif inv.is_draft:
                status_combo.addItem("Issued", "issued")
            elif not inv.is_void and not inv.is_cancelled and inv.status != "duplicate":
                if not inv.payments and not inv.credits:
                    status_combo.addItem("Draft", "draft")
                if self._balance(inv) > 0:
                    status_combo.addItem("Paid", "paid")
                if not inv.payments and not inv.credits:
                    status_combo.addItem("Duplicate", "duplicate")
                status_combo.addItem("Cancelled", "cancelled")
                status_combo.addItem("Void", "void")
            status_combo.currentIndexChanged.connect(
                lambda _index, invoice=inv, combo=status_combo: self._change_status(invoice, combo)
            )
            self._table.setCellWidget(row, 6, status_combo)
            self._table.setItem(row, 7, QTableWidgetItem("Yes" if inv.pdf_path else "No"))

    def _change_status(self, invoice: Invoice, combo: QComboBox) -> None:
        if combo.currentIndex() == 0:
            return
        target = combo.currentData()
        try:
            if target == "issued":
                if invoice.is_quote:
                    self._context.invoice_service.issue_quote(invoice)
                else:
                    self._context.invoice_service.issue(invoice)
            elif target == "upgrade":
                self._context.invoice_service.convert_quote_to_invoice(invoice)
            elif target == "paid":
                dialog = RecordPaymentDialog(self._context, invoice=invoice, parent=self)
                if dialog.exec() != 1:
                    combo.setCurrentIndex(0)
                self.refresh()
                return
            elif target == "draft":
                self._context.invoice_service.retract(invoice)
            elif target == "duplicate":
                reason, ok = QInputDialog.getText(
                    self, "Mark duplicate", f"Reason {invoice.number} is a duplicate:"
                )
                if not ok or not reason.strip():
                    combo.setCurrentIndex(0)
                    return
                self._context.invoice_service.mark_duplicate(invoice, reason.strip())
            elif target in {"cancelled", "void"}:
                reason, ok = QInputDialog.getText(
                    self,
                    f"Mark {target}",
                    f"Reason for marking {invoice.number} {target}:",
                )
                if not ok or not reason.strip():
                    combo.setCurrentIndex(0)
                    return
                if target == "cancelled":
                    self._context.invoice_service.cancel(invoice, reason.strip())
                else:
                    self._context.invoice_service.void(invoice, reason.strip())
            self._context.session.commit()
        except Exception as exc:  # noqa: BLE001
            self._context.session.rollback()
            QMessageBox.warning(self, "Status change failed", str(exc))
        self.refresh()

    def _clear_filter(self) -> None:
        self._filter_text.clear()
        self._status_filter.setCurrentIndex(0)
        self._apply_filter()

    def _selected_invoice(self) -> Invoice | None:
        rows = self._table.selectedIndexes()
        if not rows:
            return None
        row = rows[0].row()
        return self._invoices[row]

    def _open_pdf(self) -> None:
        inv = self._selected_invoice()
        if inv is None or not inv.pdf_path:
            QMessageBox.information(self, "No PDF", "Select an invoice that has a PDF.")
            return
        path = Path(inv.pdf_path)
        if not path.exists():
            QMessageBox.warning(self, "Missing", f"PDF not found: {path}")
            return
        import os

        os.startfile(str(path))

    def _new_invoice(self) -> None:
        dlg = InvoiceEditorDialog(self._context, parent=self)
        if dlg.exec() == 1:
            self.refresh()

    def _new_quote(self) -> None:
        from invoice_manager.ui.invoice_editor import InvoiceEditorDialog
        dlg = InvoiceEditorDialog(self._context, parent=self)
        # Start the dialog in quote mode by selecting Quote before it is shown.
        if hasattr(dlg, "_document_type"):
            dlg._document_type.setCurrentText("Quote")
        if dlg.exec() == 1:
            self.refresh()

    def _record_manual(self) -> None:
        dlg = ManualInvoiceDialog(self._context, parent=self)
        if dlg.exec() == 1:
            self.refresh()

    def _edit_invoice(self) -> None:
        inv = self._selected_invoice()
        if inv is None:
            QMessageBox.information(self, "Select invoice", "Select an invoice or quote to edit.")
            return
        if inv.is_void or inv.is_cancelled:
            QMessageBox.information(
                self, "Cannot edit", "Void or cancelled documents cannot be edited."
            )
            return
        dlg = InvoiceEditorDialog(self._context, invoice=inv, parent=self)
        if dlg.exec() == 1:
            self.refresh()

    def _credit_note(self) -> None:
        inv = self._selected_invoice()
        if inv is None:
            QMessageBox.information(self, "Select invoice", "Select an invoice to credit.")
            return
        if inv.is_quote:
            QMessageBox.information(self, "Cannot credit", "Quotes cannot receive credit notes.")
            return
        if inv.is_draft or inv.is_void or inv.is_cancelled:
            QMessageBox.information(
                self, "Cannot credit", "Only issued invoices can receive a credit note."
            )
            return
        dlg = CreditNoteDialog(self._context, invoice=inv, parent=self)
        if dlg.exec() == 1:
            self.refresh()

    def _cancel_invoice(self) -> None:
        inv = self._selected_invoice()
        if inv is None:
            QMessageBox.information(self, "Select invoice", "Select an invoice to cancel.")
            return
        if inv.is_cancelled or inv.is_void or inv.is_draft:
            label = "Quote" if inv.is_quote else "Invoice"
            QMessageBox.information(
                self, "Cannot cancel", f"{label} is already cancelled, void, or a draft."
            )
            return
        label = "Quote" if inv.is_quote else "Invoice"
        reason, ok = QInputDialog.getText(self, f"Cancel {label}", "Reason for cancellation:")
        if not ok or not reason.strip():
            return
        try:
            self._context.invoice_service.cancel(inv, reason.strip())
            self._context.session.commit()
            self.refresh()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Cancel failed", str(exc))

    def _void_invoice(self) -> None:
        inv = self._selected_invoice()
        if inv is None:
            QMessageBox.information(self, "Select invoice", "Select an invoice to void.")
            return
        if inv.is_void or inv.is_cancelled or inv.is_draft:
            label = "Quote" if inv.is_quote else "Invoice"
            QMessageBox.information(
                self, "Cannot void", f"{label} is already void, cancelled, or a draft."
            )
            return
        label = "Quote" if inv.is_quote else "Invoice"
        reason, ok = QInputDialog.getText(self, f"Void {label}", "Reason for voiding:")
        if not ok or not reason.strip():
            return
        try:
            self._context.invoice_service.void(inv, reason.strip())
            self._context.session.commit()
            self.refresh()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Void failed", str(exc))

    def _generate_xlsx(self) -> None:
        inv = self._selected_invoice()
        if inv is None:
            QMessageBox.information(self, "Select invoice", "Select an invoice.")
            return
        if inv.is_draft:
            QMessageBox.information(self, "Not issued", "Draft documents cannot be exported.")
            return
        try:
            settings = self._document_settings()
            folder = "quotes" if inv.is_quote else "invoices"
            xlsx_path = (
                self._context.config.get_documents_directory()
                / folder
                / str(cast(date, inv.issue_date).year)
                / f"{inv.number}.xlsx"
            )
            if inv.is_quote:
                generate_quote_xlsx(inv, settings, xlsx_path)
            else:
                generate_invoice_xlsx(inv, settings, xlsx_path)
            os.startfile(str(xlsx_path))
            QMessageBox.information(self, "Excel saved", f"Saved {xlsx_path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Excel failed", str(exc))

    def _generate_docx(self) -> None:
        inv = self._selected_invoice()
        if inv is None:
            QMessageBox.information(self, "Select invoice", "Select an invoice.")
            return
        if inv.is_draft:
            QMessageBox.information(self, "Not issued", "Draft documents cannot be exported.")
            return
        try:
            settings = self._document_settings()
            folder = "quotes" if inv.is_quote else "invoices"
            docx_path = (
                self._context.config.get_documents_directory()
                / folder
                / str(cast(date, inv.issue_date).year)
                / f"{inv.number}.docx"
            )
            if inv.is_quote:
                generate_quote_docx(inv, settings, docx_path)
            else:
                generate_invoice_docx(inv, settings, docx_path)
            os.startfile(str(docx_path))
            QMessageBox.information(self, "Word saved", f"Saved {docx_path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Word failed", str(exc))

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

    def _regenerate_pdf(self) -> None:
        inv = self._selected_invoice()
        if inv is None:
            QMessageBox.information(self, "Select invoice", "Select an invoice.")
            return
        if inv.is_draft:
            QMessageBox.information(self, "Not issued", "Draft documents do not have a PDF.")
            return
        try:
            settings = self._document_settings()
            folder = "quotes" if inv.is_quote else "invoices"
            pdf_path = (
                self._context.config.get_documents_directory()
                / folder
                / str(cast(date, inv.issue_date).year)
                / f"{inv.number}.pdf"
            )
            if inv.is_quote:
                generate_quote_pdf(inv, settings, pdf_path)
            else:
                generate_invoice_pdf(inv, settings, pdf_path)
            inv.pdf_path = str(pdf_path)
            self._context.session.commit()
            os.startfile(str(pdf_path))
            QMessageBox.information(self, "PDF regenerated", f"Saved {pdf_path}")
            self.refresh()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "PDF failed", str(exc))

    def _show_history(self) -> None:
        inv = self._selected_invoice()
        if inv is None:
            QMessageBox.information(self, "Select invoice", "Select an invoice to view history.")
            return
        dlg = InvoiceHistoryDialog(self._context, invoice=inv, parent=self)
        dlg.exec()

    def _duplicate_invoice(self) -> None:
        inv = self._selected_invoice()
        if inv is None:
            QMessageBox.information(self, "Select invoice", "Select an invoice to duplicate.")
            return
        try:
            draft = self._context.invoice_service.clone_invoice(inv)
            self._context.session.commit()
            self.refresh()
            QMessageBox.information(
                self, "Duplicated", f"Created draft {draft.number} from {inv.number}."
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Duplicate failed", str(exc))

    def _upgrade_quote(self) -> None:
        inv = self._selected_invoice()
        if inv is None:
            QMessageBox.information(self, "Select quote", "Select a quote to upgrade.")
            return
        if not inv.is_quote:
            QMessageBox.information(self, "Not a quote", "Select a quote to upgrade.")
            return
        try:
            self._context.invoice_service.convert_quote_to_invoice(inv)
            self._context.session.commit()
            self.refresh()
            QMessageBox.information(self, "Upgraded", f"Quote upgraded to invoice {inv.number}.")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Upgrade failed", str(exc))

    def _generate_reminder(self) -> None:
        inv = self._selected_invoice()
        if inv is None:
            QMessageBox.information(self, "Select invoice", "Select an invoice.")
            return
        if inv.is_quote:
            QMessageBox.information(self, "Cannot remind", "Reminders are not sent for quotes.")
            return
        if inv.is_draft or inv.is_void or inv.is_cancelled:
            QMessageBox.information(
                self, "Cannot remind", "Only issued invoices can receive reminders."
            )
            return
        try:
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
            reminder_path = (
                self._context.config.get_documents_directory()
                / "reminders"
                / str(cast(date, inv.issue_date).year)
                / f"{inv.number}_reminder.pdf"
            )
            generate_reminder_pdf(inv, settings, reminder_path)
            os.startfile(str(reminder_path))
            QMessageBox.information(self, "Reminder saved", f"Saved {reminder_path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Reminder failed", str(exc))

    def _write_off_balance(self) -> None:
        inv = self._selected_invoice()
        if inv is None:
            QMessageBox.information(self, "Select invoice", "Select an invoice.")
            return
        if inv.is_quote:
            QMessageBox.information(self, "Cannot write off", "Quotes cannot be written off.")
            return
        if inv.is_draft or inv.is_void or inv.is_cancelled:
            QMessageBox.information(
                self, "Cannot write off", "Only issued invoices can be written off."
            )
            return
        balance = self._balance(inv)
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
                inv, balance, reason.strip(), date.today()
            )
            self._context.session.commit()
            self.refresh()
            QMessageBox.information(self, "Written off", f"Credited {Money(cents=balance)}.")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Write-off failed", str(exc))

    def selected_invoice(self) -> Invoice | None:
        return self._selected_invoice()

    def modify_selected(self) -> None:
        self._edit_invoice()

    def open_selected_pdf(self) -> None:
        self._open_pdf()

    def regenerate_selected_pdf(self) -> None:
        self._regenerate_pdf()

    def credit_note_selected(self) -> None:
        self._credit_note()

    def cancel_selected(self) -> None:
        self._cancel_invoice()

    def void_selected(self) -> None:
        self._void_invoice()

    def retract_selected(self) -> None:
        inv = self._selected_invoice()
        if inv is None:
            QMessageBox.information(self, "Select invoice", "Select an invoice to retract.")
            return
        if inv.is_draft or inv.is_void or inv.is_cancelled:
            label = "quote" if inv.is_quote else "invoice"
            QMessageBox.information(
                self, "Cannot retract", f"Only issued {label}s can be retracted."
            )
            return
        try:
            self._context.invoice_service.retract(inv)
            self._context.session.commit()
            self.refresh()
            QMessageBox.information(
                self, "Retracted", f"{inv.number} is now a draft and can be edited."
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Retract failed", str(exc))

    def reissue_selected(self) -> None:
        inv = self._selected_invoice()
        if inv is None:
            QMessageBox.information(self, "Select invoice", "Select an invoice to reissue.")
            return
        if not inv.is_draft:
            QMessageBox.information(self, "Cannot reissue", "Invoice is not a draft.")
            return
        try:
            self._context.invoice_service.reissue(inv)
            self._context.session.commit()
            self.refresh()
            QMessageBox.information(self, "Reissued", f"{inv.number} is now issued.")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Reissue failed", str(exc))

    def record_payment_selected(self) -> None:
        inv = self._selected_invoice()
        if inv is None:
            QMessageBox.information(self, "Select invoice", "Select an invoice to record payment for.")
            return
        if inv.is_quote:
            QMessageBox.information(self, "Cannot record payment", "Payments cannot be recorded against quotes.")
            return
        if inv.is_draft or inv.is_void or inv.is_cancelled:
            QMessageBox.information(
                self, "Cannot record payment", "Only issued invoices can receive payments."
            )
            return
        dlg = RecordPaymentDialog(self._context, invoice=inv, parent=self)
        if dlg.exec() == 1:
            self.refresh()

    def issue_receipt_selected(self) -> None:
        inv = self._selected_invoice()
        if inv is None:
            QMessageBox.information(self, "Select invoice", "Select an invoice to issue a receipt for.")
            return
        if inv.is_quote:
            QMessageBox.information(self, "Cannot issue receipt", "Receipts cannot be issued for quotes.")
            return
        if not inv.payments:
            QMessageBox.information(self, "No payments", "This invoice has no recorded payments.")
            return
        dlg = IssueReceiptDialog(self._context, invoice=inv, parent=self)
        if dlg.exec() == 1:
            self.refresh()

    def _context_menu(self, pos: Any) -> None:
        inv = self._selected_invoice()
        if inv is None:
            return
        menu = QMenu(self)
        menu.addAction("Edit", self._edit_invoice)
        menu.addAction("Duplicate", self._duplicate_invoice)
        menu.addAction("History", self._show_history)
        if inv.is_quote:
            menu.addAction("Upgrade to invoice", self._upgrade_quote)
        menu.addSeparator()
        if not inv.is_quote:
            menu.addAction("Record payment", self.record_payment_selected)
            menu.addAction("Issue receipt", self.issue_receipt_selected)
            menu.addAction("Credit note", self._credit_note)
            menu.addAction("Write off balance", self._write_off_balance)
            menu.addAction("Reminder", self._generate_reminder)
            menu.addSeparator()
        menu.addAction("Retract to draft", self.retract_selected)
        menu.addAction("Reissue", self.reissue_selected)
        menu.addAction("Cancel", self._cancel_invoice)
        menu.addAction("Void", self._void_invoice)
        menu.addSeparator()
        menu.addAction("Open PDF", self._open_pdf)
        menu.addAction("Regenerate PDF", self._regenerate_pdf)
        menu.addAction("Generate Excel", self._generate_xlsx)
        menu.addAction("Generate Word", self._generate_docx)
        menu.exec(self._table.viewport().mapToGlobal(pos))
