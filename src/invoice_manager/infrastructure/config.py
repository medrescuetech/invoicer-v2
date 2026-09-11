"""Application configuration and storage layout."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import URL


class AppConfig:
    """Manages the storage layout and runtime configuration file."""

    APP_DIR_NAME = "InvoiceReceiptManager"
    CONFIG_FILE = "config.json"
    REMOTE_DATABASE_ENABLED = False
    DEFAULT_CONFIG: dict[str, Any] = {
        "config_version": 1,
        "database_mode": "sqlite",
        "data_dir": "",
        "documents_dir": "",
        "exports_dir": "",
        "backups_dir": "",
        "logs_dir": "",
    }

    def __init__(self, base_dir: Path | None = None) -> None:
        if base_dir is None:
            base_dir = self._default_base_dir()
        self.base_dir = Path(base_dir)
        self.config_path = self.base_dir / self.CONFIG_FILE
        self.data_dir: Path = self.base_dir / "data"
        self.documents_dir: Path = self.base_dir / "documents"
        self.exports_dir: Path = self.base_dir / "exports"
        self.backups_dir: Path = self.base_dir / "backups"
        self.logs_dir: Path = self.base_dir / "logs"
        self._ensure_dirs()
        self._ensure_config()

    @classmethod
    def _default_base_dir(cls) -> Path:
        if getattr(sys, "frozen", False):
            # For PyInstaller one-file builds, sys.argv[0] is the outer
            # executable. Use the folder containing the exe only if a local
            # data tree exists and the directory is actually writable.
            exe_dir = Path(sys.argv[0]).resolve().parent
            if (exe_dir / "data").is_dir() and os.access(exe_dir, os.W_OK):
                return exe_dir
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / cls.APP_DIR_NAME
        return Path.home() / ".invoice_receipt_manager"

    def _ensure_dirs(self) -> None:
        for directory in (
            self.base_dir,
            self.data_dir,
            self.documents_dir,
            self.exports_dir,
            self.backups_dir,
            self.logs_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def _ensure_config(self) -> None:
        if not self.config_path.exists():
            self.save(dict(self.DEFAULT_CONFIG))

    def db_path(self) -> Path:
        return self.get_data_directory() / "business.sqlite3"

    def database_mode(self) -> str:
        if not self.REMOTE_DATABASE_ENABLED:
            return "sqlite"
        mode = str(self.load().get("database_mode", "sqlite")).lower()
        return mode if mode in {"sqlite", "mysql"} else "sqlite"

    def database_url(self) -> str | URL:
        if self.database_mode() == "sqlite":
            return f"sqlite:///{self.db_path()}"
        cfg = self.load()
        password_env = str(cfg.get("mysql_password_env", "INVOICE_MANAGER_DB_PASSWORD"))
        password = os.environ.get(password_env)
        if password is None:
            raise RuntimeError(f"Database password environment variable is not set: {password_env}")
        return URL.create(
            "mysql+pymysql",
            username=str(cfg.get("mysql_user", "")),
            password=password,
            host=str(cfg.get("mysql_host", "localhost")),
            port=int(cfg.get("mysql_port", 3306)),
            database=str(cfg.get("mysql_database", "invoice_manager")),
            query={"charset": "utf8mb4"},
        )

    def configure_database(self, values: dict[str, Any]) -> None:
        cfg = self.load()
        allowed = {
            "database_mode",
            "mysql_host",
            "mysql_port",
            "mysql_database",
            "mysql_user",
            "mysql_password_env",
        }
        cfg.update({key: value for key, value in values.items() if key in allowed})
        if not self.REMOTE_DATABASE_ENABLED:
            cfg["database_mode"] = "sqlite"
        self.save(cfg)

    def load(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {}
        try:
            with self.config_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    def save(self, values: dict[str, Any]) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        safe_values = {**self.DEFAULT_CONFIG, **values}
        temporary_path = self.config_path.with_suffix(".json.tmp")
        with temporary_path.open("w", encoding="utf-8") as f:
            json.dump(safe_values, f, indent=4)
            f.flush()
            os.fsync(f.fileno())
        temporary_path.replace(self.config_path)

    def get_data_directory(self) -> Path:
        cfg = self.load()
        custom = cfg.get("data_dir", "")
        if custom:
            path = Path(custom)
            path.mkdir(parents=True, exist_ok=True)
            return path
        return self.data_dir

    def get_backup_directory(self) -> Path:
        return self.backups_dir

    def get_documents_directory(self) -> Path:
        cfg = self.load()
        custom = cfg.get("documents_dir", "")
        if custom:
            path = Path(custom)
            path.mkdir(parents=True, exist_ok=True)
            return path
        return self.documents_dir

    def _custom_directory(self, key: str, default: Path) -> Path:
        cfg = self.load()
        custom = cfg.get(key, "")
        if custom:
            path = Path(custom)
            path.mkdir(parents=True, exist_ok=True)
            return path
        return default

    def get_exports_directory(self) -> Path:
        return self._custom_directory("exports_dir", self.exports_dir)

    def get_backups_directory(self) -> Path:
        return self._custom_directory("backups_dir", self.backups_dir)

    def get_logs_directory(self) -> Path:
        return self._custom_directory("logs_dir", self.logs_dir)

    def set_data_directory(self, path: Path) -> None:
        cfg = self.load()
        cfg["data_dir"] = str(Path(path))
        self.save(cfg)

    def set_documents_directory(self, path: Path) -> None:
        cfg = self.load()
        cfg["documents_dir"] = str(Path(path))
        self.save(cfg)

    def set_exports_directory(self, path: Path) -> None:
        cfg = self.load()
        cfg["exports_dir"] = str(Path(path))
        self.save(cfg)

    def set_backups_directory(self, path: Path) -> None:
        cfg = self.load()
        cfg["backups_dir"] = str(Path(path))
        self.save(cfg)

    def set_logs_directory(self, path: Path) -> None:
        cfg = self.load()
        cfg["logs_dir"] = str(Path(path))
        self.save(cfg)
