"""Full data export service.

Creates a portable ZIP archive containing the application configuration,
SQLite database, documents, exports, and logs.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import datetime
from pathlib import Path

from sqlalchemy import MetaData, select
from sqlalchemy.orm import Session

from invoice_manager.infrastructure.config import AppConfig


class DataExportServiceError(Exception):
    pass


class DataExportService:
    """Export all application data into a single ZIP file."""

    MANIFEST_NAME = "export_manifest.json"

    def __init__(self, config: AppConfig, session: Session | None = None) -> None:
        self._config = config
        self._session = session

    def export_all(self, target: Path | None = None) -> Path:
        """Zip the base application directory and return the archive path.

        Backups and the output archive itself are excluded from the export.
        """
        base = self._config.base_dir
        if not base.exists():
            raise DataExportServiceError(f"Base directory not found: {base}")

        if target is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            target = self._config.get_exports_directory() / f"invoice_manager_export_{timestamp}.zip"
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)

        target_resolved = target.resolve()

        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            manifest = {
                "created_at": datetime.now().isoformat(),
                "version": "2.0",
                "base_dir": str(base),
            }
            zf.writestr(self.MANIFEST_NAME, json.dumps(manifest, indent=2))

            if self._session is not None:
                metadata = MetaData()
                metadata.reflect(bind=self._session.get_bind())
                for table in sorted(metadata.tables.values(), key=lambda value: value.name):
                    rows = self._session.execute(select(table)).mappings().all()
                    output = io.StringIO(newline="")
                    writer = csv.DictWriter(output, fieldnames=[column.name for column in table.columns])
                    writer.writeheader()
                    for row in rows:
                        writer.writerow({key: str(value) if value is not None else "" for key, value in row.items()})
                    zf.writestr(f"database_csv/{table.name}.csv", output.getvalue())

            if self._config.config_path.exists():
                zf.write(self._config.config_path, self._config.config_path.name)

            for folder in ("data", "documents", "exports", "logs"):
                src = base / folder
                if not src.exists():
                    continue
                for file in src.rglob("*"):
                    if not file.is_file():
                        continue
                    if file.resolve() == target_resolved:
                        continue
                    arcname = f"{folder}/{file.relative_to(src)}"
                    zf.write(file, arcname)

        return target
