"""Products screen: add products and search the local catalog."""

from __future__ import annotations

import uuid as uuidlib
from decimal import Decimal

from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
)

from ..i18n import tr
from .common import FormDialog, ListScreen, money_text, qty_text


class ProductsScreen(ListScreen):
    def __init__(self, runtime, language: str):
        super().__init__(runtime, language)
        self._setup_table(
            ["name", "sku", "barcode", "price", "cost", "available", "status"]
        )
        actions = QHBoxLayout()
        add = QPushButton(tr(language, "products") + f" - {tr(language, 'add')}")
        add.clicked.connect(self._open_add_dialog)
        actions.addWidget(add)
        actions.addStretch(1)
        self.layout().addLayout(actions)
        self.reload()

    def _open_add_dialog(self) -> None:
        FormDialog(
            self, self.runtime, self.language, "products",
            {
                "name": "name",
                "name_ar": "name_ar",
                "sku": "sku",
                "barcode": "barcode",
                "cost": "cost",
                "price": "price",
                "tax_percent": "tax_percent",
                "min_stock": "min_stock",
            },
            self._create_product,
        ).show()

    def _create_product(self, values: dict) -> None:
        if not values["name"] or not values["sku"]:
            raise ValueError(
                f"{tr(self.language, 'name')} / {tr(self.language, 'sku')}"
            )
        tax_bps = int(Decimal(values["tax_percent"] or "0") * 100)
        product = {
            "uuid": str(uuidlib.uuid4()),
            "tenant_id": self._tenant_id(),
            "sku": values["sku"],
            "name": values["name"],
            "name_ar": values["name_ar"] or None,
            "cost": values["cost"] or "0",
            "price": values["price"] or "0",
            "tax_rate_bps": tax_bps,
            "min_stock": values["min_stock"] or "0",
            "default_unit": "PIECE",
        }
        with self.runtime.db.transaction():
            self.runtime.products.insert(product)
            if values["barcode"]:
                self.runtime.products.add_barcode(product["uuid"], values["barcode"])
        self.reload()

    def reload(self) -> None:
        tenant = self._tenant_id()
        term = self.search.text().strip()
        if term:
            products = self.runtime.products.search(tenant, term, limit=500)
        else:
            rows = self.runtime.db.query_all(
                "SELECT * FROM products WHERE tenant_id=? ORDER BY name LIMIT 500",
                (tenant,),
            )
            products = [dict(r) for r in rows]

        balances: dict[str, Decimal] = {}
        for row in self.runtime.db.query_all(
            "SELECT product_uuid, quantity, reserved_qty FROM inventory_balances"
            " WHERE tenant_id=?",
            (tenant,),
        ):
            available = Decimal(row["quantity"]) - Decimal(row["reserved_qty"])
            balances[row["product_uuid"]] = (
                balances.get(row["product_uuid"], Decimal("0")) + available
            )

        barcodes: dict[str, str] = {}
        for row in self.runtime.db.query_all(
            "SELECT product_uuid, barcode FROM product_barcodes"
        ):
            barcodes.setdefault(row["product_uuid"], row["barcode"])

        view = []
        for p in products:
            view.append([
                p["name_ar"] or p["name"],
                p["sku"],
                barcodes.get(p["uuid"], "-"),
                money_text(Decimal(p["price"])),
                money_text(Decimal(p["cost"])),
                qty_text(balances.get(p["uuid"], Decimal("0"))),
                p["status"],
            ])
        self._show_rows(view)
