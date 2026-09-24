"""Pure invoice line and total calculations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from invoice_manager.domain.money import MoneyError, _decimal


@dataclass(frozen=True)
class LineCalculation:
    gross_cents: int
    discount_cents: int
    subtotal_cents: int
    gst_cents: int
    total_cents: int


@dataclass(frozen=True)
class InvoiceCalculation:
    subtotal_cents: int
    gst_cents: int
    total_cents: int
    lines: tuple[LineCalculation, ...]


def calculate_line(
    quantity: Decimal | str | int,
    unit_price_cents: int,
    *,
    discount_type: str = "none",
    discount_value: Decimal | str | int = 0,
    taxable: bool = False,
    gst_rate: Decimal | str | int = 0,
) -> LineCalculation:
    """Calculate a line; GST rates are fractions, discount percentages are 0-100."""
    q = _decimal(quantity)
    if q <= 0 or not isinstance(unit_price_cents, int) or unit_price_cents < 0:
        raise MoneyError("quantity must be positive and unit price cannot be negative")
    gross = int((q * Decimal(unit_price_cents)).quantize(Decimal("1"), ROUND_HALF_UP))
    discount = _decimal(discount_value)
    if discount < 0:
        raise MoneyError("discount cannot be negative")
    if discount_type == "percentage":
        if discount > 100:
            raise MoneyError("percentage discount cannot exceed 100")
        discount_cents = int(
            (Decimal(gross) * discount / 100).quantize(Decimal("1"), ROUND_HALF_UP)
        )
    elif discount_type in ("none", "fixed"):
        discount_cents = int(discount.quantize(Decimal("1"), ROUND_HALF_UP))
    else:
        raise ValueError("discount type must be none, fixed, or percentage")
    if discount_cents > gross:
        raise MoneyError("discount cannot exceed gross amount")
    subtotal = gross - discount_cents
    rate = _decimal(gst_rate)
    if not 0 <= rate <= 1:
        raise MoneyError("GST rate must be a decimal fraction between 0 and 1")
    gst = int((Decimal(subtotal) * rate).quantize(Decimal("1"), ROUND_HALF_UP)) if taxable else 0
    return LineCalculation(gross, discount_cents, subtotal, gst, subtotal + gst)


def calculate_invoice(lines: list[LineCalculation]) -> InvoiceCalculation:
    return InvoiceCalculation(
        subtotal_cents=sum(line.subtotal_cents for line in lines),
        gst_cents=sum(line.gst_cents for line in lines),
        total_cents=sum(line.total_cents for line in lines),
        lines=tuple(lines),
    )
