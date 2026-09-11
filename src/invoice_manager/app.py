"""Application bootstrap and entry point."""

from __future__ import annotations

import sys
from typing import Any

from invoice_manager.infrastructure.config import AppConfig
from invoice_manager.infrastructure.logging_setup import get_logger, setup_logging


def _install_exception_hook() -> None:
    log = get_logger("invoice_manager.app")

    def _handler(
        exc_type: type[BaseException],
        exc_value: BaseException | None,
        exc_traceback: Any | None,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            if exc_value is not None:
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        if exc_value is None:
            log.error("Uncaught exception: %s", exc_type)
            return
        log.exception(
            "Uncaught exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    sys.excepthook = _handler


def main() -> int:
    """Launch the Invoice & Receipt Manager."""
    config = AppConfig()
    setup_logging(config.get_logs_directory())
    _install_exception_hook()
    log = get_logger("invoice_manager.app")

    lock = None
    if sys.platform == "win32":
        from invoice_manager.infrastructure.instance_lock import InstanceLock

        lock = InstanceLock()
        if not lock.acquire():
            log.warning("Another instance is already running")
            return 0

    try:
        from PySide6.QtWidgets import QApplication

        from invoice_manager.ui.login import run_login_flow
        from invoice_manager.ui.main_window import MainWindow

        app = QApplication(sys.argv)
        app.setApplicationName("Invoice & Receipt Manager")
        app.setApplicationVersion("2.0.10")

        current_user = run_login_flow(config)
        if not current_user:
            log.info("Login cancelled")
            return 0

        window = MainWindow(config, current_user)
        window.show()
        return app.exec()
    except Exception as exc:  # noqa: BLE001
        log.exception("Fatal error during startup: %s", exc)
        try:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.critical(
                None,
                "Application startup failed",
                f"The database could not be opened. Check the database configuration and password environment variable.\n\n{exc}",
            )
        except Exception:  # noqa: BLE001
            pass
        return 1
    finally:
        if lock is not None:
            lock.release()


if __name__ == "__main__":
    sys.exit(main())
