"""Full application migration pack export/import.

A migration pack is a single ZIP file containing config.json, the data
directory, documents, exports and logs so the application can be moved
between machines or version installations.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from invoice_manager.infrastructure.config import AppConfig


class MigrationPackError(Exception):
    pass


class MigrationPackService:
    """Create and restore migration packs for the application."""

    MANIFEST_NAME = "migration_pack_manifest.json"
    PACK_VERSION = "1.0"
    APP_VERSION = "2.0.11"

    _PATH_KEYS = {
        "data_dir",
        "documents_dir",
        "exports_dir",
        "backups_dir",
        "logs_dir",
    }

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def export_pack(self, target: Path | None = None) -> Path:
        """Zip config, data, documents, exports and logs into a single archive."""
        base = self._config.base_dir

        if target is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            target = self._config.get_exports_directory() / f"invoice_manager_pack_{timestamp}.zip"
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target_resolved = target.resolve()

        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            manifest = {
                "pack_version": self.PACK_VERSION,
                "app_version": self.APP_VERSION,
                "created_at": datetime.now().isoformat(),
                "source_base_dir": str(base),
            }
            zf.writestr(self.MANIFEST_NAME, json.dumps(manifest, indent=2))

            if self._config.config_path.exists():
                zf.write(self._config.config_path, "config.json")

            self._add_dir(zf, self._config.get_data_directory(), "data", target_resolved)
            self._add_dir(zf, self._config.get_documents_directory(), "documents", target_resolved)
            self._add_dir(zf, self._config.get_exports_directory(), "exports", target_resolved)
            self._add_dir(zf, self._config.get_logs_directory(), "logs", target_resolved)
            self._add_dir(zf, self._config.get_backups_directory(), "backups", target_resolved)

        return target

    def validate_pack(self, archive: Path) -> None:
        """Validate that *archive* looks like a supported migration pack."""
        archive = Path(archive)
        if not archive.exists():
            raise MigrationPackError(f"Archive not found: {archive}")

        try:
            with zipfile.ZipFile(archive, "r") as zf:
                if self.MANIFEST_NAME not in zf.namelist():
                    raise MigrationPackError("Migration pack manifest missing.")
                raw = zf.read(self.MANIFEST_NAME)
                manifest = json.loads(raw.decode("utf-8"))
        except zipfile.BadZipFile as exc:
            raise MigrationPackError("Archive is not a valid zip file.") from exc
        except json.JSONDecodeError as exc:
            raise MigrationPackError("Invalid migration pack manifest.") from exc

        pack_version = str(manifest.get("pack_version", ""))
        if not pack_version.startswith("1"):
            raise MigrationPackError(f"Unsupported migration pack version: {pack_version}")

    def import_pack(self, archive: Path) -> Path:
        """Restore a migration pack over the current application directories.

        Returns the path of the safety backup taken before the import.
        """
        archive = Path(archive)
        self.validate_pack(archive)

        data_dir = self._config.get_data_directory()
        backup_dir = self._config.get_backups_directory()
        backup_dir.mkdir(parents=True, exist_ok=True)
        safety = backup_dir / f"pre_import_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copytree(data_dir, safety, dirs_exist_ok=True)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with zipfile.ZipFile(archive, "r") as zf:
                zf.extractall(tmp_path)

            # Merge config settings but keep the target machine's directory layout.
            src_config_path = tmp_path / "config.json"
            if src_config_path.exists():
                try:
                    src_cfg = json.loads(src_config_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    raise MigrationPackError("Invalid config.json in pack.") from exc

                current_cfg = self._config.load()
                for key, value in src_cfg.items():
                    if key in self._PATH_KEYS:
                        continue
                    current_cfg[key] = value

                # Remote database support is staged; force local mode if not enabled.
                if not AppConfig.REMOTE_DATABASE_ENABLED:
                    current_cfg["database_mode"] = "sqlite"

                self._config.save(current_cfg)

            # Replace the data directory wholesale.
            src_data = tmp_path / "data"
            if src_data.exists():
                if data_dir.exists():
                    shutil.rmtree(data_dir)
                shutil.copytree(src_data, data_dir)

            # Merge user files into the current configured directories.
            self._merge_dir(tmp_path / "documents", self._config.get_documents_directory())
            self._merge_dir(tmp_path / "exports", self._config.get_exports_directory())
            self._merge_dir(tmp_path / "logs", self._config.get_logs_directory())
            self._merge_dir(tmp_path / "backups", self._config.get_backups_directory())

        return safety

    @staticmethod
    def _add_dir(
        zf: zipfile.ZipFile,
        source: Path,
        arc_prefix: str,
        exclude: Path | None = None,
    ) -> None:
        if not source.exists():
            return
        for path in source.rglob("*"):
            if not path.is_file():
                continue
            if exclude and path.resolve() == exclude:
                continue
            arcname = f"{arc_prefix}/{path.relative_to(source).as_posix()}"
            zf.write(path, arcname)

    @staticmethod
    def _merge_dir(source: Path, destination: Path) -> None:
        if not source.exists():
            return
        destination.mkdir(parents=True, exist_ok=True)
        for path in source.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(source)
            dest_file = destination / rel
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            with contextlib.suppress(OSError):
                shutil.copy2(path, dest_file)
