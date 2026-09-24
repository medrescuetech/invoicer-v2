from __future__ import annotations

import builtins
import csv
import io
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from invoice_manager.application.audit import AuditService
from invoice_manager.persistence.clock import utc_now
from invoice_manager.persistence.models import Client, CreditNote, Invoice, Payment


def _normalise(value: str) -> str:
    return " ".join(value.casefold().split())


@dataclass(frozen=True)
class ClientRollup:
    invoice_count: int
    billed_cents: int
    paid_cents: int
    balance_cents: int
    overdue_cents: int
    last_invoice_date: date | None


class ClientService:
    def __init__(self, audit: AuditService | None = None) -> None:
        self.audit = audit or AuditService()

    def list(
        self, session: Session, search: str = "", *, active_only: bool = False
    ) -> builtins.list[Client]:
        stmt = select(Client).order_by(Client.display_name)
        if active_only:
            stmt = stmt.where(Client.active.is_(True))
        if search.strip():
            term = f"%{search.strip()}%"
            stmt = stmt.where(
                Client.display_name.ilike(term)
                | Client.legal_name.ilike(term)
                | Client.email.ilike(term)
                | Client.phone.ilike(term)
            )
        return list(session.scalars(stmt).all())

    def duplicates(
        self,
        session: Session,
        *,
        display_name: str,
        email: str = "",
        phone: str = "",
        exclude_id: int | None = None,
    ) -> builtins.list[Client]:
        values = [v for v in (_normalise(display_name), _normalise(email), _normalise(phone)) if v]
        if not values:
            return []
        result = []
        for client in session.scalars(select(Client)).all():
            if client.id == exclude_id:
                continue
            candidates = (
                _normalise(client.display_name),
                _normalise(client.email),
                _normalise(client.phone),
            )
            if any(value in candidates for value in values):
                result.append(client)
        return result

    def create(
        self,
        session: Session,
        *,
        display_name: str,
        legal_name: str = "",
        abn: str = "",
        contact_name: str = "",
        email: str = "",
        phone: str = "",
        billing_address: str = "",
        default_terms_days: int = 0,
        default_notes: str = "",
        active: bool = True,
        user_id: int | None = None,
    ) -> Client:
        if not display_name.strip():
            raise ValueError("display name is required")
        if self.duplicates(
            session,
            display_name=display_name,
            email=email,
            phone=phone,
        ):
            raise ValueError("possible duplicate client")
        client = Client(
            display_name=display_name.strip(),
            legal_name=legal_name,
            abn=abn,
            contact_name=contact_name,
            email=email,
            phone=phone,
            billing_address=billing_address,
            default_terms_days=default_terms_days,
            default_notes=default_notes,
            active=active,
        )
        session.add(client)
        session.flush()
        self.audit.record(
            session,
            action="create",
            entity_type="client",
            entity_id=client.id,
            summary="Created client",
            user_id=user_id,
            after={"display_name": client.display_name},
        )
        return client

    def update(
        self,
        session: Session,
        client: Client,
        *,
        display_name: str | None = None,
        legal_name: str | None = None,
        abn: str | None = None,
        contact_name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        billing_address: str | None = None,
        default_terms_days: int | None = None,
        default_notes: str | None = None,
        active: bool | None = None,
        user_id: int | None = None,
    ) -> Client:
        before = {"display_name": client.display_name, "email": client.email}
        proposed_name = display_name if display_name is not None else client.display_name
        proposed_email = email if email is not None else client.email
        proposed_phone = phone if phone is not None else client.phone
        if self.duplicates(
            session,
            display_name=proposed_name,
            email=proposed_email,
            phone=proposed_phone,
            exclude_id=client.id,
        ):
            raise ValueError("possible duplicate client")
        if display_name is not None:
            client.display_name = display_name
        if legal_name is not None:
            client.legal_name = legal_name
        if abn is not None:
            client.abn = abn
        if contact_name is not None:
            client.contact_name = contact_name
        if email is not None:
            client.email = email
        if phone is not None:
            client.phone = phone
        if billing_address is not None:
            client.billing_address = billing_address
        if default_terms_days is not None:
            client.default_terms_days = default_terms_days
        if default_notes is not None:
            client.default_notes = default_notes
        if active is not None:
            client.active = active
        if not client.display_name.strip():
            raise ValueError("display name is required")
        client.updated_at = utc_now()
        session.flush()
        self.audit.record(
            session,
            action="update",
            entity_type="client",
            entity_id=client.id,
            summary="Updated client",
            user_id=user_id,
            before=before,
            after={"display_name": client.display_name, "email": client.email},
        )
        return client

    def deactivate(self, session: Session, client: Client, *, user_id: int | None = None) -> None:
        client.active = False
        self.audit.record(
            session,
            action="deactivate",
            entity_type="client",
            entity_id=client.id,
            summary="Deactivated client",
            user_id=user_id,
        )

    def delete(self, session: Session, client: Client, *, user_id: int | None = None) -> None:
        if session.scalar(select(Invoice.id).where(Invoice.client_id == client.id).limit(1)):
            raise ValueError("client is referenced by invoices")
        session.delete(client)
        self.audit.record(
            session,
            action="delete",
            entity_type="client",
            entity_id=client.id,
            summary="Deleted client",
            user_id=user_id,
        )

    def merge(
        self, session: Session, source: Client, target: Client, *, user_id: int | None = None
    ) -> Client:
        if source.id == target.id:
            raise ValueError("cannot merge a client into itself")
        if not target.active:
            raise ValueError("merge target must be active")
        invoices = list(
            session.scalars(select(Invoice).where(Invoice.client_id == source.id)).all()
        )
        for invoice in invoices:
            invoice.client_id = target.id
        source.active = False
        session.flush()
        self.audit.record(
            session,
            action="merge",
            entity_type="client",
            entity_id=target.id,
            summary=f"Merged client {source.id} into {target.id}",
            before={"source_id": source.id, "invoice_ids": [i.id for i in invoices]},
            after={"target_id": target.id},
            user_id=user_id,
        )
        return target

    def rollup(self, session: Session, client: Client) -> ClientRollup:
        invoices = list(
            invoice
            for invoice in session.scalars(
                select(Invoice).where(Invoice.client_id == client.id)
            ).all()
            if invoice.issued_at is not None
            and invoice.status_override not in ("Cancelled", "Void")
        )
        invoice_ids = [invoice.id for invoice in invoices]
        payments = (
            sum(
                p.amount_cents
                for p in session.scalars(
                    select(Payment).where(Payment.invoice_id.in_(invoice_ids))
                ).all()
                if p.reversed_at is None
            )
            if invoice_ids
            else 0
        )
        credits = (
            sum(
                c.total_cents
                for c in session.scalars(
                    select(CreditNote).where(CreditNote.invoice_id.in_(invoice_ids))
                ).all()
                if not c.voided
            )
            if invoice_ids
            else 0
        )
        billed = sum(i.total_cents for i in invoices)
        overdue = 0
        today = date.today()
        for invoice in invoices:
            if invoice.due_date < today and invoice.status_override not in ("Cancelled", "Void"):
                paid = sum(
                    p.amount_cents
                    for p in session.scalars(
                        select(Payment).where(Payment.invoice_id == invoice.id)
                    ).all()
                    if p.reversed_at is None
                )
                credited = sum(
                    c.total_cents
                    for c in session.scalars(
                        select(CreditNote).where(CreditNote.invoice_id == invoice.id)
                    ).all()
                    if not c.voided
                )
                overdue += max(invoice.total_cents - paid - credited, 0)
        return ClientRollup(
            invoice_count=len(invoices),
            billed_cents=billed,
            paid_cents=payments,
            balance_cents=billed - payments - credits,
            overdue_cents=overdue,
            last_invoice_date=max((i.invoice_date for i in invoices), default=None),
        )

    def export_csv(self, session: Session, clients: builtins.list[Client] | None = None) -> str:
        output = io.StringIO()
        fields = ["id", "display_name", "legal_name", "email", "phone", "active"]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for client in clients or self.list(session):
            writer.writerow({field: getattr(client, field) for field in fields})
        return output.getvalue()
