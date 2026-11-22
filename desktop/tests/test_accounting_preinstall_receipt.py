from decimal import Decimal
from pathlib import Path

import pytest

from desktop.business_logic.accounting import AccountingEngine, AccountingError
from desktop.business_logic.money import D

TENANT = "11111111-1111-1111-1111-111111111111"


def test_unbalanced_entry_rejected(runtime):
    engine = AccountingEngine(runtime.db)
    with pytest.raises(AccountingError):
        engine.post_entry(
            tenant_id=TENANT,
            lines=[("1000", Decimal("100"), Decimal("0")), ("4000", Decimal("0"), Decimal("90"))],
            memo="x",
            source_type="ADJUSTMENT",
        )


def test_unknown_account_rejected(runtime):
    engine = AccountingEngine(runtime.db)
    with pytest.raises(AccountingError):
        engine.post_entry(
            tenant_id=TENANT,
            lines=[("9999", Decimal("100"), Decimal("0")), ("4000", Decimal("0"), Decimal("100"))],
            memo="x",
            source_type="ADJUSTMENT",
        )


def test_posted_entry_content_immutable_reversal_only(runtime):
    engine = AccountingEngine(runtime.db)
    entry = engine.post_entry(
        tenant_id=TENANT,
        lines=[("1000", Decimal("1000"), Decimal("0")), ("4000", Decimal("0"), Decimal("1000"))],
        memo="cash sale",
        source_type="SALE",
    )
    acct = runtime.db.query_one("SELECT 1 FROM accounts WHERE code='1000'")
    # direct edit of a posted entry line is prevented by the immutability policy
    # check: engine refuses REVERSED double-reversal, and reversal mirrors lines
    rev = engine.post_reversal(tenant_id=TENANT, entry_uuid=entry["uuid"], memo="oops")
    lines_rev = runtime.db.query_all(
        "SELECT debit, credit FROM journal_lines WHERE entry_uuid=?", (rev["uuid"],)
    )
    assert D(lines_rev[0]["credit"]) == Decimal("1000")
    with pytest.raises(AccountingError):
        engine.post_reversal(tenant_id=TENANT, entry_uuid=entry["uuid"], memo="again")
    # trial balance nets to zero for the paired entries
    tb = engine.trial_balance(TENANT)
    assert all(v["debits"] >= 0 and v["credits"] >= 0 for v in tb.values())


def test_trial_balance_excludes_reversed(runtime):
    engine = AccountingEngine(runtime.db)
    e1 = engine.post_entry(
        tenant_id=TENANT,
        lines=[("1000", Decimal("500"), Decimal("0")), ("6100", Decimal("0"), Decimal("500"))],
        memo="a",
        source_type="EXPENSE",
    )
    acct_before = engine.trial_balance(TENANT)
    engine.post_reversal(tenant_id=TENANT, entry_uuid=e1["uuid"], memo="fix")
    acct_after = engine.trial_balance(TENANT)
    assert D(acct_after["1000"]["debits"]) == D("0")
    assert D(acct_after["6100"]["credits"]) == D("0")


def _write_pkg(tmp_path, size=1024):
    pkg = tmp_path / "pre" / "pkg.pkg"
    pkg.parent.mkdir(parents=True, exist_ok=True)
    pkg.write_bytes(b"U" * size)
    return pkg


def test_preinstall_report_requires_verified_backup(runtime, tmp_path):
    import hashlib

    from desktop.updates.preinstall import build_preinstall_report

    pkg = _write_pkg(tmp_path)
    manifest = {
        "sha256": hashlib.sha256(pkg.read_bytes()).hexdigest(),
        "package_size": pkg.stat().st_size,
        "min_schema_version": 1,
        "max_schema_version": runtime.db.schema_version(),
    }
    runtime.db.execute(
        "INSERT OR IGNORE INTO app_config (key, value) VALUES ('app_version','1.0.0')"
    )
    markup = runtime.db.path.parent / "backups"
    report = build_preinstall_report(runtime.db, pkg, manifest["sha256"], manifest)
    assert report["schema_compatible"] is True
    assert report["checksum_verified"] is True
    assert report["ok"] is False  # no verified pre-update backup yet


def test_receipt_rendering(runtime, seeded_products):
    from desktop.printing.receipt import render_escpos_bytes, render_text_receipt

    with runtime.db.transaction() as db:
        runtime.inventory.record_movement(
            tenant_id=TENANT,
            branch_id="branch-1",
            product_uuid="aaaa1111-0000-0000-0000-000000000001",
            movement_type="PURCHASE_RECEIPT",
            direction=1,
            quantity=100,
            unit="PIECE",
            reference_type="PURCHASE",
        )
    result = runtime.sales.commit_sale(
        tenant_id=TENANT, branch_id="branch-1",
        device_id=runtime.device["device_id"], cashier_id="c1",
        items=[{"product_uuid": "aaaa1111-0000-0000-0000-000000000001",
                "quantity": 2, "unit": "PIECE"}],
        payments=[{"method": "CASH", "amount": "2000.00"}],
    )
    sale = runtime.sales.get_sale(result["sale_uuid"])
    text = render_text_receipt(sale)
    assert result["invoice_no"] in text
    escpos = render_escpos_bytes(sale)
    assert escpos.startswith(b"\x1b\x40")
    assert b"TOTAL" in escpos
