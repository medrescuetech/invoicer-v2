"""Shared application context for UI pages."""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import QObject, QTimer, Signal
from sqlalchemy import event

from invoice_manager.application.invoice_service import InvoiceService
from invoice_manager.application.ledger_service import LedgerService
from invoice_manager.application.payment_service import PaymentService
from invoice_manager.infrastructure.audit import AuditService
from invoice_manager.infrastructure.config import AppConfig
from invoice_manager.infrastructure.file_store import FileStore
from invoice_manager.persistence.database import Database
from invoice_manager.persistence.repositories import (
    AuditRepository,
    ClientRepository,
    InvoiceRepository,
    LedgerRepository,
    PaymentRepository,
    ServiceItemRepository,
    SettingRepository,
)


class AppContext(QObject):
    """Holds database session, config, file store, and application services."""

    data_changed = Signal()

    def __init__(self, config: AppConfig, current_user: str) -> None:
        super().__init__()
        self.config = config
        self.current_user = current_user
        self.database = Database(config.database_url())
        self.database.create_schema()
        self.session = self.database.new_session()
        # Defer the signal so consumers do not query the session while it is still
        # inside the commit event.
        event.listen(
            self.session,
            "after_commit",
            lambda _session: QTimer.singleShot(0, self.data_changed.emit),
        )
        self.file_store = FileStore(config.get_data_directory())

        self.client_repo = ClientRepository(self.session)
        self.invoice_repo = InvoiceRepository(self.session)
        self.payment_repo = PaymentRepository(self.session)
        self.service_repo = ServiceItemRepository(self.session)
        self.ledger_repo = LedgerRepository(self.session)
        self.setting_repo = SettingRepository(self.session)

        self.audit = AuditService(
            repository=AuditRepository(self.session),
            current_user=current_user,
        )

        gst_rate = Decimal(self.setting_repo.get("gst_rate") or "0.0")
        payment_terms = int(self.setting_repo.get("payment_terms_days") or 7)
        self.invoice_service = InvoiceService(
            invoice_repo=self.invoice_repo,
            client_repo=self.client_repo,
            payment_repo=self.payment_repo,
            setting_repo=self.setting_repo,
            audit=self.audit,
            gst_rate=gst_rate,
            payment_terms_days=payment_terms,
        )
        self.ledger_service = LedgerService(self.ledger_repo, self.audit)
        self.payment_service = PaymentService(
            payment_repo=self.payment_repo,
            invoice_repo=self.invoice_repo,
            setting_repo=self.setting_repo,
            audit=self.audit,
            ledger_service=self.ledger_service,
        )
