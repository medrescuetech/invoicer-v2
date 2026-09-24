from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from invoice_manager.application.audit import AuditService
from invoice_manager.persistence.models import ServiceItem


class ServiceItemService:
    def __init__(self, audit: AuditService | None = None) -> None:
        self.audit = audit or AuditService()

    def list(
        self, session: Session, search: str = "", *, active_only: bool = False
    ) -> list[ServiceItem]:
        stmt = select(ServiceItem).order_by(ServiceItem.name)
        if active_only:
            stmt = stmt.where(ServiceItem.active.is_(True))
        if search.strip():
            term = f"%{search.strip()}%"
            stmt = stmt.where(
                ServiceItem.name.ilike(term)
                | ServiceItem.code.ilike(term)
                | ServiceItem.description.ilike(term)
            )
        return list(session.scalars(stmt).all())

    def create(
        self,
        session: Session,
        *,
        name: str,
        code: str = "",
        description: str = "",
        unit: str = "each",
        unit_price_cents: int = 0,
        taxable: bool = False,
        category_id: int | None = None,
        active: bool = True,
        user_id: int | None = None,
    ) -> ServiceItem:
        if not name.strip():
            raise ValueError("service name is required")
        if unit_price_cents < 0:
            raise ValueError("unit price cannot be negative")
        if not unit.strip():
            raise ValueError("service unit is required")
        item = ServiceItem(
            code=code.strip(),
            name=name.strip(),
            description=description.strip(),
            unit=unit.strip() or "each",
            unit_price_cents=unit_price_cents,
            taxable=taxable,
            category_id=category_id,
            active=active,
        )
        session.add(item)
        session.flush()
        self.audit.record(
            session,
            action="create",
            entity_type="service_item",
            entity_id=item.id,
            summary="Created service item",
            user_id=user_id,
        )
        return item

    def update(
        self,
        session: Session,
        item: ServiceItem,
        *,
        name: str | None = None,
        code: str | None = None,
        description: str | None = None,
        unit: str | None = None,
        unit_price_cents: int | None = None,
        taxable: bool | None = None,
        category_id: int | None = None,
        active: bool | None = None,
        user_id: int | None = None,
    ) -> ServiceItem:
        before = {"name": item.name, "unit_price_cents": item.unit_price_cents}
        if name is not None and not name.strip():
            raise ValueError("service name is required")
        if unit is not None and not unit.strip():
            raise ValueError("service unit is required")
        if name is not None:
            item.name = name.strip()
        if code is not None:
            item.code = code.strip()
        if description is not None:
            item.description = description.strip()
        if unit is not None:
            item.unit = unit.strip() or "each"
        if unit_price_cents is not None:
            if unit_price_cents < 0:
                raise ValueError("unit price cannot be negative")
            item.unit_price_cents = unit_price_cents
        if taxable is not None:
            item.taxable = taxable
        if category_id is not None:
            item.category_id = category_id
        if active is not None:
            item.active = active
        if not item.name.strip() or item.unit_price_cents < 0 or not item.unit.strip():
            raise ValueError("invalid service item")
        session.flush()
        self.audit.record(
            session,
            action="update",
            entity_type="service_item",
            entity_id=item.id,
            summary="Updated service item",
            before=before,
            after={"name": item.name, "unit_price_cents": item.unit_price_cents},
            user_id=user_id,
        )
        return item

    def set_active(
        self, session: Session, item: ServiceItem, active: bool, *, user_id: int | None = None
    ) -> None:
        item.active = active
        session.flush()
        self.audit.record(
            session,
            action="activate" if active else "deactivate",
            entity_type="service_item",
            entity_id=item.id,
            summary="Changed service item active state",
            user_id=user_id,
        )
