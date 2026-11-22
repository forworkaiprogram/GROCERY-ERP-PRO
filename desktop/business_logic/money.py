"""Monetary and quantity arithmetic. Decimal only — floats are prohibited.

All monetary values are stored as TEXT decimal strings in SQLite and parsed
into Decimal at the boundary. Quantities use Decimal as well (fractional
weights like 0.250 kg are legal; floats are never used in arithmetic).
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

TWO_DP = Decimal("0.01")
FOUR_DP = Decimal("0.0001")


class MoneyError(ValueError):
    pass


def D(value) -> Decimal:
    """Parse a decimal string / int / Decimal. Floats are rejected."""
    if isinstance(value, float):
        raise MoneyError("float is prohibited for money/quantity values")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).strip() or "0")
    except InvalidOperation as exc:
        raise MoneyError(f"invalid decimal: {value!r}") from exc


def money(value) -> str:
    """Normalize to 2dp decimal string (YER usually has no minor unit, keep 2)."""
    return str(D(value).quantize(TWO_DP, ROUND_HALF_UP))


def qty(value) -> str:
    return str(D(value).quantize(FOUR_DP, ROUND_HALF_UP))


def tax_of(base: Decimal, rate_bps: int) -> Decimal:
    """Tax computed in basis points: 1500 bps = 15%."""
    if rate_bps < 0:
        raise MoneyError("tax rate cannot be negative")
    return (base * Decimal(rate_bps) / Decimal(10000)).quantize(TWO_DP, ROUND_HALF_UP)


def discount_of(line_gross: Decimal, bps: int) -> Decimal:
    if bps < 0:
        raise MoneyError("discount cannot be negative")
    return (line_gross * Decimal(bps) / Decimal(10000)).quantize(TWO_DP, ROUND_HALF_UP)


def assert_balanced(debits: Decimal, credits: Decimal) -> None:
    if debits != credits:
        raise MoneyError(
            f"unbalanced journal entry: debits {debits} != credits {credits}"
        )
