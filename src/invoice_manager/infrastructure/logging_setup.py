"""Application logging setup."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def get_exe_log_path() -> Path | None:
    """Return a log path next to the frozen executable, or None if not frozen."""
    if not getattr(sys, "frozen", False):
        return None
    # sys.argv[0] points at the outer one-file executable location.
    exe_path = Path(sys.argv[0]).resolve()
    return exe_path.parent / f"{exe_path.stem}.log"


def _can_write_dir(path: Path) -> bool:
    """Check whether *path* can be created and written to."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        test_file = path / ".write_test"
        test_file.write_text("", encoding="utf-8")
        test_file.unlink()
        return True
    except OSError:
        return False


def _fallback_log_dir() -> Path:
    """Return a user-writable log directory."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "InvoiceReceiptManager" / "logs"
    return Path.home() / ".invoice_receipt_manager" / "logs"


def _add_file_handler(root_logger: logging.Logger, log_path: Path, level: int) -> None:
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler = RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=10,
            encoding="utf-8",
        )
        handler.setLevel(level)
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
    except OSError:
        # If the requested log location is not writable, skip the file handler
        # rather than preventing the application from starting.
        pass


def setup_logging(log_dir: Path, app_name: str = "invoice_manager") -> Path:
    """Configure rotating file logging and return the log file path."""
    log_dir = Path(log_dir)
    if not _can_write_dir(log_dir):
        log_dir = _fallback_log_dir()
    if not _can_write_dir(log_dir):
        # Last resort: use the current working directory so the app can start.
        log_dir = Path.cwd() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

    log_path = log_dir / "application.log"
    error_log_path = log_dir / "error.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Clear existing handlers to make the function idempotent in tests.
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    _add_file_handler(root_logger, log_path, logging.DEBUG)
    _add_file_handler(root_logger, error_log_path, logging.ERROR)

    exe_log_path = get_exe_log_path()
    if exe_log_path is not None:
        _add_file_handler(root_logger, exe_log_path, logging.DEBUG)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    logging.getLogger(app_name).info(
        "Logging initialised: application=%s errors=%s", log_path, error_log_path
    )
    if exe_log_path is not None:
        logging.getLogger(app_name).info("Executable log: %s", exe_log_path)
    return log_path


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
