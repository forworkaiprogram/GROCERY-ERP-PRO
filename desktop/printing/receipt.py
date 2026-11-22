"""Receipt rendering: plain-text layout for 58/80mm thermal printers, and an
ESC/POS byte stream builder for direct serial/USB printing. Qt printing is
overkill for receipts; this is pure Python and unit-testable."""

from __future__ import annotations

import json


class ReceiptError(ValueError):
    pass


def render_text_receipt(sale: dict, *, width: int = 42, currency: str = "YER") -> str:
    """sale: result of SaleEngine.get_sale."""
    lines: list[str] = []
    center = lambda s: s.center(width)  # noqa: E731
    lines.append(center("GROCERY ERP PRO"))
    lines.append(center(f"Invoice {sale['invoice_no']}"))
    lines.append(center(f"{sale['created_at']}  cash: {sale['cashier_id']}"))
    lines.append("-" * width)
    for item in sale["items"]:
        name = (item.get("product_uuid", "")[:18]).ljust(18)
        qty_txt = item["quantity"].rjust(6)
        amount = item["line_total"].rjust(width - 6 - 18 - 1)
        lines.append(f"{name}{qty_txt} {amount}")
    lines.append("-" * width)
    lines.append(f"{'Subtotal':<30}{sale['subtotal'].rjust(width - 30)}")
    lines.append(f"{'Discount':<30}{sale['discount_total'].rjust(width - 30)}")
    lines.append(f"{'Tax':<30}{sale['tax_total'].rjust(width - 30)}")
    lines.append(f"{'TOTAL':<30}{sale['total'].rjust(width - 30)}")
    for p in sale["payments"]:
        lines.append(f"{p['method']:<30}{p['amount'].rjust(width - 30)}")
    lines.append("-" * width)
    snapshot = json.loads(sale["priced_snapshot"]) if "priced_snapshot" in sale else {}
    if snapshot:
        lines.append(f"cost: {snapshot.get('cost_total', '-')}  (internal)")
    lines.append(center("Thank you — شكراً لزيارتكم"))
    return "\n".join(lines)


def render_escpos_bytes(sale: dict, *, currency: str = "YER") -> bytes:
    """ESC/POS: init, centered header, text, cut."""
    text = render_text_receipt(sale, currency=currency)
    esc_init = b"\x1b\x40"
    esc_center_off = b"\x1b\x61\x00"
    cut = b"\x1d\x56\x42\x00"
    body = text.encode("utf-8", errors="replace")
    return esc_init + esc_center_off + body + b"\n\n\n" + cut
