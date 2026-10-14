"""REAL MCP tests: each test starts mcp_server/server.py over stdio (the same
transport the agents use) pointed at an isolated database copy, then calls tools."""

import asyncio
import sqlite3

import pytest

from agents import build_mcp_toolset

EXPECTED_TOOLS = {
    "get_product_stock_and_price", "get_open_vendor_invoices", "get_lease_rent_status",
    "get_tickets", "get_cash_balance", "list_vendors", "prepare_payment_request",
    "record_approved_payment", "update_ticket_status",
}


async def _passthrough(ctx, call_tool, name, args):
    return await call_tool(name, args)


def mcp_session(db_path, steps):
    """Run `steps(call)` inside one MCP session; `call` returns result or the error text."""
    async def main():
        ts = build_mcp_toolset(_passthrough, db_path=db_path)
        async with ts:
            async def call(name, **args):
                try:
                    return await ts.direct_call_tool(name, args)
                except Exception as exc:  # tool errors arrive as exceptions
                    return {"__error__": str(exc)}
            async def list_names():
                return {t.name for t in await ts.list_tools()}
            return await steps(call, list_names)
    return asyncio.run(main())


def q(db, sql, *params):
    with sqlite3.connect(db) as con:
        return con.execute(sql, params).fetchall()


def test_all_tools_registered_and_existing_three_unchanged(iso_db):
    async def steps(call, list_names):
        return (
            await list_names(),
            await call("get_product_stock_and_price", sku="CC-HOOD-NAVY", size="M", qty_needed=20),
            await call("get_open_vendor_invoices"),
            await call("get_lease_rent_status", lease_id=1),
        )
    names, stock, invoices, lease = mcp_session(iso_db, steps)
    assert names == EXPECTED_TOOLS
    assert stock["requested_size"] == {"size": "M", "qty_on_hand": 8, "location": "Aisle A", "qty_needed": 20,
                                       "can_fill_from_stock": False, "shortfall": 12}
    assert stock["pricing"] == {"unit_cost": 22, "list_price": 58, "margin_per_unit_at_list": 36}
    assert invoices["invoices"][0]["invoice_id"] == 501 and invoices["invoices"][0]["days_past_due"] == 3
    assert lease["monthly_rent"] == 2400 and lease["days_until_due"] == 2 and lease["is_overdue"] is False


def test_new_read_tools_match_database(iso_db):
    async def steps(call, _):
        return (
            await call("get_tickets"),
            await call("get_tickets", ticket_id=103),
            await call("get_tickets", status="resolved"),
            await call("get_cash_balance"),
            await call("list_vendors"),
            await call("list_vendors", specialty_keyword="apparel"),
        )
    all_t, t103, resolved, cash, vendors, apparel = mcp_session(iso_db, steps)
    assert [t["id"] for t in all_t["tickets"]] == [101, 102, 103]
    assert all(t["status"] == "open" for t in all_t["tickets"])
    assert t103["tickets"][0]["sku"] == "CC-HOOD-NAVY" and t103["tickets"][0]["qty"] == 20
    assert resolved["count"] == 0
    assert cash == {"account": "checking", "balance": 3400, "balance_as_of": "2026-08-31", "shop_date": "2026-08-31"}
    by_id = {v["vendor_id"]: v for v in vendors["vendors"]}
    assert by_id[1]["can_ship_new_product"] is False and by_id[1]["open_invoice_amount"] == 840
    assert by_id[2]["can_ship_new_product"] is True and by_id[2]["earliest_arrival_if_ordered_today"] == "2026-09-03"
    assert [v["vendor_id"] for v in apparel["vendors"]] == [1]


def test_invalid_inputs_and_missing_records(iso_db):
    async def steps(call, _):
        return [
            await call("get_tickets", ticket_id=999),
            await call("get_tickets", status="closed"),
            await call("get_cash_balance", account="savings"),
            await call("get_product_stock_and_price", sku="NOPE"),
            await call("get_product_stock_and_price", sku="CC-TEE-WHITE", size="XXL"),
            await call("get_lease_rent_status", lease_id=42),
            await call("prepare_payment_request", kind="invoice", ref_id=999),
            await call("prepare_payment_request", kind="purchase_order", ref_id=2, sku="CC-MUG-CREST", size="OS", qty=0),
            await call("prepare_payment_request", kind="purchase_order", ref_id=2),
            await call("prepare_payment_request", kind="refund", ref_id=1),
        ]
    results = mcp_session(iso_db, steps)
    assert all("__error__" in r for r in results), results


def test_prepare_payment_is_read_only_and_enforces_vendor_rule(iso_db):
    async def steps(call, _):
        return (
            await call("prepare_payment_request", kind="invoice", ref_id=501),
            await call("prepare_payment_request", kind="rent", ref_id=1),
            await call("prepare_payment_request", kind="purchase_order", ref_id=1, sku="CC-HOOD-NAVY", size="M", qty=12),
            await call("prepare_payment_request", kind="purchase_order", ref_id=2, sku="CC-MUG-CREST", size="OS", qty=10),
        )
    inv, rent, po_blocked, po_ok = mcp_session(iso_db, steps)
    assert inv["status"] == "pending_human_approval" and inv["amount"] == 840 and inv["balance_after"] == 2560
    assert rent["amount"] == 2400 and rent["details"]["for_due_date"] == "2026-09-02"
    assert "open invoice" in po_blocked["__error__"]
    assert po_ok["amount"] == 35.0 and po_ok["details"]["expected_arrival"] == "2026-09-03"
    # Nothing was written.
    assert q(iso_db, "SELECT COUNT(*) FROM payments") == [(0,)]
    assert q(iso_db, "SELECT balance FROM cash_accounts") == [(3400.0,)]
    assert q(iso_db, "SELECT status FROM invoices WHERE id = 501") == [("open",)]


def test_payment_refusals(iso_db):
    async def steps(call, _):
        return [
            await call("record_approved_payment", kind="invoice", ref_id=501, approved_amount=840, approved_by="accounting"),
            await call("record_approved_payment", kind="invoice", ref_id=501, approved_amount=840, approved_by="  "),
            await call("record_approved_payment", kind="invoice", ref_id=501, approved_amount=800, approved_by="Store Manager"),
            await call("record_approved_payment", kind="rent", ref_id=1, approved_amount=2400, approved_by="Store Manager",
                       for_due_date="2026-10-02"),
            await call("record_approved_payment", kind="purchase_order", ref_id=1, approved_amount=264,
                       approved_by="Store Manager", sku="CC-HOOD-NAVY", size="M", qty=12),
        ]
    results = mcp_session(iso_db, steps)
    assert all("__error__" in r for r in results), results
    assert q(iso_db, "SELECT COUNT(*) FROM payments") == [(0,)]
    assert q(iso_db, "SELECT balance FROM cash_accounts") == [(3400.0,)]


def test_payment_exceeding_cash_is_refused(iso_db):
    q(iso_db, "UPDATE cash_accounts SET balance = 500 WHERE name = 'checking'")  # isolated copy only
    async def steps(call, _):
        return (
            await call("prepare_payment_request", kind="invoice", ref_id=501),
            await call("record_approved_payment", kind="invoice", ref_id=501, approved_amount=840, approved_by="Store Manager"),
        )
    prep, rec = mcp_session(iso_db, steps)
    assert prep["status"] == "refused_insufficient_funds" and prep["sufficient_funds"] is False
    assert "Insufficient funds" in rec["__error__"]
    assert q(iso_db, "SELECT balance FROM cash_accounts") == [(500.0,)]
    assert q(iso_db, "SELECT COUNT(*) FROM payments") == [(0,)]
    assert q(iso_db, "SELECT status FROM invoices WHERE id = 501") == [("open",)]


def test_approved_payments_update_all_tables_consistently(iso_db):
    async def steps(call, _):
        return (
            await call("record_approved_payment", kind="invoice", ref_id=501, approved_amount=840, approved_by="Test Approver"),
            await call("record_approved_payment", kind="invoice", ref_id=501, approved_amount=840, approved_by="Test Approver"),
            await call("record_approved_payment", kind="rent", ref_id=1, approved_amount=2400, approved_by="Test Approver",
                       for_due_date="2026-09-02"),
            await call("record_approved_payment", kind="rent", ref_id=1, approved_amount=2400, approved_by="Test Approver",
                       for_due_date="2026-09-02"),
            await call("list_vendors", specialty_keyword="apparel"),
            await call("prepare_payment_request", kind="purchase_order", ref_id=1, sku="CC-HOOD-NAVY", size="M", qty=12),
        )
    inv, inv_again, rent, rent_again, vendors, po = mcp_session(iso_db, steps)
    assert inv["status"] == "paid" and inv["balance_after"] == 2560
    assert "not open" in inv_again["__error__"]
    assert rent["balance_after"] == 160 and rent["details"]["next_due_after_payment"] == "2026-10-02"
    assert "__error__" in rent_again  # same month cannot be paid twice
    assert vendors["vendors"][0]["can_ship_new_product"] is True  # invoice paid, vendor unblocked
    assert po["amount"] == 264 and po["sufficient_funds"] is False  # 12 x 22 > 160 left
    assert q(iso_db, "SELECT kind, ref_id, amount, account, paid_at, approved_by FROM payments ORDER BY id") == [
        ("invoice", 501, 840.0, "checking", "2026-08-31", "Test Approver"),
        ("rent", 1, 2400.0, "checking", "2026-08-31", "Test Approver"),
    ]
    assert q(iso_db, "SELECT balance FROM cash_accounts") == [(160.0,)]
    assert q(iso_db, "SELECT status FROM invoices WHERE id = 501") == [("paid",)]
    assert q(iso_db, "SELECT next_due FROM leases WHERE id = 1") == [("2026-10-02",)]


def test_approved_purchase_order_moves_cash_but_not_inventory(iso_db):
    """An approved PO is a payment, not a delivery: stock only changes when goods arrive."""
    inventory_before = q(iso_db, "SELECT sku, size, qty, location FROM inventory ORDER BY sku, size")
    async def steps(call, _):
        return (
            await call("record_approved_payment", kind="invoice", ref_id=501, approved_amount=840, approved_by="Test Approver"),
            await call("prepare_payment_request", kind="purchase_order", ref_id=1, sku="CC-HOOD-NAVY", size="M", qty=12),
            await call("record_approved_payment", kind="purchase_order", ref_id=1, approved_amount=264,
                       approved_by="Test Approver", sku="CC-HOOD-NAVY", size="M", qty=12),
            await call("get_product_stock_and_price", sku="CC-HOOD-NAVY", size="M", qty_needed=20),
        )
    _, prep, po, stock = mcp_session(iso_db, steps)
    assert prep["status"] == "pending_human_approval" and prep["amount"] == 264 and prep["balance_after"] == 2296
    assert prep["details"]["lead_days"] == 5 and prep["details"]["expected_arrival"] == "2026-09-05"
    assert po["status"] == "paid" and po["amount"] == 264 and po["balance_after"] == 2296
    assert po["details"]["expected_arrival"] == "2026-09-05"
    # Cash and the payment log move together...
    assert q(iso_db, "SELECT kind, ref_id, amount, paid_at FROM payments ORDER BY id")[-1] == ("purchase_order", 1, 264.0, "2026-08-31")
    assert q(iso_db, "SELECT balance FROM cash_accounts") == [(2296.0,)]
    # ...but available stock does not: M is still 8 and still 12 short.
    assert q(iso_db, "SELECT sku, size, qty, location FROM inventory ORDER BY sku, size") == inventory_before
    assert stock["requested_size"]["qty_on_hand"] == 8 and stock["requested_size"]["shortfall"] == 12


def test_update_ticket_status(iso_db):
    async def steps(call, _):
        return (
            await call("update_ticket_status", ticket_id=102, status="in_progress"),
            await call("update_ticket_status", ticket_id=999, status="resolved"),
            await call("update_ticket_status", ticket_id=101, status="done"),
        )
    ok, missing, bad = mcp_session(iso_db, steps)
    assert ok == {"ticket_id": 102, "previous_status": "open", "status": "in_progress"}
    assert "__error__" in missing and "__error__" in bad
    assert q(iso_db, "SELECT notes FROM tickets WHERE id = 102") == [("Email: shop rent due in 2 days.",)]


def test_server_refuses_original_database():
    from conftest import ORIGINAL_DB
    with pytest.raises(Exception):
        mcp_session(ORIGINAL_DB, lambda call, _: call("get_cash_balance"))
