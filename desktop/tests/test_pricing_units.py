import json
from decimal import Decimal

import pytest

from desktop.business_logic.money import D, discount_of, money, tax_of
from desktop.business_logic.pricing import price_line, price_sale
from desktop.business_logic.units import ConversionError, UnitConverter

PRODUCT = {
    "uuid": "p1",
    "sku": "OIL",
    "price": "2500",
    "wholesale_price": "2400",
    "min_price": "2300",
    "cost": "2000",
    "tax_rate_bps": 500,
}


def test_tax_uses_bps_exact_decimal():
    base = D("1000.00")
    assert tax_of(base, 500) == Decimal("50.00")
    assert tax_of(base, 1500) == Decimal("150.00")


def test_discount_of_rounds_half_up():
    assert discount_of(D("999.99"), 500) == Decimal("50.00")


def test_float_is_rejected():
    with pytest.raises(Exception):
        D(25.5)


def test_line_pricing_snapshot_math():
    line = price_line(product=PRODUCT, quantity="3", unit="PIECE")
    assert line.unit_price == Decimal("2500.00")
    assert line.line_total == Decimal("7875.00")  # 3*2500 + 5%
    assert line.line_cost == Decimal("6000.00")


def test_min_price_guard_blocks_disoucnt_breach():
    with pytest.raises(Exception):
        price_line(
            product=PRODUCT,
            quantity="1",
            unit="PIECE",
            line_discount_bps=999,
        )


def test_wholesale_for_group_customer():
    customer = {"group_name": "WHOLESALE", "balance": "0", "credit_limit": "0"}
    line = price_line(product=PRODUCT, quantity="1", unit="PIECE", customer=customer)
    assert line.unit_price == Decimal("2400.00")


def test_sale_totals_and_snapshot():
    l1 = price_line(product=PRODUCT, quantity="2", unit="PIECE")
    cheap = dict(PRODUCT, price="1000", tax_rate_bps=0, cost="700", min_price="0")
    l2 = price_line(product=cheap, quantity="5", unit="PIECE")
    sale = price_sale([l1, l2])
    assert sale.subtotal == Decimal("10000.00")
    assert sale.tax_total == Decimal("250.00")
    assert sale.total == Decimal("10250.00")
    snapshot = json.loads(sale.as_snapshot())
    assert snapshot["total"] == "10250.00"


UNITS = [
    {"from_unit": "CARTON", "to_unit": "PACK", "numerator": 12, "denominator": 1},
    {"from_unit": "PACK", "to_unit": "PIECE", "numerator": 6, "denominator": 1},
    {"from_unit": "KG", "to_unit": "G", "numerator": 1000, "denominator": 1},
    {"from_unit": "L", "to_unit": "ML", "numerator": 1000, "denominator": 1},
]


def test_unit_conversion_chained_exact():
    conv = UnitConverter(UNITS)
    half_carton = conv.convert("0.5", "CARTON", "PIECE")
    assert half_carton == Decimal("36.0000")


def test_cross_dimension_conversion_rejected():
    conv = UnitConverter(UNITS)
    with pytest.raises(ConversionError):
        conv.convert("1", "KG", "PIECE")
