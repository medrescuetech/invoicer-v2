"""Settings and numbering configuration dialog."""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import URL

from invoice_manager.persistence.database import Database
from invoice_manager.ui.app_context import AppContext


class SettingsDialog(QDialog):
    """Edit business settings and document numbering."""

    _STRING_KEYS = [
        "business_name",
        "business_address",
        "business_abn",
        "business_phone",
        "business_email",
        "currency_symbol",
        "bank_name",
        "bank_bsb",
        "bank_account",
        "bank_account_name",
        "thank_you_note",
    ]

    _INVOICE_WORDING = [
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
    ]

    _INVOICE_DEFAULTS = {
        "invoice_title_tax": "TAX INVOICE",
        "invoice_title": "INVOICE",
        "invoice_date_label": "Date:",
        "invoice_due_date_label": "Due date:",
        "invoice_due_date_na_text": "N/A",
        "invoice_client_label": "Client:",
        "invoice_address_label": "Address:",
        "invoice_description_header": "Description",
        "invoice_qty_header": "Qty",
        "invoice_unit_header": "Unit",
        "invoice_price_header": "Price",
        "invoice_gst_header": "GST",
        "invoice_total_header": "Total",
        "invoice_subtotal_label": "Subtotal",
        "invoice_gst_label": "GST",
        "invoice_total_label": "Total",
        "invoice_amount_paid_label": "Amount Paid",
        "invoice_balance_due_label": "Balance Due",
        "invoice_payment_details_label": "Payment details",
        "invoice_bank_label": "Bank:",
        "invoice_bsb_label": "BSB:",
        "invoice_account_label": "Account:",
        "invoice_account_name_label": "Name:",
        "invoice_notes_label": "Notes:",
        "invoice_thank_you": "Thank you for your business!",
        "invoice_payment_terms_note": "Payment due within {days} days",
        "invoice_gst_footer_note": "GST Excluded - Supplier not registered for GST. This template is designed for Australian GST invoicing. For invoices of $1,000 or more (including GST), ensure the customer's identity is included. Do not use the words 'Tax Invoice' if you are not GST registered.",
    }

    _RECEIPT_WORDING = [
        "receipt_title",
        "receipt_invoice_label",
        "receipt_date_label",
        "receipt_amount_label",
        "receipt_method_label",
        "receipt_reference_label",
        "receipt_thank_you",
    ]

    _RECEIPT_DEFAULTS = {
        "receipt_title": "RECEIPT",
        "receipt_invoice_label": "Invoice:",
        "receipt_date_label": "Date:",
        "receipt_amount_label": "Amount:",
        "receipt_method_label": "Method:",
        "receipt_reference_label": "Reference:",
        "receipt_thank_you": "Thank you for your payment.",
    }

    _QUOTE_WORDING = [
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

    _QUOTE_DEFAULTS = {
        "quote_title": "QUOTE",
        "quote_title_tax": "TAX QUOTE",
        "quote_date_label": "Quote date:",
        "quote_due_date_label": "Valid until:",
        "quote_due_date_na_text": "N/A",
        "quote_subtotal_label": "Subtotal",
        "quote_gst_label": "GST",
        "quote_total_label": "Total",
        "quote_amount_paid_label": "Amount Paid",
        "quote_balance_due_label": "Balance Due",
        "quote_payment_details_label": "Payment details",
        "quote_bank_label": "Bank:",
        "quote_bsb_label": "BSB:",
        "quote_account_label": "Account:",
        "quote_account_name_label": "Name:",
        "quote_notes_label": "Notes:",
        "quote_thank_you": "Thank you for considering our services.",
        "quote_footer_note": "This is a quote, not an invoice. Prices are valid for 30 days unless otherwise stated.",
    }

    _DEFAULT_VALUES: dict[str, Any] = {
        "business_name": "Alexander Gillam",
        "business_address": "15 Dalkeith Drive, Point Cook",
        "business_abn": "73 421 221 580",
        "business_phone": "03 7057 3645",
        "business_email": "alex@gmedical.net.au",
        "currency_symbol": "$",
        "bank_name": "ANZ",
        "bank_bsb": "013202",
        "bank_account": "307415227",
        "bank_account_name": "AK Gillam",
        "thank_you_note": "Thank you for your business!",
        "gst_rate": "0.0",
        "payment_terms_days": 7,
        "financial_year_start_month": 7,
        "next_invoice_number": 1,
        "next_quote_number": 1,
        "next_receipt_number": 1,
        "next_credit_note_number": 1,
        "invoice_due_date_na_text": "N/A",
        "report_header_colour": "#2C3E50",
        "report_accent_colour": "#2980B9",
        "report_stripe_colour": "#EBF5FB",
        "report_footer": "",
        "pdf_save_mode": "Auto",
        "backup_enabled": False,
        "backup_frequency": 24,
        "backup_keep": 30,
        "backup_on_exit": False,
        "backup_folder": "",
        "default_taxable": False,
    }

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._fields: dict[str, QLineEdit] = {}
        self.setWindowTitle("Settings")
        self.setMinimumWidth(500)
        self._build_ui()
        self._load()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.setMinimumWidth(550)

        tabs = QTabWidget()

        # Business tab
        biz_group = QGroupBox("Business")
        biz_form = QFormLayout()
        for key in self._STRING_KEYS:
            edit = QLineEdit()
            biz_form.addRow(self._label(key), edit)
            self._fields[key] = edit
        self._gst_rate = QLineEdit()
        biz_form.addRow("GST rate (e.g. 0.10):", self._gst_rate)
        self._payment_terms = QSpinBox()
        self._payment_terms.setRange(0, 365)
        biz_form.addRow("Payment terms (days):", self._payment_terms)
        self._default_taxable = QCheckBox("New invoice lines are taxable")
        biz_form.addRow("Default taxable:", self._default_taxable)
        self._fy_start = QSpinBox()
        self._fy_start.setRange(1, 12)
        self._fy_start.setToolTip("Month number the financial year starts (e.g. 7 for July)")
        biz_form.addRow("Financial year start month:", self._fy_start)
        self._next_invoice = QSpinBox()
        self._next_invoice.setRange(1, 999999)
        biz_form.addRow("Next invoice number:", self._next_invoice)
        self._next_quote = QSpinBox()
        self._next_quote.setRange(1, 999999)
        biz_form.addRow("Next quote number:", self._next_quote)
        self._next_receipt = QSpinBox()
        self._next_receipt.setRange(1, 999999)
        biz_form.addRow("Next receipt number:", self._next_receipt)
        self._next_credit_note = QSpinBox()
        self._next_credit_note.setRange(1, 999999)
        biz_form.addRow("Next credit note number:", self._next_credit_note)
        biz_group.setLayout(biz_form)
        tabs.addTab(biz_group, "Business")

        # Reports / PDF tab
        report_group = QGroupBox("Reports & PDF")
        report_form = QFormLayout()
        self._report_header_colour = QLineEdit()
        report_form.addRow("Report header colour (hex):", self._report_header_colour)
        self._report_accent_colour = QLineEdit()
        report_form.addRow("Report accent colour (hex):", self._report_accent_colour)
        self._report_stripe_colour = QLineEdit()
        report_form.addRow("Report stripe colour (hex):", self._report_stripe_colour)
        self._report_footer = QLineEdit()
        report_form.addRow("Report footer:", self._report_footer)
        self._pdf_save_mode = QComboBox()
        self._pdf_save_mode.addItems(["Auto", "Prompt"])
        report_form.addRow("PDF save mode:", self._pdf_save_mode)
        report_group.setLayout(report_form)
        tabs.addTab(report_group, "Reports")

        # Backup tab
        backup_group = QGroupBox("Backup")
        backup_form = QFormLayout()
        self._backup_enabled = QCheckBox("Enable scheduled backups")
        backup_form.addRow(self._backup_enabled)
        self._backup_frequency = QSpinBox()
        self._backup_frequency.setRange(1, 168)
        backup_form.addRow("Frequency (hours):", self._backup_frequency)
        self._backup_keep = QSpinBox()
        self._backup_keep.setRange(1, 365)
        backup_form.addRow("Keep count:", self._backup_keep)
        self._backup_on_exit = QCheckBox("Backup on exit")
        backup_form.addRow(self._backup_on_exit)
        self._backup_folder = QLineEdit()
        backup_browse = QPushButton("Browse...")
        backup_browse.clicked.connect(self._browse_backup_folder)
        backup_row = QHBoxLayout()
        backup_row.addWidget(self._backup_folder)
        backup_row.addWidget(backup_browse)
        backup_form.addRow("Backup folder:", backup_row)
        backup_group.setLayout(backup_form)
        tabs.addTab(backup_group, "Backup")

        # Data / Setup tab
        data_group = QGroupBox("Data & Setup")
        data_form = QFormLayout()

        self._data_dir = QLineEdit()
        self._data_dir.setReadOnly(True)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_data_dir)
        onedrive_btn = QPushButton("Use OneDrive")
        onedrive_btn.clicked.connect(self._use_onedrive)
        data_row = QHBoxLayout()
        data_row.addWidget(self._data_dir)
        data_row.addWidget(browse_btn)
        data_row.addWidget(onedrive_btn)
        data_form.addRow("Data folder:", data_row)

        self._documents_dir = QLineEdit()
        self._documents_dir.setReadOnly(True)
        docs_browse_btn = QPushButton("Browse...")
        docs_browse_btn.clicked.connect(self._browse_documents_dir)
        docs_reset_btn = QPushButton("Use default")
        docs_reset_btn.clicked.connect(self._reset_documents_dir)
        documents_row = QHBoxLayout()
        documents_row.addWidget(self._documents_dir)
        documents_row.addWidget(docs_browse_btn)
        documents_row.addWidget(docs_reset_btn)
        data_form.addRow("Documents (PDF) folder:", documents_row)

        self._exports_dir = QLineEdit()
        self._exports_dir.setReadOnly(True)
        exports_browse_btn = QPushButton("Browse...")
        exports_browse_btn.clicked.connect(self._browse_exports_dir)
        exports_reset_btn = QPushButton("Use default")
        exports_reset_btn.clicked.connect(self._reset_exports_dir)
        exports_row = QHBoxLayout()
        exports_row.addWidget(self._exports_dir)
        exports_row.addWidget(exports_browse_btn)
        exports_row.addWidget(exports_reset_btn)
        data_form.addRow("Exports folder:", exports_row)

        self._logs_dir = QLineEdit()
        self._logs_dir.setReadOnly(True)
        logs_browse_btn = QPushButton("Browse...")
        logs_browse_btn.clicked.connect(self._browse_logs_dir)
        logs_reset_btn = QPushButton("Use default")
        logs_reset_btn.clicked.connect(self._reset_logs_dir)
        logs_row = QHBoxLayout()
        logs_row.addWidget(self._logs_dir)
        logs_row.addWidget(logs_browse_btn)
        logs_row.addWidget(logs_reset_btn)
        data_form.addRow("Logs folder:", logs_row)

        self._database_path = QLineEdit()
        self._database_path.setReadOnly(True)
        open_db_btn = QPushButton("Open database location")
        open_db_btn.clicked.connect(self._open_database_location)
        db_row = QHBoxLayout()
        db_row.addWidget(self._database_path)
        db_row.addWidget(open_db_btn)
        data_form.addRow("Database file:", db_row)

        self._database_mode = QComboBox()
        self._database_mode.addItem("Local SQLite", "sqlite")
        self._database_mode.currentIndexChanged.connect(self._update_database_fields)
        data_form.addRow("Database type:", self._database_mode)

        self._mysql_host = QLineEdit()
        self._mysql_port = QSpinBox()
        self._mysql_port.setRange(1, 65535)
        self._mysql_database = QLineEdit()
        self._mysql_user = QLineEdit()
        self._mysql_password_env = QLineEdit()
        self._mysql_password_env.setPlaceholderText("INVOICE_MANAGER_DB_PASSWORD")
        self._test_database_btn = QPushButton("Test database connection")
        self._test_database_btn.clicked.connect(self._test_database_connection)
        if self._context.config.REMOTE_DATABASE_ENABLED:
            self._database_mode.addItem("Remote MySQL / MariaDB", "mysql")
            data_form.addRow("MySQL host:", self._mysql_host)
            data_form.addRow("MySQL port:", self._mysql_port)
            data_form.addRow("MySQL database:", self._mysql_database)
            data_form.addRow("MySQL user:", self._mysql_user)
            data_form.addRow("Password environment variable:", self._mysql_password_env)
            data_form.addRow(self._test_database_btn)
        else:
            data_form.addRow(QLabel("Remote MySQL support is planned but not enabled in this release."))

        self._migration_source = QLineEdit()
        self._migration_source.setReadOnly(True)
        open_source_btn = QPushButton("Open source folder")
        open_source_btn.clicked.connect(self._open_migration_source)
        source_row = QHBoxLayout()
        source_row.addWidget(self._migration_source)
        source_row.addWidget(open_source_btn)
        data_form.addRow("Migration / CSV source:", source_row)

        data_form.addRow(QLabel("Changing the data folder or database requires a restart to take effect."))
        data_group.setLayout(data_form)
        tabs.addTab(data_group, "Data")

        # Invoice wording tab
        invoice_group = QGroupBox("Invoice PDF wording")
        invoice_form = QFormLayout()
        for key in self._INVOICE_WORDING:
            edit = QLineEdit()
            invoice_form.addRow(self._label(key), edit)
            self._fields[key] = edit
        invoice_group.setLayout(invoice_form)
        tabs.addTab(invoice_group, "Invoice")

        # Receipt wording tab
        receipt_group = QGroupBox("Receipt PDF wording")
        receipt_form = QFormLayout()
        for key in self._RECEIPT_WORDING:
            edit = QLineEdit()
            receipt_form.addRow(self._label(key), edit)
            self._fields[key] = edit
        receipt_group.setLayout(receipt_form)
        tabs.addTab(receipt_group, "Receipt")

        # Quote wording tab
        quote_group = QGroupBox("Quote PDF wording")
        quote_form = QFormLayout()
        for key in self._QUOTE_WORDING:
            edit = QLineEdit()
            quote_form.addRow(self._label(key), edit)
            self._fields[key] = edit
        quote_group.setLayout(quote_form)
        tabs.addTab(quote_group, "Quote")

        layout.addWidget(tabs)

        bbox = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        bbox.accepted.connect(self._save)
        bbox.rejected.connect(self.reject)
        layout.addWidget(bbox)

    def _label(self, key: str) -> str:
        return " ".join(part.capitalize() for part in key.replace("_", " ").split())

    def _default_for(self, key: str) -> Any:
        defaults: dict[str, Any] = {
            **self._DEFAULT_VALUES,
            **self._INVOICE_DEFAULTS,
            **self._RECEIPT_DEFAULTS,
            **self._QUOTE_DEFAULTS,
        }
        return defaults.get(key)

    def _load(self) -> None:
        settings = self._context.setting_repo
        for key, edit in self._fields.items():
            edit.setText(settings.get(key) or self._default_for(key) or "")
        self._gst_rate.setText(settings.get("gst_rate") or self._default_for("gst_rate"))
        self._payment_terms.setValue(
            settings.get_int("payment_terms_days", self._default_for("payment_terms_days"))
        )
        self._default_taxable.setChecked(settings.get("default_taxable") == "1")
        self._fy_start.setValue(
            settings.get_int("financial_year_start_month", self._default_for("financial_year_start_month"))
        )
        self._next_invoice.setValue(
            settings.get_int("next_invoice_number", self._default_for("next_invoice_number"))
        )
        self._next_quote.setValue(
            settings.get_int("next_quote_number", self._default_for("next_quote_number"))
        )
        self._next_receipt.setValue(
            settings.get_int("next_receipt_number", self._default_for("next_receipt_number"))
        )
        self._next_credit_note.setValue(
            settings.get_int("next_credit_note_number", self._default_for("next_credit_note_number"))
        )

        self._report_header_colour.setText(
            settings.get("report_header_colour") or self._default_for("report_header_colour")
        )
        self._report_accent_colour.setText(
            settings.get("report_accent_colour") or self._default_for("report_accent_colour")
        )
        self._report_stripe_colour.setText(
            settings.get("report_stripe_colour") or self._default_for("report_stripe_colour")
        )
        self._report_footer.setText(settings.get("report_footer") or self._default_for("report_footer"))
        pdf_mode = settings.get("pdf_save_mode") or self._default_for("pdf_save_mode")
        self._pdf_save_mode.setCurrentText(
            pdf_mode if pdf_mode in ("Auto", "Prompt") else "Auto"
        )

        self._backup_enabled.setChecked(
            (settings.get("backup_enabled") or str(int(self._default_for("backup_enabled")))) == "1"
        )
        self._backup_frequency.setValue(
            settings.get_int("backup_frequency_hours", self._default_for("backup_frequency"))
        )
        self._backup_keep.setValue(
            settings.get_int("backup_keep", self._default_for("backup_keep"))
        )
        self._backup_on_exit.setChecked(
            (settings.get("backup_on_exit") or str(int(self._default_for("backup_on_exit")))) == "1"
        )
        self._backup_folder.setText(settings.get("backup_folder") or self._default_for("backup_folder"))

        self._data_dir.setText(str(self._context.config.get_data_directory()))
        self._documents_dir.setText(str(self._context.config.get_documents_directory()))
        self._exports_dir.setText(str(self._context.config.get_exports_directory()))
        self._logs_dir.setText(str(self._context.config.get_logs_directory()))
        self._database_path.setText(str(self._context.config.db_path()))
        database_cfg = self._context.config.load()
        mode_index = self._database_mode.findData(self._context.config.database_mode())
        self._database_mode.setCurrentIndex(max(0, mode_index))
        self._mysql_host.setText(str(database_cfg.get("mysql_host", "localhost")))
        self._mysql_port.setValue(int(database_cfg.get("mysql_port", 3306)))
        self._mysql_database.setText(str(database_cfg.get("mysql_database", "invoice_manager")))
        self._mysql_user.setText(str(database_cfg.get("mysql_user", "")))
        self._mysql_password_env.setText(
            str(database_cfg.get("mysql_password_env", "INVOICE_MANAGER_DB_PASSWORD"))
        )
        self._update_database_fields()
        self._migration_source.setText(settings.get("migration_source_dir") or "")

    def _save(self) -> None:
        settings = self._context.setting_repo
        for key, edit in self._fields.items():
            settings.set(key, edit.text().strip())

        gst = self._gst_rate.text().strip() or "0.0"
        try:
            Decimal(gst)
        except Exception:
            QMessageBox.warning(self, "Invalid", "GST rate must be a valid decimal.")
            return
        settings.set("gst_rate", gst)
        settings.set("payment_terms_days", str(self._payment_terms.value()))
        settings.set("default_taxable", "1" if self._default_taxable.isChecked() else "0")
        settings.set("financial_year_start_month", str(self._fy_start.value()))

        self._context.invoice_service.set_next_invoice_number(self._next_invoice.value())
        self._context.invoice_service.set_next_quote_number(self._next_quote.value())
        self._context.payment_service.set_next_receipt_number(self._next_receipt.value())
        self._context.invoice_service.set_next_credit_note_number(self._next_credit_note.value())

        # Also store the number settings in case services have not flushed yet.
        settings.set("next_invoice_number", str(self._next_invoice.value()))
        settings.set("next_quote_number", str(self._next_quote.value()))
        settings.set("next_receipt_number", str(self._next_receipt.value()))
        settings.set("next_credit_note_number", str(self._next_credit_note.value()))

        settings.set("report_header_colour", self._report_header_colour.text().strip())
        settings.set("report_accent_colour", self._report_accent_colour.text().strip())
        settings.set("report_stripe_colour", self._report_stripe_colour.text().strip())
        settings.set("report_footer", self._report_footer.text().strip())
        settings.set("pdf_save_mode", self._pdf_save_mode.currentText())

        settings.set("backup_enabled", "1" if self._backup_enabled.isChecked() else "0")
        settings.set("backup_frequency_hours", str(self._backup_frequency.value()))
        settings.set("backup_keep", str(self._backup_keep.value()))
        settings.set("backup_on_exit", "1" if self._backup_on_exit.isChecked() else "0")
        settings.set("backup_folder", self._backup_folder.text().strip())

        new_data_dir = Path(self._data_dir.text())
        if new_data_dir != self._context.config.get_data_directory():
            self._context.config.set_data_directory(new_data_dir)

        new_documents_dir = Path(self._documents_dir.text())
        if new_documents_dir != self._context.config.get_documents_directory():
            self._context.config.set_documents_directory(new_documents_dir)

        new_exports_dir = Path(self._exports_dir.text())
        if new_exports_dir != self._context.config.get_exports_directory():
            self._context.config.set_exports_directory(new_exports_dir)

        new_logs_dir = Path(self._logs_dir.text())
        if new_logs_dir != self._context.config.get_logs_directory():
            self._context.config.set_logs_directory(new_logs_dir)

        self._context.config.configure_database(
            {
                "database_mode": self._database_mode.currentData(),
                "mysql_host": self._mysql_host.text().strip(),
                "mysql_port": self._mysql_port.value(),
                "mysql_database": self._mysql_database.text().strip(),
                "mysql_user": self._mysql_user.text().strip(),
                "mysql_password_env": self._mysql_password_env.text().strip(),
            }
        )

        self._context.session.commit()
        QMessageBox.information(self, "Saved", "Settings saved.")
        self.accept()

    def _update_database_fields(self) -> None:
        enabled = self._database_mode.currentData() == "mysql"
        for widget in (
            self._mysql_host,
            self._mysql_port,
            self._mysql_database,
            self._mysql_user,
            self._mysql_password_env,
        ):
            widget.setEnabled(enabled)
        self._test_database_btn.setEnabled(enabled)

    def _test_database_connection(self) -> None:
        password_env = self._mysql_password_env.text().strip()
        password = os.environ.get(password_env)
        if not password:
            QMessageBox.warning(
                self,
                "Password unavailable",
                f"Set the {password_env} environment variable before testing.",
            )
            return
        url = URL.create(
            "mysql+pymysql",
            username=self._mysql_user.text().strip(),
            password=password,
            host=self._mysql_host.text().strip(),
            port=self._mysql_port.value(),
            database=self._mysql_database.text().strip(),
            query={"charset": "utf8mb4"},
        )
        database = Database(url)
        try:
            database.test_connection()
            QMessageBox.information(self, "Connection successful", "The MySQL connection succeeded.")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Connection failed", str(exc))
        finally:
            database.engine.dispose()

    def _browse_data_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select data directory", self._data_dir.text()
        )
        if path:
            self._data_dir.setText(path)

    def _browse_documents_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select documents output directory", self._documents_dir.text()
        )
        if path:
            self._documents_dir.setText(path)

    def _reset_documents_dir(self) -> None:
        self._documents_dir.setText(str(self._context.config.base_dir / "documents"))

    def _browse_exports_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select exports directory", self._exports_dir.text()
        )
        if path:
            self._exports_dir.setText(path)

    def _reset_exports_dir(self) -> None:
        self._exports_dir.setText(str(self._context.config.base_dir / "exports"))

    def _browse_logs_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select logs directory", self._logs_dir.text()
        )
        if path:
            self._logs_dir.setText(path)

    def _reset_logs_dir(self) -> None:
        self._logs_dir.setText(str(self._context.config.base_dir / "logs"))

    def _use_onedrive(self) -> None:
        onedrive = os.environ.get("ONEDRIVE") or str(Path.home() / "OneDrive")
        target = Path(onedrive) / "InvoiceReceiptManager"
        self._data_dir.setText(str(target))

    def _browse_backup_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select backup folder", self._backup_folder.text() or self._data_dir.text()
        )
        if path:
            self._backup_folder.setText(path)

    def _open_database_location(self) -> None:
        path = Path(self._database_path.text())
        if not path.exists():
            QMessageBox.warning(self, "Not found", f"Database file not found: {path}")
            return
        os.startfile(str(path.parent))

    def _open_migration_source(self) -> None:
        source = self._migration_source.text().strip()
        if not source:
            QMessageBox.information(self, "No source", "No migration source is recorded.")
            return
        path = Path(source)
        if not path.exists():
            QMessageBox.warning(self, "Not found", f"Source folder not found: {path}")
            return
        os.startfile(str(path))
