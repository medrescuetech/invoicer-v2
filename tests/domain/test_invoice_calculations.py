from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from invoice_manager.domain.invoice_calculations import (
    calculate_invoice,
    calculate_line,
)
from invoice_manager.domain.money import MoneyError


@given(
    quantity=st.decimals(min_value="0.01", max_value="100", places=2, allow_nan=False),
    unit_price=st.integers(min_value=0, max_value=100000),
    rate=st.decimals(min_value="0", max_value="1", places=2, allow_nan=False),
)
def test_line_and_invoice_totals_are_exact(quantity, unit_price, rate) -> None:
    line = calculate_line(quantity, unit_price, taxable=True, gst_rate=rate)
    total = calculate_invoice([line])
    assert total.subtotal_cents + total.gst_cents == total.total_cents


def test_discount_rounding_is_half_up() -> None:
    line = calculate_line(1, 101, discount_type="percentage", discount_value=Decimal("50"))
    assert line.discount_cents == 51
    assert line.total_cents == 50


def test_fractional_gst_rate_and_rejection() -> None:
    line = calculate_line(1, 10000, taxable=True, gst_rate=Decimal("0.1"))
    assert line.gst_cents == 1000
    assert line.total_cents == 11000
    with pytest.raises(MoneyError):
        calculate_line(1, 10000, taxable=True, gst_rate=Decimal("10"))
