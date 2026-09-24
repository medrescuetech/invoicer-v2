from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from invoice_manager.persistence.clock import utc_now


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    force_password_change: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)


class BusinessProfile(Base):
    __tablename__ = "business_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_name: Mapped[str] = mapped_column(String(200), default="")
    abn: Mapped[str] = mapped_column(String(20), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    phone: Mapped[str] = mapped_column(String(80), default="")
    email: Mapped[str] = mapped_column(String(254), default="")
    bank_instructions: Mapped[str] = mapped_column(Text, default="")
    gst_registered: Mapped[bool] = mapped_column(Boolean, default=False)
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), default="AUD")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Client(Base):
    __tablename__ = "clients"
    __table_args__ = {"sqlite_autoincrement": True}
    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200), index=True)
    legal_name: Mapped[str] = mapped_column(String(200), default="")
    abn: Mapped[str] = mapped_column(String(20), default="")
    contact_name: Mapped[str] = mapped_column(String(160), default="")
    email: Mapped[str] = mapped_column(String(254), default="")
    phone: Mapped[str] = mapped_column(String(80), default="")
    billing_address: Mapped[str] = mapped_column(Text, default="")
    default_terms_days: Mapped[int] = mapped_column(Integer, default=14)
    default_notes: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (
        CheckConstraint("type IN ('income', 'expense')", name="ck_category_type"),
        UniqueConstraint("type", "name", name="uq_category_type_name"),
    )


class ServiceItem(Base):
    __tablename__ = "service_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), default="")
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    unit: Mapped[str] = mapped_column(String(40), default="each")
    unit_price_cents: Mapped[int] = mapped_column(Integer, default=0)
    taxable: Mapped[bool] = mapped_column(Boolean, default=False)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL")
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (
        CheckConstraint("unit_price_cents >= 0", name="ck_service_price"),
        {"sqlite_autoincrement": True},
    )


class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_number: Mapped[str | None] = mapped_column(String(30), unique=True, index=True)
    original_number: Mapped[str | None] = mapped_column(String(80))
    status_override: Mapped[str | None] = mapped_column(String(20))
    invoice_date: Mapped[date] = mapped_column(Date, index=True)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="RESTRICT"), index=True
    )
    client_name_snapshot: Mapped[str] = mapped_column(String(200), default="")
    client_abn_snapshot: Mapped[str] = mapped_column(String(20), default="")
    client_contact_snapshot: Mapped[str] = mapped_column(String(160), default="")
    client_email_snapshot: Mapped[str] = mapped_column(String(254), default="")
    client_phone_snapshot: Mapped[str] = mapped_column(String(80), default="")
    client_address_snapshot: Mapped[str] = mapped_column(Text, default="")
    business_name_snapshot: Mapped[str] = mapped_column(String(200), default="")
    business_abn_snapshot: Mapped[str] = mapped_column(String(20), default="")
    business_address_snapshot: Mapped[str] = mapped_column(Text, default="")
    business_phone_snapshot: Mapped[str] = mapped_column(String(80), default="")
    business_email_snapshot: Mapped[str] = mapped_column(String(254), default="")
    bank_instructions_snapshot: Mapped[str] = mapped_column(Text, default="")
    gst_registered_snapshot: Mapped[bool] = mapped_column(Boolean, default=False)
    gst_rate_snapshot: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=Decimal("0"))
    reference: Mapped[str] = mapped_column(String(160), default="")
    visible_notes: Mapped[str] = mapped_column(Text, default="")
    internal_notes: Mapped[str] = mapped_column(Text, default="")
    subtotal_cents: Mapped[int] = mapped_column(Integer, default=0)
    gst_cents: Mapped[int] = mapped_column(Integer, default=0)
    total_cents: Mapped[int] = mapped_column(Integer, default=0)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime)
    correction_reason: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(30), default="manual")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    items: Mapped[list[InvoiceItem]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )
    __table_args__ = (
        CheckConstraint(
            "status_override IS NULL OR status_override IN ('Cancelled','Void')",
            name="ck_invoice_override",
        ),
        CheckConstraint(
            "subtotal_cents >= 0 AND gst_cents >= 0 AND total_cents >= 0", name="ck_invoice_money"
        ),
        {"sqlite_autoincrement": True},
    )


class InvoiceItem(Base):
    __tablename__ = "invoice_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    service_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("service_items.id", ondelete="SET NULL")
    )
    service_code_snapshot: Mapped[str] = mapped_column(String(80), default="")
    description: Mapped[str] = mapped_column(Text)
    quantity_decimal: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("1"))
    unit: Mapped[str] = mapped_column(String(40), default="each")
    unit_price_cents: Mapped[int] = mapped_column(Integer, default=0)
    discount_type: Mapped[str] = mapped_column(String(20), default="none")
    discount_value: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    discount_cents: Mapped[int] = mapped_column(Integer, default=0)
    taxable: Mapped[bool] = mapped_column(Boolean, default=False)
    gst_rate_decimal: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=Decimal("0"))
    subtotal_cents: Mapped[int] = mapped_column(Integer, default=0)
    gst_cents: Mapped[int] = mapped_column(Integer, default=0)
    total_cents: Mapped[int] = mapped_column(Integer, default=0)
    invoice: Mapped[Invoice] = relationship(back_populates="items")
    __table_args__ = (
        CheckConstraint(
            "quantity_decimal > 0 AND unit_price_cents >= 0", name="ck_item_quantity_price"
        ),
        CheckConstraint(
            "discount_cents >= 0 AND subtotal_cents >= 0 AND gst_cents >= 0 AND total_cents >= 0",
            name="ck_item_money",
        ),
    )


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), index=True
    )
    payment_date: Mapped[date | None] = mapped_column(Date, index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(40), default="")
    reference: Mapped[str] = mapped_column(String(160), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(30), default="manual")
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime)
    reversal_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="ck_payment_positive"),
        {"sqlite_autoincrement": True},
    )


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = {"sqlite_autoincrement": True}
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(40), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    document_type: Mapped[str] = mapped_column(String(40))
    managed_relative_path: Mapped[str | None] = mapped_column(String(500))
    external_path: Mapped[str | None] = mapped_column(String(1000))
    original_filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    mime_type: Mapped[str] = mapped_column(String(120), default="application/pdf")
    source: Mapped[str] = mapped_column(String(30), default="generated")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    missing_last_checked: Mapped[datetime | None] = mapped_column(DateTime)


class Receipt(Base):
    __tablename__ = "receipts"
    __table_args__ = {"sqlite_autoincrement": True}
    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_number: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    original_number: Mapped[str | None] = mapped_column(String(80))
    payment_id: Mapped[int] = mapped_column(
        ForeignKey("payments.id", ondelete="CASCADE"), unique=True
    )
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    source: Mapped[str] = mapped_column(String(30), default="generated")


class CreditNote(Base):
    __tablename__ = "credit_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_number: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), index=True
    )
    credit_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(Text)
    subtotal_cents: Mapped[int] = mapped_column(Integer, default=0)
    gst_cents: Mapped[int] = mapped_column(Integer, default=0)
    total_cents: Mapped[int] = mapped_column(Integer, default=0)
    voided: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    __table_args__ = (
        CheckConstraint(
            "subtotal_cents >= 0 AND gst_cents >= 0 AND total_cents >= 0", name="ck_credit_money"
        ),
        {"sqlite_autoincrement": True},
    )


class CreditNoteItem(Base):
    __tablename__ = "credit_note_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    credit_note_id: Mapped[int] = mapped_column(
        ForeignKey("credit_notes.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    quantity_decimal: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("1"))
    unit_price_cents: Mapped[int] = mapped_column(Integer, default=0)
    taxable: Mapped[bool] = mapped_column(Boolean, default=False)
    gst_cents: Mapped[int] = mapped_column(Integer, default=0)
    total_cents: Mapped[int] = mapped_column(Integer, default=0)


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    type: Mapped[str] = mapped_column(String(20))
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL")
    )
    description: Mapped[str] = mapped_column(Text)
    ex_gst_cents: Mapped[int] = mapped_column(Integer, default=0)
    gst_cents: Mapped[int] = mapped_column(Integer, default=0)
    total_cents: Mapped[int] = mapped_column(Integer, default=0)
    supplier_payee: Mapped[str] = mapped_column(String(200), default="")
    payment_method: Mapped[str] = mapped_column(String(40), default="")
    reference: Mapped[str] = mapped_column(String(160), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime)
    reversal_reason: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(30), default="manual")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    __table_args__ = (
        CheckConstraint("type IN ('income', 'expense')", name="ck_ledger_type"),
        CheckConstraint(
            "ex_gst_cents >= 0 AND gst_cents >= 0 AND total_cents >= 0", name="ck_ledger_money"
        ),
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str] = mapped_column(Text)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str | None] = mapped_column(String(80), index=True)


class NumberSequence(Base):
    __tablename__ = "number_sequences"
    id: Mapped[int] = mapped_column(primary_key=True)
    sequence_type: Mapped[str] = mapped_column(String(20), unique=True)
    prefix: Mapped[str] = mapped_column(String(10))
    next_value: Mapped[int] = mapped_column(Integer, default=1)
    padding: Mapped[int] = mapped_column(Integer, default=4)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    __table_args__ = (CheckConstraint("next_value > 0 AND padding > 0", name="ck_sequence_values"),)


class MigrationRun(Base):
    __tablename__ = "migration_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    started: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished: Mapped[datetime | None] = mapped_column(DateTime)
    source_description: Mapped[str] = mapped_column(Text)
    source_manifest_hash: Mapped[str] = mapped_column(String(64), default="")
    result: Mapped[str] = mapped_column(String(30), default="started")
    counts_totals_json: Mapped[str] = mapped_column(Text, default="{}")
    report_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )


class MigrationIssue(Base):
    __tablename__ = "migration_issues"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("migration_runs.id", ondelete="CASCADE"), index=True
    )
    severity: Mapped[str] = mapped_column(String(20))
    issue_code: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(80))
    source_key: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text)
    proposed_resolution: Mapped[str] = mapped_column(Text, default="")
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
