"""Main application window with a left navigation rail."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenuBar,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from invoice_manager.application.backup_service import BackupService, BackupServiceError
from invoice_manager.application.export_service import DataExportService, DataExportServiceError
from invoice_manager.documents.accountant_pack_pdf import generate_accountant_pack_pdf
from invoice_manager.documents.blank_invoice_docx import generate_blank_invoice_docx
from invoice_manager.domain.tax_year import TaxYear
from invoice_manager.infrastructure.config import AppConfig
from invoice_manager.infrastructure.logging_setup import get_logger
from invoice_manager.ui.app_context import AppContext
from invoice_manager.ui.clients_page import ClientsPage
from invoice_manager.ui.dashboard_page import DashboardPage
from invoice_manager.ui.invoice_editor import InvoiceEditorDialog
from invoice_manager.ui.invoice_list import InvoiceListPage
from invoice_manager.ui.ledger_page import LedgerPage
from invoice_manager.ui.migration_wizard import MigrationWizard
from invoice_manager.ui.payments_page import PaymentsPage
from invoice_manager.ui.reports_page import ReportsPage
from invoice_manager.ui.service_items_page import ServiceItemsPage
from invoice_manager.ui.settings_dialog import SettingsDialog

_log = get_logger("invoice_manager.ui.main_window")

_NAV_ITEMS = [
    "Dashboard",
    "New Invoice",
    "Invoices",
    "Payments & Receipts",
    "Clients",
    "Products & Services",
    "Income & Expenses",
    "Reports",
]


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig, current_user: str) -> None:
        super().__init__()
        self._config = config
        self._current_user = current_user
        self._context = AppContext(config, current_user)
        self.setWindowTitle("Invoice & Receipt Manager")
        self.setMinimumSize(1200, 800)
        self._build_ui()
        self._start_backup_scheduler()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Left nav rail
        nav_container = QWidget()
        nav_container.setFixedWidth(200)
        nav_layout = QVBoxLayout(nav_container)
        nav_layout.setContentsMargins(8, 8, 8, 8)

        self._nav = QListWidget()
        for label in _NAV_ITEMS:
            item = QListWidgetItem(label)
            item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            self._nav.addItem(item)
        self._nav.setCurrentRow(0)
        self._nav.currentRowChanged.connect(self._on_nav_changed)
        nav_layout.addWidget(self._nav)

        self._status_label = QLabel(f"User: {self._current_user}")
        self._status_label.setWordWrap(True)
        nav_layout.addWidget(self._status_label)

        layout.addWidget(nav_container)

        # Content area
        self._stack = QStackedWidget()
        self._pages: list[QWidget] = []
        self._invoices_page: InvoiceListPage | None = None
        for label in _NAV_ITEMS:
            page = self._create_page(label)
            self._pages.append(page)
            self._stack.addWidget(page)
            if isinstance(page, InvoiceListPage):
                self._invoices_page = page
        layout.addWidget(self._stack, stretch=1)
        self._context.data_changed.connect(self._refresh_all_pages)

        self._build_menu()

    def _create_page(self, label: str) -> QWidget:
        if label == "Dashboard":
            return DashboardPage(self._context)
        if label == "Invoices":
            return InvoiceListPage(self._context)
        if label == "Payments & Receipts":
            return PaymentsPage(self._context)
        if label == "Clients":
            return ClientsPage(self._context)
        if label == "Products & Services":
            return ServiceItemsPage(self._context)
        if label == "Income & Expenses":
            return LedgerPage(self._context)
        if label == "Reports":
            return ReportsPage(self._context)
        return self._placeholder_page(label)

    def _placeholder_page(self, label: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel(f"<h1>{label}</h1><p>This screen is under construction.</p>"))
        layout.addStretch()
        return page

    def _refresh_all_pages(self) -> None:
        for page in self._pages:
            refresh = getattr(page, "refresh", None)
            if callable(refresh):
                refresh()

    def _on_nav_changed(self, index: int) -> None:
        label = _NAV_ITEMS[index]
        if label == "New Invoice":
            self._open_new_invoice()
            self._nav.setCurrentRow(2)
            return
        self._stack.setCurrentIndex(index)
        page = self._pages[index]
        if hasattr(page, "refresh"):
            page.refresh()

    def _build_menu(self) -> None:
        menu_bar = QMenuBar(self)

        invoices_menu = menu_bar.addMenu("Invoices")
        new_inv_action = invoices_menu.addAction("New Invoice")
        new_inv_action.triggered.connect(self._open_new_invoice)
        new_quote_action = invoices_menu.addAction("New Quote")
        new_quote_action.triggered.connect(self._open_new_quote)
        edit_inv_action = invoices_menu.addAction("Modify selected")
        edit_inv_action.triggered.connect(self._modify_selected_invoice)
        retract_inv_action = invoices_menu.addAction("Retract to draft")
        retract_inv_action.triggered.connect(self._retract_selected_invoice)
        reissue_inv_action = invoices_menu.addAction("Reissue")
        reissue_inv_action.triggered.connect(self._reissue_selected_invoice)
        credit_inv_action = invoices_menu.addAction("Credit note")
        credit_inv_action.triggered.connect(self._credit_note_selected_invoice)
        cancel_inv_action = invoices_menu.addAction("Cancel selected")
        cancel_inv_action.triggered.connect(self._cancel_selected_invoice)
        void_inv_action = invoices_menu.addAction("Void selected")
        void_inv_action.triggered.connect(self._void_selected_invoice)
        regen_inv_action = invoices_menu.addAction("Regenerate PDF")
        regen_inv_action.triggered.connect(self._regenerate_pdf_selected_invoice)
        open_inv_action = invoices_menu.addAction("Open PDF")
        open_inv_action.triggered.connect(self._open_pdf_selected_invoice)
        invoices_menu.addSeparator()
        record_payment_action = invoices_menu.addAction("Record payment")
        record_payment_action.triggered.connect(self._record_payment_selected_invoice)
        issue_receipt_action = invoices_menu.addAction("Issue receipt")
        issue_receipt_action.triggered.connect(self._issue_receipt_selected_invoice)

        tools_menu = menu_bar.addMenu("Tools")
        import_action = tools_menu.addAction("Import / Migrate")
        import_action.triggered.connect(self._open_migration_wizard)
        accountant_action = tools_menu.addAction("Accountant pack...")
        accountant_action.triggered.connect(self._generate_accountant_pack)
        export_action = tools_menu.addAction("Export all data...")
        export_action.triggered.connect(self._export_all_data)
        blank_word_action = tools_menu.addAction("Blank invoice (Word)...")
        blank_word_action.triggered.connect(self._generate_blank_invoice_word)
        tools_menu.addSeparator()
        backup_action = tools_menu.addAction("Backup now")
        backup_action.triggered.connect(self._backup_now)
        restore_action = tools_menu.addAction("Restore from backup...")
        restore_action.triggered.connect(self._restore_backup)
        tools_menu.addSeparator()
        settings_action = tools_menu.addAction("Settings")
        settings_action.triggered.connect(self._open_settings)
        self.setMenuBar(menu_bar)

    def _open_migration_wizard(self) -> None:
        wizard = MigrationWizard(self._config, parent=self)
        wizard.exec()

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self._context, parent=self)
        dlg.exec()

    def _open_new_invoice(self) -> None:
        dlg = InvoiceEditorDialog(self._context, parent=self)
        if dlg.exec() == 1 and self._invoices_page is not None:
            self._invoices_page.refresh()

    def _open_new_quote(self) -> None:
        dlg = InvoiceEditorDialog(self._context, parent=self)
        if hasattr(dlg, "_document_type"):
            dlg._document_type.setCurrentText("Quote")
        if dlg.exec() == 1 and self._invoices_page is not None:
            self._invoices_page.refresh()

    def _with_selected_invoice(self, action: str, method_name: str) -> None:
        if self._invoices_page is None:
            return
        inv = self._invoices_page.selected_invoice()
        if inv is None:
            QMessageBox.information(self, "Select invoice", f"Select an invoice to {action}.")
            return
        self._stack.setCurrentWidget(self._invoices_page)
        getattr(self._invoices_page, method_name)()

    def _modify_selected_invoice(self) -> None:
        self._with_selected_invoice("modify", "modify_selected")

    def _retract_selected_invoice(self) -> None:
        self._with_selected_invoice("retract", "retract_selected")

    def _reissue_selected_invoice(self) -> None:
        self._with_selected_invoice("reissue", "reissue_selected")

    def _credit_note_selected_invoice(self) -> None:
        self._with_selected_invoice("credit", "credit_note_selected")

    def _cancel_selected_invoice(self) -> None:
        self._with_selected_invoice("cancel", "cancel_selected")

    def _void_selected_invoice(self) -> None:
        self._with_selected_invoice("void", "void_selected")

    def _regenerate_pdf_selected_invoice(self) -> None:
        self._with_selected_invoice("regenerate PDF", "regenerate_selected_pdf")

    def _open_pdf_selected_invoice(self) -> None:
        self._with_selected_invoice("open PDF", "open_selected_pdf")

    def _record_payment_selected_invoice(self) -> None:
        self._with_selected_invoice("record payment", "record_payment_selected")

    def _issue_receipt_selected_invoice(self) -> None:
        self._with_selected_invoice("issue receipt", "issue_receipt_selected")

    def _generate_accountant_pack(self) -> None:
        start_month = self._context.setting_repo.get_int("financial_year_start_month", 7)
        current_fy = TaxYear(start_month).current()
        fy, ok = QInputDialog.getText(
            self,
            "Accountant Pack",
            "Financial year (e.g. 2025-2026):",
            text=current_fy,
        )
        if not ok or not fy.strip():
            return
        default_name = f"accountant_pack_{fy.strip()}.pdf"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save accountant pack",
            str(self._context.config.get_exports_directory() / default_name),
            "PDF files (*.pdf)",
        )
        if not path:
            return
        try:
            settings = {
                k: self._context.setting_repo.get(k)
                for k in [
                    "business_name",
                    "business_abn",
                    "currency_symbol",
                    "report_header_colour",
                    "report_stripe_colour",
                    "gst_rate",
                    "financial_year_start_month",
                ]
            }
            generate_accountant_pack_pdf(Path(path), fy.strip(), self._context, settings)
            os.startfile(str(path))
            QMessageBox.information(self, "Accountant pack", f"Saved: {path}")
        except Exception as exc:  # noqa: BLE001
            _log.exception("Accountant pack failed: %s", exc)
            QMessageBox.warning(self, "Accountant pack failed", str(exc))

    def _export_all_data(self) -> None:
        default_name = f"invoice_manager_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export all data",
            str(self._context.config.get_exports_directory() / default_name),
            "Zip files (*.zip)",
        )
        if not path:
            return
        try:
            service = DataExportService(self._context.config, self._context.session)
            archive = service.export_all(Path(path))
            QMessageBox.information(self, "Export complete", f"Saved: {archive}")
        except DataExportServiceError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))

    def _generate_blank_invoice_word(self) -> None:
        default_name = "blank_invoice.docx"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save blank invoice",
            str(self._context.config.get_exports_directory() / default_name),
            "Word documents (*.docx)",
        )
        if not path:
            return
        settings = {k: self._context.setting_repo.get(k) for k in self._invoice_settings_keys()}
        try:
            generate_blank_invoice_docx(settings, Path(path))
            QMessageBox.information(self, "Blank invoice", f"Saved: {path}")
        except Exception as exc:  # noqa: BLE001
            _log.exception("Blank invoice failed: %s", exc)
            QMessageBox.warning(self, "Blank invoice failed", str(exc))

    def _invoice_settings_keys(self) -> list[str]:
        return [
            "business_name",
            "business_address",
            "gst_rate",
            "bank_name",
            "bank_bsb",
            "bank_account",
            "bank_account_name",
            "invoice_title_tax",
            "invoice_title",
            "invoice_date_label",
            "invoice_due_date_label",
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
            "invoice_payment_details_label",
            "invoice_bank_label",
            "invoice_bsb_label",
            "invoice_account_label",
            "invoice_account_name_label",
            "invoice_notes_label",
            "invoice_thank_you",
        ]

    def _start_backup_scheduler(self) -> None:
        self._backup_if_due()
        self._backup_timer = QTimer(self)
        self._backup_timer.timeout.connect(self._backup_if_due)
        self._backup_timer.start(15 * 60 * 1000)

    def _backup_if_due(self) -> None:
        if self._context.config.database_mode() != "sqlite":
            return
        try:
            service = BackupService(
                self._context.config.get_data_directory(),
                self._context.config.get_backup_directory(),
                self._context.setting_repo,
            )
            if service.backup_if_due():
                _log.info("Scheduled backup completed")
        except Exception:  # noqa: BLE001
            _log.exception("Scheduled backup failed")

    def _backup_on_exit(self) -> None:
        if self._context.config.database_mode() != "sqlite":
            return
        try:
            service = BackupService(
                self._context.config.get_data_directory(),
                self._context.config.get_backup_directory(),
                self._context.setting_repo,
            )
            if service.backup_on_exit():
                _log.info("Exit backup completed")
        except Exception:  # noqa: BLE001
            _log.exception("Exit backup failed")

    def _backup_now(self) -> None:
        if self._context.config.database_mode() != "sqlite":
            QMessageBox.information(
                self,
                "Remote database",
                "File backup is unavailable for MySQL. Use Export all data for an application-level backup and configure server backups with your database provider.",
            )
            return
        try:
            service = BackupService(
                self._context.config.get_data_directory(),
                self._context.config.get_backup_directory(),
                self._context.setting_repo,
            )
            path = service.backup()
            service.prune()
            QMessageBox.information(self, "Backup complete", f"Saved: {path}")
        except BackupServiceError as exc:
            QMessageBox.warning(self, "Backup failed", str(exc))

    def _restore_backup(self) -> None:
        if self._context.config.database_mode() != "sqlite":
            QMessageBox.information(
                self,
                "Remote database",
                "Raw restore is unavailable for MySQL. Restore the server database through your database provider.",
            )
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select backup zip",
            str(self._context.config.get_backup_directory()),
            "Zip files (*.zip)",
        )
        if not path:
            return
        reply = QMessageBox.question(
            self,
            "Confirm restore",
            "This will overwrite the current data with the backup.\nA safety copy will be made first. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            service = BackupService(
                self._context.config.get_data_directory(),
                self._context.config.get_backup_directory(),
            )
            service.restore(Path(path))
            QMessageBox.information(self, "Restore complete", "Please restart the application.")
        except BackupServiceError as exc:
            QMessageBox.critical(self, "Restore failed", str(exc))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._backup_on_exit()
        self._context.session.close()
        self._context.database.engine.dispose()
        event.accept()
