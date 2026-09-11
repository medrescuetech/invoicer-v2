"""Tests for the dashboard page."""

from __future__ import annotations

from datetime import date

from invoice_manager.domain.statuses import InvoiceStatus
from invoice_manager.infrastructure.config import AppConfig
from invoice_manager.persistence.models import Invoice
from invoice_manager.ui.app_context import AppContext
from invoice_manager.ui.dashboard_page import DashboardPage


def test_dashboard_refresh_with_none_due_date(qtbot, tmp_path):
    config = AppConfig(tmp_path / "app")
    context = AppContext(config, "admin")

    invoice = Invoice(
        number="QTE-0001",
        sequence_number=1,
        issue_date=date.today(),
        client_name="Acme",
        status=InvoiceStatus.ISSUED.value,
        is_draft=False,
        due_date=None,
    )
    context.session.add(invoice)
    context.session.commit()

    page = DashboardPage(context)
    qtbot.addWidget(page)
    page.refresh()

    assert page._unpaid_total.text() == "$0.00"
    assert page._overdue_count.text() == "0"

    context.session.close()
    context.database.engine.dispose()
