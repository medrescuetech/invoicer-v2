"""Tests for migration pack export and import."""

from __future__ import annotations

import zipfile
from pathlib import Path

from invoice_manager.application.migration_pack_service import (
    MigrationPackError,
    MigrationPackService,
)
from invoice_manager.infrastructure.config import AppConfig


def test_export_pack_creates_zip_with_manifest_and_files(tmp_path: Path) -> None:
    source_base = tmp_path / "source"
    source_base.mkdir()
    config = AppConfig(source_base)

    (config.get_data_directory() / "business.sqlite3").write_text("db", encoding="utf-8")
    doc_file = config.get_documents_directory() / "invoices" / "INV-0001.pdf"
    doc_file.parent.mkdir(parents=True)
    doc_file.write_text("pdf", encoding="utf-8")

    archive = MigrationPackService(config).export_pack()

    assert archive.exists()
    with zipfile.ZipFile(archive, "r") as zf:
        names = zf.namelist()
        assert "migration_pack_manifest.json" in names
        assert "config.json" in names
        assert any(n.startswith("data/") for n in names)
        assert any(n.startswith("documents/") for n in names)


def test_import_pack_restores_data_and_documents(tmp_path: Path) -> None:
    source_base = tmp_path / "source"
    source_base.mkdir()
    source_config = AppConfig(source_base)
    (source_config.get_data_directory() / "business.sqlite3").write_text("db", encoding="utf-8")
    doc_file = source_config.get_documents_directory() / "invoices" / "INV-0001.pdf"
    doc_file.parent.mkdir(parents=True)
    doc_file.write_text("pdf", encoding="utf-8")

    # Store a non-path setting in config.json to verify it is merged.
    source_config.save({**source_config.load(), "custom_setting": "preserved"})

    archive = MigrationPackService(source_config).export_pack()

    dest_base = tmp_path / "dest"
    dest_base.mkdir()
    dest_config = AppConfig(dest_base)
    safety = MigrationPackService(dest_config).import_pack(archive)

    assert safety.exists()
    assert (dest_config.get_data_directory() / "business.sqlite3").read_text(encoding="utf-8") == "db"
    restored_doc = dest_config.get_documents_directory() / "invoices" / "INV-0001.pdf"
    assert restored_doc.read_text(encoding="utf-8") == "pdf"
    assert dest_config.load().get("custom_setting") == "preserved"

    # Directory paths from the source machine should not be imported.
    for key in MigrationPackService._PATH_KEYS:
        assert not dest_config.load().get(key)


def test_import_pack_rejects_missing_manifest(tmp_path: Path) -> None:
    bad_archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad_archive, "w") as zf:
        zf.writestr("data.txt", "x")

    config = AppConfig(tmp_path / "app")
    with zipfile.ZipFile(bad_archive, "a") as zf:
        pass

    try:
        MigrationPackService(config).validate_pack(bad_archive)
    except MigrationPackError as exc:
        assert "manifest missing" in str(exc).lower()
    else:
        raise AssertionError("Expected MigrationPackError")
