from datetime import date
from pathlib import Path

import pytest

from invoice_manager.application.client_service import ClientService
from invoice_manager.application.invoice_service import InvoiceItemData, InvoiceService
from invoice_manager.config import AppPaths
from invoice_manager.persistence.models import Invoice
from invoice_manager.ui.invoice_editor import InvoiceEditorView
from invoice_manager.ui.invoice_list import InvoiceListView


@pytest.mark.gui
def test_editor_line_totals_and_save_reload(qtbot, session) -> None:
    client = ClientService().create(session, display_name="GUI Client")
    editor = InvoiceEditorView(session)
    qtbot.addWidget(editor)
    editor.client_combo.setCurrentIndex(editor.client_combo.findData(client.id))
    editor.description_input.setText("Design")
    editor.quantity_input.setText("2")
    editor.price_input.setText("1250")
    editor.add_line_button.click()
    assert editor.subtotal_label.text() == "$25.00"
    assert editor.total_label.text() == "$25.00"
    editor._save()
    assert editor.invoice is not None
    invoice_id = editor.invoice.id
    reloaded = InvoiceEditorView(session, session.get(type(editor.invoice), invoice_id))
    qtbot.addWidget(reloaded)
    assert reloaded.lines_table.rowCount() == 1
    assert reloaded.total_label.text() == "$25.00"


@pytest.mark.gui
def test_editor_issue_assigns_one_number(qtbot, session, monkeypatch, tmp_path) -> None:
    client = ClientService().create(session, display_name="Issue GUI")
    paths = AppPaths.resolve(tmp_path)
    editor = InvoiceEditorView(session, paths=paths)
    qtbot.addWidget(editor)
    editor.client_combo.setCurrentIndex(editor.client_combo.findData(client.id))
    editor.description_input.setText("Work")
    editor.price_input.setText("100")
    editor.add_line_button.click()
    editor._save()
    monkeypatch.setattr(
        "invoice_manager.ui.invoice_editor.QMessageBox.question",
        lambda *args: 16384,
    )
    editor._issue()
    assert editor.invoice is None
    issued = session.query(Invoice).one()
    assert issued.canonical_number == "INV-0001"


@pytest.mark.gui
def test_editor_can_issue_second_invoice_without_restart(
    qtbot, session, monkeypatch, tmp_path
) -> None:
    client = ClientService().create(session, display_name="Two invoices")
    paths = AppPaths.resolve(tmp_path)
    editor = InvoiceEditorView(session, paths=paths)
    qtbot.addWidget(editor)
    editor.client_combo.setCurrentIndex(editor.client_combo.findData(client.id))
    editor.description_input.setText("First")
    editor.price_input.setText("100")
    editor.add_line_button.click()
    editor._save()
    monkeypatch.setattr(
        "invoice_manager.ui.invoice_editor.QMessageBox.question",
        lambda *args: 16384,
    )
    editor._issue()
    assert editor.invoice is None

    editor.description_input.setText("Second")
    editor.price_input.setText("200")
    editor.add_line_button.click()
    editor._issue()
    numbers = [invoice.canonical_number for invoice in session.query(Invoice).all()]
    assert numbers == ["INV-0001", "INV-0002"]


@pytest.mark.gui
def test_editor_bad_date_is_visible_error(qtbot, session, monkeypatch) -> None:
    client = ClientService().create(session, display_name="Bad date")
    editor = InvoiceEditorView(session)
    qtbot.addWidget(editor)
    editor.client_combo.setCurrentIndex(editor.client_combo.findData(client.id))
    editor.description_input.setText("Work")
    editor.price_input.setText("100")
    editor.add_line_button.click()
    editor.invoice_date_input.setText("not a date")
    monkeypatch.setattr(
        "invoice_manager.ui.invoice_editor.QDesktopServices.openUrl",
        lambda *_args: True,
    )
    editor._preview()
    assert "DD/MM/YYYY" in editor.error_label.text()


@pytest.mark.gui
def test_editor_preview_uses_data_root_not_working_directory(
    qtbot, session, monkeypatch, tmp_path
) -> None:
    client = ClientService().create(session, display_name="Preview GUI")
    paths = AppPaths.resolve(tmp_path)
    editor = InvoiceEditorView(session, paths=paths)
    qtbot.addWidget(editor)
    editor.client_combo.setCurrentIndex(editor.client_combo.findData(client.id))
    editor.description_input.setText("Work")
    editor.price_input.setText("100")
    editor.add_line_button.click()
    monkeypatch.setattr(
        "invoice_manager.ui.invoice_editor.QDesktopServices.openUrl",
        lambda *_args: True,
    )
    working_directory = Path.cwd()

    editor._preview()

    assert Path.cwd() == working_directory
    assert not (working_directory / "invoice-draft-preview.pdf").exists()
    assert (paths.exports / "invoice-previews" / "draft-preview.pdf").is_file()


@pytest.mark.gui
def test_invoice_list_search_and_export(qtbot, session) -> None:
    client = ClientService().create(session, display_name="Searchable")
    InvoiceService().create_draft(
        session,
        client,
        [InvoiceItemData("Listed", 1, 100)],
        invoice_date=date(2026, 1, 1),
    )
    view = InvoiceListView(session)
    qtbot.addWidget(view)
    assert view.table.rowCount() == 1
    view.search.setText("Searchable")
    assert view.table.rowCount() == 1
    view.search.setText("missing")
    assert view.table.rowCount() == 0
    assert "canonical_number" in view.service.export_csv(session)


@pytest.mark.gui
def test_invoice_list_resolves_managed_pdf(qtbot, session, monkeypatch, tmp_path) -> None:
    client = ClientService().create(session, display_name="Managed PDF")
    paths = AppPaths.resolve(tmp_path)
    service = InvoiceService(paths=paths)
    invoice = service.create_draft(session, client, [InvoiceItemData("Work", 1, 100)])
    service.issue(session, invoice)
    view = InvoiceListView(session, invoice_service=service, paths=paths)
    qtbot.addWidget(view)
    view._select(0, 0)
    opened: list[str] = []
    monkeypatch.setattr(
        "invoice_manager.ui.invoice_list.QDesktopServices.openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )

    view._open_pdf()

    assert [Path(value).resolve() for value in opened] == [
        (paths.documents / "invoices" / "INV-0001.pdf").resolve()
    ]
