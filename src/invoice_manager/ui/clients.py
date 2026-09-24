from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
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
from sqlalchemy.orm import Session

from invoice_manager.application.client_service import ClientService
from invoice_manager.config import AppPaths
from invoice_manager.domain.money import format_aud
from invoice_manager.persistence.models import Client


class ClientsView(QWidget):
    def __init__(
        self,
        session: Session | None = None,
        service: ClientService | None = None,
        *,
        paths: AppPaths | None = None,
        user_id: int | None = None,
    ) -> None:
        super().__init__()
        self.session = session
        self.service = service or ClientService()
        self.paths = paths or AppPaths.resolve()
        self.user_id = user_id
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search clients")
        self.search.textChanged.connect(self.refresh)
        self.name = QLineEdit()
        self.email = QLineEdit()
        self.phone = QLineEdit()
        form = QFormLayout()
        form.addRow("Name", self.name)
        form.addRow("Email", self.email)
        form.addRow("Phone", self.phone)
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(
            [
                "Client",
                "Contact",
                "Phone",
                "Email",
                "Invoices",
                "Billed",
                "Paid",
                "Balance",
                "Overdue",
                "Last invoice date",
            ]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.cellClicked.connect(self._load_selected)
        add = QPushButton("Add client")
        add.clicked.connect(self._create)
        edit = QPushButton("Save changes")
        edit.clicked.connect(self._update)
        deactivate = QPushButton("Deactivate")
        deactivate.clicked.connect(self._deactivate)
        delete = QPushButton("Delete client")
        delete.clicked.connect(self._delete)
        export = QPushButton("Export / copy CSV")
        export.clicked.connect(self._export)
        actions = QHBoxLayout()
        for button in (add, edit, deactivate, delete, export):
            actions.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Clients"))
        layout.addWidget(self.search)
        layout.addLayout(form)
        layout.addLayout(actions)
        layout.addWidget(self.table)
        self._selected: Client | None = None
        self.refresh()

    def showEvent(self, event: QShowEvent) -> None:
        self.refresh()
        super().showEvent(event)

    def refresh(self) -> None:
        self.table.setRowCount(0)
        if self.session is None:
            return
        for client in self.service.list(self.session, self.search.text()):
            row = self.table.rowCount()
            self.table.insertRow(row)
            rollup = self.service.rollup(self.session, client)
            values = [
                client.display_name,
                client.contact_name,
                client.phone,
                client.email,
                str(rollup.invoice_count),
                format_aud(rollup.billed_cents),
                format_aud(rollup.paid_cents),
                format_aud(rollup.balance_cents),
                format_aud(rollup.overdue_cents),
                (
                    rollup.last_invoice_date.strftime("%d/%m/%Y")
                    if rollup.last_invoice_date is not None
                    else ""
                ),
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))

    def _load_selected(self, row: int, _column: int) -> None:
        if self.session is None:
            return
        clients = self.service.list(self.session, self.search.text())
        if row >= len(clients):
            return
        self._selected = clients[row]
        self.name.setText(self._selected.display_name)
        self.email.setText(self._selected.email)
        self.phone.setText(self._selected.phone)

    def _create(self) -> None:
        if self.session is None:
            return
        try:
            self.service.create(
                self.session,
                display_name=self.name.text(),
                email=self.email.text(),
                phone=self.phone.text(),
                user_id=self.user_id,
            )
            self.session.commit()
            self._clear_form()
            self.refresh()
        except ValueError as exc:
            QMessageBox.warning(self, "Client", str(exc))

    def _update(self) -> None:
        if self.session is None or self._selected is None:
            return
        try:
            self.service.update(
                self.session,
                self._selected,
                display_name=self.name.text(),
                email=self.email.text(),
                phone=self.phone.text(),
                user_id=self.user_id,
            )
            self.session.commit()
            self.refresh()
        except ValueError as exc:
            QMessageBox.warning(self, "Client", str(exc))

    def _deactivate(self) -> None:
        if self.session is None or self._selected is None:
            return
        self.service.deactivate(self.session, self._selected, user_id=self.user_id)
        self.session.commit()
        self.refresh()

    def _delete(self) -> None:
        if self.session is None or self._selected is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete client",
            f"Delete {self._selected.display_name}?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.service.delete(self.session, self._selected, user_id=self.user_id)
            self.session.commit()
            self._clear_form()
            self.refresh()
        except ValueError as exc:
            QMessageBox.warning(self, "Client", str(exc))

    def _export(self) -> None:
        if self.session is not None:
            content = self.service.export_csv(self.session)
            QApplication.clipboard().setText(content)
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Export clients",
                str(self.paths.exports / "clients.csv"),
                "CSV files (*.csv)",
            )
            if path:
                Path(path).write_text(content, encoding="utf-8", newline="")

    def _clear_form(self) -> None:
        self.name.clear()
        self.email.clear()
        self.phone.clear()
        self._selected = None
