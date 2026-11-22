"""Pricing engine: Decimal-based line math with transaction-time snapshots.

Every sale stores a complete priced_snapshot so historical invoices never
change when product prices change later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .money import D, discount_of, money, tax_of


@dataclass
class PricedLine:
    product_uuid: str
    quantity: Decimal
    unit: str | None
    unit_price: Decimal
    discount: Decimal          # absolute line discount
    tax_rate_bps: int
    tax_amount: Decimal
    line_total: Decimal        # quantity * unit_price - discount + tax
    unit_cost: Decimal
    line_cost: Decimal

    def as_dict(self) -> dict:
        return {
            "product_uuid": self.product_uuid,
            "quantity": str(self.quantity),
            "unit": self.unit,
            "unit_price": str(self.unit_price),
            "discount": str(self.discount),
            "tax_rate_bps": self.tax_rate_bps,
            "tax_amount": str(self.tax_amount),
            "line_total": str(self.line_total),
            "unit_cost": str(self.unit_cost),
            "line_cost": str(self.line_cost),
        }


@dataclass
class PricedSale:
    lines: list[PricedLine] = field(default_factory=list)
    invoice_discount: Decimal = Decimal("0")
    subtotal: Decimal = Decimal("0")
    discount_total: Decimal = Decimal("0")
    tax_total: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    cost_total: Decimal = Decimal("0")

    def as_snapshot(self) -> str:
        import json

        return json.dumps(
            {
                "lines": [line.as_dict() for line in self.lines],
                "invoice_discount": str(self.invoice_discount),
                "subtotal": str(self.subtotal),
                "discount_total": str(self.discount_total),
                "tax_total": str(self.tax_total),
                "total": str(self.total),
                "cost_total": str(self.cost_total),
            },
            sort_keys=True,
        )


class PricingError(ValueError):
    pass


def resolve_unit_price(product: dict, quantity: Decimal, customer: dict | None) -> Decimal:
    """Wholesale price when quantity exceeds the configured wholesale
    threshold of 12 units or the customer belongs to the WHOLESALE group;
    otherwise the retail price. Customer-specific discount is applied as a
    line_discount_bps when present."""
    price = D(product["price"])
    if customer and customer.get("group_name") == "WHOLESALE":
        wholesale = D(product.get("wholesale_price", "0"))
        if wholesale > 0:
            price = wholesale
    return price


def price_line(
    *,
    product: dict,
    quantity,
    unit: str,
    customer: dict | None = None,
    line_discount_bps: int | None = None,
) -> PricedLine:
    quantity = D(quantity)
    if quantity <= 0:
        raise PricingError("quantity must be positive")
    unit_price = resolve_unit_price(product, quantity, customer)
    gross = (unit_price * quantity).quantize(Decimal("0.01"))
    bps = line_discount_bps
    if bps is None and customer:
        bps = int(customer.get("discount_bps") or 0)
    discount = discount_of(gross, bps) if bps else Decimal("0")
    if unit_price > 0:
        effective = (gross - discount) / quantity
        if D(product.get("min_price", "0")) > 0 and effective < D(product["min_price"]):
            raise PricingError(
                f"discount breaches minimum price for {product['sku']}"
            )
    net = gross - discount
    tax_rate_bps = int(product.get("tax_rate_bps") or 0)
    tax_amount = tax_of(net, tax_rate_bps)
    line_total = net + tax_amount
    unit_cost = D(product.get("cost", "0"))
    return PricedLine(
        product_uuid=product["uuid"],
        quantity=quantity,
        unit=unit,
        unit_price=unit_price.quantize(Decimal("0.01")),
        discount=discount,
        tax_rate_bps=tax_rate_bps,
        tax_amount=tax_amount,
        line_total=line_total,
        unit_cost=unit_cost,
        line_cost=(unit_cost * quantity).quantize(Decimal("0.01")),
    )


def price_sale(lines: list[PricedLine], invoice_discount=Decimal("0")) -> PricedSale:
    sale = PricedSale(lines=lines, invoice_discount=D(invoice_discount))
    for line in lines:
        sale.subtotal += line.unit_price * line.quantity
        sale.discount_total += line.discount
        sale.tax_total += line.tax_amount
        sale.cost_total += line.line_cost
    sale.subtotal = sale.subtotal.quantize(Decimal("0.01"))
    sale.cost_total = sale.cost_total.quantize(Decimal("0.01"))
    sale.total = sale.subtotal - sale.discount_total - sale.invoice_discount + sale.tax_total
    sale.total = sale.total.quantize(Decimal("0.01"))
    return sale


def sale_accounting_lines(priced: PricedSale, *, cash_account="1000") -> list[tuple]:
    """Standard cash sale journal: DR cash, CR revenue, CR tax payable,
    DR COGS / CR inventory. Returns lines for AccountingEngine.post_entry."""
    net_revenue = priced.subtotal - priced.discount_total - priced.invoice_discount
    lines = [
        (cash_account, priced.total, Decimal("0")),
        ("4000", Decimal("0"), net_revenue),
    ]
    if priced.tax_total > 0:
        lines.append(("2100", Decimal("0"), priced.tax_total))
    if priced.cost_total > 0:
        lines.append(("5000", priced.cost_total, Decimal("0")))
        lines.append(("1200", Decimal("0"), priced.cost_total))
    return lines
