import pytest

from invoice_manager.application.client_service import ClientService
from invoice_manager.application.invoice_service import InvoiceItemData, InvoiceService
from invoice_manager.config import AppPaths
from invoice_manager.ui.clients import ClientsView
from invoice_manager.ui.main_window import DESTINATIONS, MainWindow


@pytest.mark.gui
def test_shell_opens_with_all_eight_destinations(qtbot) -> None:
    window = MainWindow("Alexander Gillam")
    qtbot.addWidget(window)
    window.show()
    assert window.nav.count() == 8
    assert [window.nav.item(i).text() for i in range(8)] == list(DESTINATIONS)
    actions = {action.text(): action for action in window.menuBar().actions()[0].menu().actions()}
    assert window.application_menu.toolTipsVisible()
    assert actions["About"].isEnabled()
    assert actions["App Log"].isEnabled()
    assert not actions["Settings"].isEnabled()


@pytest.mark.gui
def test_clients_rollup_columns_and_refresh(qtbot, session, tmp_path) -> None:
    client = ClientService().create(session, display_name="Rollup GUI")
    invoice = InvoiceService().create_draft(
        session,
        client,
        [InvoiceItemData("Work", 1, 1000)],
    )
    paths = AppPaths.resolve(tmp_path)
    view = ClientsView(session, paths=paths)
    qtbot.addWidget(view)
    assert view.table.columnCount() == 10
    assert [view.table.horizontalHeaderItem(i).text() for i in range(10)][-6:] == [
        "Invoices",
        "Billed",
        "Paid",
        "Balance",
        "Overdue",
        "Last invoice date",
    ]
    assert view.table.item(0, 5).text() == "$0.00"
    InvoiceService(paths=paths).issue(session, invoice)
    view.show()
    qtbot.wait(10)
    assert view.table.item(0, 4).text() == "1"
    assert view.table.item(0, 5).text() == "$10.00"
    assert view.table.item(0, 7).text() == "$10.00"
    assert view.table.item(0, 9).text()
