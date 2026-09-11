"""Dashboard summary page."""

from __future__ import annotations

from datetime import date
from typing import cast

from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from invoice_manager.domain.statuses import invoice_balance_cents
from invoice_manager.ui.app_context import AppContext


class DashboardPage(QWidget):
    """High-level summary of invoices, payments, and ledger."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h1>Dashboard</h1>"))

        self._grid = QGridLayout()
        self._grid.setSpacing(16)
        layout.addLayout(self._grid)

        self._widgets: list[tuple[str, QLabel]] = []

        self._unpaid_total = QLabel("$0.00")
        self._overdue_count = QLabel("0")
        self._overdue_total = QLabel("$0.00")
        self._month_income = QLabel("$0.00")
        self._month_expense = QLabel("$0.00")

        self._grid.addWidget(QLabel("Unpaid invoices total:"), 0, 0)
        self._grid.addWidget(self._unpaid_total, 0, 1)
        self._grid.addWidget(QLabel("Overdue invoices:"), 1, 0)
        self._grid.addWidget(self._overdue_count, 1, 1)
        self._grid.addWidget(QLabel("Overdue total:"), 2, 0)
        self._grid.addWidget(self._overdue_total, 2, 1)
        self._grid.addWidget(QLabel("This month income:"), 3, 0)
        self._grid.addWidget(self._month_income, 3, 1)
        self._grid.addWidget(QLabel("This month expenses:"), 4, 0)
        self._grid.addWidget(self._month_expense, 4, 1)

        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        layout.addWidget(refresh)
        layout.addStretch()

    def refresh(self) -> None:
        from invoice_manager.persistence.models import Invoice, LedgerEntry

        session = self._context.session
        invoices = session.query(Invoice).all()
        today = date.today()

        unpaid_total = 0
        overdue_count = 0
        overdue_total = 0
        for inv in invoices:
            if inv.is_void or inv.is_cancelled or inv.is_draft:
                continue
            balance = invoice_balance_cents(inv)
            if balance > 0:
                unpaid_total += balance
                due = inv.due_date
                if due is not None and cast(date, due) < today:
                    overdue_count += 1
                    overdue_total += balance

        entries = (
            session.query(LedgerEntry)
            .filter(
                LedgerEntry.is_deleted.is_(False),
            )
            .all()
        )
        month_income = 0
        month_expense = 0
        for entry in entries:
            entry_date = cast(date, entry.date)
            if entry_date.month != today.month or entry_date.year != today.year:
                continue
            if entry.entry_type == "in":
                month_income += entry.amount_cents
            else:
                month_expense += entry.amount_cents

        self._unpaid_total.setText(f"${unpaid_total / 100:.2f}")
        self._overdue_count.setText(str(overdue_count))
        self._overdue_total.setText(f"${overdue_total / 100:.2f}")
        self._month_income.setText(f"${month_income / 100:.2f}")
        self._month_expense.setText(f"${month_expense / 100:.2f}")
