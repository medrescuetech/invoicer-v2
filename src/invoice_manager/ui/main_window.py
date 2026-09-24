from __future__ import annotations

import sys
from pathlib import Path

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import qVersion
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from invoice_manager import __version__
from invoice_manager.config import AppPaths
from invoice_manager.ui.app_log import AppLogDialog
from invoice_manager.ui.clients import ClientsView
from invoice_manager.ui.invoice_editor import InvoiceEditorView
from invoice_manager.ui.invoice_list import InvoiceListView
from invoice_manager.ui.services import ServicesView

DESTINATIONS = (
    "Dashboard",
    "New Invoice",
    "Invoices",
    "Payments & Receipts",
    "Clients",
    "Products & Services",
    "Income & Expenses",
    "Reports",
)


class MainWindow(QMainWindow):
    def __init__(
        self,
        user_display_name: str = "",
        data_location: Path | None = None,
        log_path: Path | None = None,
        session: Session | None = None,
        paths: AppPaths | None = None,
        user_id: int | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Invoicer V2")
        self.resize(1100, 720)
        self.nav = QListWidget()
        self.nav.setObjectName("navigationRail")
        self.nav.setFixedWidth(210)
        for destination in DESTINATIONS:
            QListWidgetItem(destination, self.nav)
        self.pages = QStackedWidget()
        resolved_paths = paths or AppPaths.resolve()
        editor_view = InvoiceEditorView(session, paths=resolved_paths, user_id=user_id)
        invoice_list_view = InvoiceListView(session, paths=resolved_paths, user_id=user_id)
        invoice_list_view.invoice_selected.connect(editor_view.load_invoice)
        for destination in DESTINATIONS:
            page: QWidget
            if destination == "New Invoice":
                page = editor_view
            elif destination == "Invoices":
                page = invoice_list_view
            elif destination == "Clients":
                page = ClientsView(session, paths=resolved_paths, user_id=user_id)
            elif destination == "Products & Services":
                page = ServicesView(session, user_id=user_id)
            else:
                page = QWidget()
            if destination not in {
                "Clients",
                "Products & Services",
                "New Invoice",
                "Invoices",
            }:
                page_layout = QVBoxLayout(page)
                title = QLabel(destination)
                title.setStyleSheet("font-size: 24px; font-weight: 600;")
                page_layout.addWidget(title)
                if destination == "Dashboard":
                    text = "Your financial dashboard will arrive in a later phase."
                else:
                    text = f"{destination} will arrive in a later phase."
                empty = QLabel(text)
                empty.setWordWrap(True)
                page_layout.addWidget(empty)
                page_layout.addStretch()
            self.pages.addWidget(page)
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)
        central = QWidget()
        central_layout = QHBoxLayout(central)
        central_layout.addWidget(self.nav)
        central_layout.addWidget(self.pages, 1)
        self.setCentralWidget(central)
        self._data_location = data_location
        self._log_path = log_path or Path.cwd() / "app.log"
        self._build_menu()
        self.statusBar().showMessage(f"Signed in: {user_display_name}" if user_display_name else "")

    def _build_menu(self) -> None:
        menu = QMenu("&Application", self.menuBar())
        menu.setToolTipsVisible(True)
        self.menuBar().addMenu(menu)
        self.application_menu = menu
        for label in (
            "Settings",
            "Import/Migrate",
            "Export",
            "Backup Now",
            "Restore",
            "Users",
            "Audit Log",
            "App Log",
            "Help",
            "About",
        ):
            action = menu.addAction(label)
            if label == "App Log":
                action.triggered.connect(self._show_app_log)
            elif label == "About":
                action.triggered.connect(self._show_about)
            else:
                action.setEnabled(False)
                action.setToolTip("Available in a later phase")

    def _show_about(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        location = str(self._data_location) if self._data_location else "Not configured"
        QMessageBox.about(
            self,
            "About Invoicer V2",
            (
                f"Invoicer V2 {__version__}\n\n"
                f"Data location: {location}\n"
                f"Python: {sys.version.split()[0]}\n"
                f"Qt: {qVersion()}\n"
                f"PySide6: {pyside_version}"
            ),
        )

    def _show_app_log(self) -> None:
        if self._log_path is not None:
            dialog = AppLogDialog(self._log_path)
            dialog.exec()
