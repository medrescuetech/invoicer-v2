"""SQLAlchemy ORM models for the invoice and receipt manager."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="admin")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now(UTC).replace(tzinfo=None)
    )


class Setting(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now(UTC).replace(tzinfo=None),
        onupdate=datetime.now(UTC).replace(tzinfo=None),
    )


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(Text)
    abn: Mapped[str | None] = mapped_column(String(32))
    notes: Mapped[str | None] = mapped_column(Text)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now(UTC).replace(tzinfo=None)
    )

    invoices: Mapped[list[Invoice]] = relationship(
        "Invoice", back_populates="client", lazy="dynamic"
    )


class ServiceItem(Base):
    __tablename__ = "service_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    unit_price_cents: Mapped[int] = mapped_column(Integer, default=0)
    unit: Mapped[str | None] = mapped_column(String(32), default="ea")
    taxable: Mapped[bool] = mapped_column(Boolean, default=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    issue_date: Mapped[Date] = mapped_column(Date, nullable=False)
    due_date: Mapped[Date | None] = mapped_column(Date)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"))
    client_name: Mapped[str] = mapped_column(String(255), nullable=False)
    client_address: Mapped[str | None] = mapped_column(Text)
    reference: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    internal_notes: Mapped[str | None] = mapped_column(Text)
    subtotal_cents: Mapped[int] = mapped_column(Integer, default=0)
    gst_cents: Mapped[int] = mapped_column(Integer, default=0)
    total_cents: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    is_cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    is_void: Mapped[bool] = mapped_column(Boolean, default=False)
    is_draft: Mapped[bool] = mapped_column(Boolean, default=True)
    pdf_path: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now(UTC).replace(tzinfo=None)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now(UTC).replace(tzinfo=None),
        onupdate=datetime.now(UTC).replace(tzinfo=None),
    )

    client: Mapped[Client | None] = relationship("Client", back_populates="invoices")
    items: Mapped[list[InvoiceItem]] = relationship(
        "InvoiceItem", back_populates="invoice", cascade="all, delete-orphan"
    )

    @property
    def is_quote(self) -> bool:
        """Return True when this record is a quote based on its number prefix."""
        return (self.number or "").upper().startswith("QTE")
    payments: Mapped[list[Payment]] = relationship(
        "Payment", back_populates="invoice", cascade="all, delete-orphan"
    )
    credits: Mapped[list[CreditNote]] = relationship("CreditNote", back_populates="invoice")


class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), nullable=False)
    service_item_id: Mapped[int | None] = mapped_column(ForeignKey("service_items.id"))
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit: Mapped[str | None] = mapped_column(String(32), default="ea")
    unit_price_cents: Mapped[int] = mapped_column(Integer, default=0)
    discount_cents: Mapped[int] = mapped_column(Integer, default=0)
    discount_percent: Mapped[int | None] = mapped_column(Integer)  # basis points
    taxable: Mapped[bool] = mapped_column(Boolean, default=True)
    subtotal_cents: Mapped[int] = mapped_column(Integer, default=0)
    gst_cents: Mapped[int] = mapped_column(Integer, default=0)
    total_cents: Mapped[int] = mapped_column(Integer, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    invoice: Mapped[Invoice] = relationship("Invoice", back_populates="items")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"))
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    date: Mapped[Date] = mapped_column(Date, nullable=False)
    method: Mapped[str | None] = mapped_column(String(64))
    reference: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    receipt_number: Mapped[str | None] = mapped_column(String(32), unique=True)
    is_reversed: Mapped[bool] = mapped_column(Boolean, default=False)
    reversal_reason: Mapped[str | None] = mapped_column(Text)
    pdf_path: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now(UTC).replace(tzinfo=None)
    )

    invoice: Mapped[Invoice | None] = relationship("Invoice", back_populates="payments")


class Receipt(Base):
    __tablename__ = "receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"))
    client_name: Mapped[str] = mapped_column(String(255), nullable=False)
    client_address: Mapped[str | None] = mapped_column(Text)
    date: Mapped[Date] = mapped_column(Date, nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str | None] = mapped_column(String(64))
    reference: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)
    pdf_path: Mapped[str | None] = mapped_column(String(500))
    docx_path: Mapped[str | None] = mapped_column(String(500))
    xlsx_path: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now(UTC).replace(tzinfo=None)
    )


class CreditNote(Base):
    __tablename__ = "credit_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    date: Mapped[Date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    pdf_path: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now(UTC).replace(tzinfo=None)
    )

    invoice: Mapped[Invoice] = relationship("Invoice", back_populates="credits")


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[Date] = mapped_column(Date, nullable=False)
    entry_type: Mapped[str] = mapped_column(String(16), nullable=False)  # in / out
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    reference: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    attachment_path: Mapped[str | None] = mapped_column(String(500))
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now(UTC).replace(tzinfo=None)
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now(UTC).replace(tzinfo=None)
    )
    user: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    table_name: Mapped[str | None] = mapped_column(String(64))
    record_id: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[str | None] = mapped_column(Text)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(500), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(64))  # invoice, client, ledger
    entity_id: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now(UTC).replace(tzinfo=None)
    )


class MigrationIssue(Base):
    __tablename__ = "migration_issues"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[str | None] = mapped_column(String(255))
    issue_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)  # info/warn/error
    message: Mapped[str] = mapped_column(Text, nullable=False)
    raw_data: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now(UTC).replace(tzinfo=None)
    )
