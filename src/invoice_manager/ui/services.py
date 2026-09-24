from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
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

from invoice_manager.application.service_item_service import ServiceItemService
from invoice_manager.domain.money import format_aud
from invoice_manager.persistence.models import ServiceItem


class ServicesView(QWidget):
    def __init__(
        self,
        session: Session | None = None,
        service: ServiceItemService | None = None,
        *,
        user_id: int | None = None,
    ) -> None:
        super().__init__()
        self.session = session
        self.service = service or ServiceItemService()
        self.user_id = user_id
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search services")
        self.search.textChanged.connect(self.refresh)
        self.code = QLineEdit()
        self.name = QLineEdit()
        self.description = QLineEdit()
        self.unit = QLineEdit("each")
        self.unit_price = QLineEdit()
        self.taxable = QCheckBox("Taxable")
        self.category_id = QLineEdit()
        form = QFormLayout()
        form.addRow("Code", self.code)
        form.addRow("Name", self.name)
        form.addRow("Description", self.description)
        form.addRow("Unit", self.unit)
        form.addRow("Unit price (cents)", self.unit_price)
        form.addRow("Tax", self.taxable)
        form.addRow("Category ID", self.category_id)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Code", "Name", "Description", "Unit", "Price", "Taxable", "Category"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.cellClicked.connect(self._load_selected)
        add = QPushButton("Add service")
        add.clicked.connect(self._create)
        edit = QPushButton("Save changes")
        edit.clicked.connect(self._update)
        toggle = QPushButton("Activate / deactivate")
        toggle.clicked.connect(self._toggle)
        actions = QHBoxLayout()
        for button in (add, edit, toggle):
            actions.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Products & Services"))
        layout.addWidget(self.search)
        layout.addLayout(form)
        layout.addLayout(actions)
        layout.addWidget(self.table)
        self._selected: ServiceItem | None = None
        self.refresh()

    def refresh(self) -> None:
        self.table.setRowCount(0)
        if self.session is None:
            return
        for item in self.service.list(self.session, self.search.text()):
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                item.code,
                item.name,
                item.description,
                item.unit,
                format_aud(item.unit_price_cents),
                "Yes" if item.taxable else "No",
                str(item.category_id or ""),
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))

    def _load_selected(self, row: int, _column: int) -> None:
        if self.session is None:
            return
        items = self.service.list(self.session, self.search.text())
        if row >= len(items):
            return
        self._selected = items[row]
        self.code.setText(self._selected.code)
        self.name.setText(self._selected.name)
        self.description.setText(self._selected.description)
        self.unit.setText(self._selected.unit)
        self.unit_price.setText(str(self._selected.unit_price_cents))
        self.taxable.setChecked(self._selected.taxable)
        self.category_id.setText(str(self._selected.category_id or ""))

    def _create(self) -> None:
        if self.session is None:
            return
        try:
            self.service.create(
                self.session,
                code=self.code.text(),
                name=self.name.text(),
                description=self.description.text(),
                unit=self.unit.text(),
                unit_price_cents=int(self.unit_price.text()),
                taxable=self.taxable.isChecked(),
                category_id=int(self.category_id.text()) if self.category_id.text() else None,
                user_id=self.user_id,
            )
            self.session.commit()
            self.refresh()
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Service", str(exc))

    def _update(self) -> None:
        if self.session is None or self._selected is None:
            return
        try:
            self.service.update(
                self.session,
                self._selected,
                code=self.code.text(),
                name=self.name.text(),
                description=self.description.text(),
                unit=self.unit.text(),
                unit_price_cents=int(self.unit_price.text()),
                taxable=self.taxable.isChecked(),
                category_id=int(self.category_id.text()) if self.category_id.text() else None,
                user_id=self.user_id,
            )
            self.session.commit()
            self.refresh()
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Service", str(exc))

    def _toggle(self) -> None:
        if self.session is None or self._selected is None:
            return
        self.service.set_active(
            self.session,
            self._selected,
            not self._selected.active,
            user_id=self.user_id,
        )
        self.session.commit()
        self.refresh()
