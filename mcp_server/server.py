"""Campus Customs MCP server.

Exposes shop-data tools over the working database data/campus_customs_new.db.
Every agent gets its shop facts from these tools; nothing here is hardcoded.

Read tools open the database read-only. The two write tools
(`record_approved_payment`, `update_ticket_status`) are meant for the backend's
human-approval routes only; the agent team is never given access to them.
"""

import calendar
import os
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

# Project-relative paths so the server works wherever the repo is cloned.
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ORIGINAL_DB_PATH = DATA_DIR / "campus_customs.db"
# CAMPUS_CUSTOMS_DB lets tests point the server at an isolated copy. It may never
# point at the original database, which stays untouched for resets.
DB_PATH = Path(os.environ.get("CAMPUS_CUSTOMS_DB") or DATA_DIR / "campus_customs_new.db").resolve()
if DB_PATH == ORIGINAL_DB_PATH.resolve():
    raise RuntimeError("Refusing to serve the original database; use the working copy.")

READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}
WRITE = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False}

PAYMENT_KINDS = ("invoice", "rent", "purchase_order")
TICKET_STATUSES = ("open", "in_progress", "awaiting_approval", "resolved")
# Approvals must come from a person, never from one of the agents.
AGENT_NAMES = {"boss", "inventory", "accounting", "facilities", "customer_service", "customer service", "agent"}

mcp = FastMCP("campus-customs")


def connect_read_only() -> sqlite3.Connection:
    """Open the working database in read-only mode (no writes possible)."""
    if not DB_PATH.exists():
        raise ToolError(f"Working database not found at {DB_PATH}")
    con = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def connect_read_write() -> sqlite3.Connection:
    """Open the working database for a write tool (never creates a new file)."""
    if not DB_PATH.exists():
        raise ToolError(f"Working database not found at {DB_PATH}")
    con = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=rw", uri=True)
    con.row_factory = sqlite3.Row
    return con


def shop_today(con: sqlite3.Connection) -> date:
    """The shop's 'today' comes from desk.date_today, not the system clock."""
    row = con.execute("SELECT date_today FROM desk LIMIT 1").fetchone()
    if row is None:
        raise ToolError("desk table has no date_today row")
    return date.fromisoformat(row["date_today"])


@mcp.tool(annotations=READ_ONLY)
def get_product_stock_and_price(
    sku: str, size: str | None = None, qty_needed: int | None = None
) -> dict:
    """Look up stock on hand (by size) and pricing for one SKU.

    Returns every size row for the SKU from `inventory` plus `unit_cost`,
    `list_price`, and per-unit margin from `pricing`. If `size` is given, the
    matching size row is returned as `requested_size`; if `qty_needed` is also
    given, the result reports whether stock covers it and the shortfall.
    Use this to check whether an order can be filled from stock and what
    margin is available before agreeing to a discount.
    """
    with closing(connect_read_only()) as con:
        rows = con.execute(
            "SELECT sku, name, size, qty, location FROM inventory WHERE sku = ? ORDER BY rowid",
            (sku,),
        ).fetchall()
        if not rows:
            raise ToolError(f"No inventory found for SKU '{sku}'")
        price = con.execute(
            "SELECT unit_cost, list_price FROM pricing WHERE sku = ?", (sku,)
        ).fetchone()

    result = {
        "sku": sku,
        "name": rows[0]["name"],
        "sizes": [
            {"size": r["size"], "qty": r["qty"], "location": r["location"]} for r in rows
        ],
        "total_qty_all_sizes": sum(r["qty"] for r in rows),
        "pricing": None,
    }
    if price is not None:
        result["pricing"] = {
            "unit_cost": price["unit_cost"],
            "list_price": price["list_price"],
            "margin_per_unit_at_list": round(price["list_price"] - price["unit_cost"], 2),
        }

    if size is not None:
        match = next((r for r in rows if r["size"] == size), None)
        if match is None:
            raise ToolError(
                f"SKU '{sku}' has no size '{size}'. Available: {[r['size'] for r in rows]}"
            )
        requested = {"size": size, "qty_on_hand": match["qty"], "location": match["location"]}
        if qty_needed is not None:
            requested["qty_needed"] = qty_needed
            requested["can_fill_from_stock"] = match["qty"] >= qty_needed
            requested["shortfall"] = max(qty_needed - match["qty"], 0)
        result["requested_size"] = requested

    return result


@mcp.tool(annotations=READ_ONLY)
def get_open_vendor_invoices(vendor_id: int | None = None) -> dict:
    """List unpaid (status 'open') invoices with vendor details and overdue status.

    Joins `invoices` with `vendors` (name, specialty, lead_days) and compares
    each due_date to the shop date in `desk.date_today`. Optionally filter to
    one vendor. A vendor with an open invoice will not ship new product, so
    use this before planning any restock or paying a vendor bill.
    """
    with closing(connect_read_only()) as con:
        today = shop_today(con)
        query = """
            SELECT i.id, i.vendor_id, i.amount, i.due_date, i.status, i.description,
                   v.name AS vendor_name, v.specialty, v.lead_days
            FROM invoices i JOIN vendors v ON v.id = i.vendor_id
            WHERE i.status = 'open'
        """
        params: tuple = ()
        if vendor_id is not None:
            query += " AND i.vendor_id = ?"
            params = (vendor_id,)
        rows = con.execute(query + " ORDER BY i.due_date", params).fetchall()

    invoices = []
    for r in rows:
        days_past_due = (today - date.fromisoformat(r["due_date"])).days
        invoices.append(
            {
                "invoice_id": r["id"],
                "vendor_id": r["vendor_id"],
                "vendor_name": r["vendor_name"],
                "vendor_specialty": r["specialty"],
                "vendor_lead_days": r["lead_days"],
                "amount": r["amount"],
                "due_date": r["due_date"],
                "status": r["status"],
                "description": r["description"],
                "is_overdue": days_past_due > 0,
                "days_past_due": max(days_past_due, 0),
                "vendor_blocked_from_shipping": True,
            }
        )

    return {
        "shop_date": today.isoformat(),
        "open_invoice_count": len(invoices),
        "total_open_amount": round(sum(i["amount"] for i in invoices), 2),
        "invoices": invoices,
    }


@mcp.tool(annotations=READ_ONLY)
def get_lease_rent_status(lease_id: int) -> dict:
    """Get a lease's rent amount, landlord, and next due date relative to shop date.

    Reads `leases` and compares `next_due` to `desk.date_today` to report
    days until rent is due (or days overdue). Use this to verify a rent
    notice before preparing a rent payment for human approval.
    """
    with closing(connect_read_only()) as con:
        today = shop_today(con)
        row = con.execute(
            "SELECT id, space_name, landlord, monthly_rent, next_due, notes FROM leases WHERE id = ?",
            (lease_id,),
        ).fetchone()
    if row is None:
        raise ToolError(f"No lease found with id {lease_id}")

    days_until_due = (date.fromisoformat(row["next_due"]) - today).days
    return {
        "lease_id": row["id"],
        "space_name": row["space_name"],
        "landlord": row["landlord"],
        "monthly_rent": row["monthly_rent"],
        "next_due": row["next_due"],
        "notes": row["notes"],
        "shop_date": today.isoformat(),
        "days_until_due": days_until_due,
        "is_overdue": days_until_due < 0,
    }


@mcp.tool(annotations=READ_ONLY)
def get_tickets(ticket_id: int | None = None, status: str | None = None) -> dict:
    """Read desk tickets: one ticket by id, or all tickets (optionally by status).

    Reads `tickets`. Returns every stored field (type, requester, subject,
    sku/size/qty, lease_id, invoice_id, status, notes, created_at) so the Boss
    can see what is being asked and which other tables hold the context.
    """
    if status is not None and status not in TICKET_STATUSES:
        raise ToolError(f"Unknown status '{status}'. Allowed: {list(TICKET_STATUSES)}")
    query = "SELECT * FROM tickets"
    clauses, params = [], []
    if ticket_id is not None:
        clauses.append("id = ?")
        params.append(ticket_id)
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    with closing(connect_read_only()) as con:
        rows = con.execute(query + " ORDER BY id", params).fetchall()
    if ticket_id is not None and not rows:
        raise ToolError(f"No ticket found with id {ticket_id}")
    return {"count": len(rows), "tickets": [dict(r) for r in rows]}


@mcp.tool(annotations=READ_ONLY)
def get_cash_balance(account: str = "checking") -> dict:
    """Get the current balance of a cash account and the shop date.

    Reads `cash_accounts` and `desk`. Accounting must check this before
    proposing any payment; cash only goes out in this shop, so the balance is
    the hard ceiling on what can be paid.
    """
    with closing(connect_read_only()) as con:
        today = shop_today(con)
        row = con.execute(
            "SELECT name, balance, date FROM cash_accounts WHERE name = ?", (account,)
        ).fetchone()
        names = [r["name"] for r in con.execute("SELECT name FROM cash_accounts")]
    if row is None:
        raise ToolError(f"No cash account named '{account}'. Available: {names}")
    return {
        "account": row["name"],
        "balance": row["balance"],
        "balance_as_of": row["date"],
        "shop_date": today.isoformat(),
    }


@mcp.tool(annotations=READ_ONLY)
def list_vendors(specialty_keyword: str | None = None) -> dict:
    """List vendors with lead time, open-invoice status, and earliest arrival date.

    Reads `vendors`, `invoices`, and `desk`. Optionally filter by a keyword in
    the vendor's specialty (e.g. "apparel"). There is no SKU-to-vendor table,
    so the specialty is the only evidence of who can restock a product. A
    vendor with any open invoice is reported as unable to ship new product.
    """
    with closing(connect_read_only()) as con:
        today = shop_today(con)
        query = """
            SELECT v.id, v.name, v.specialty, v.lead_days,
                   COUNT(i.id) AS open_invoices, COALESCE(SUM(i.amount), 0) AS open_amount
            FROM vendors v LEFT JOIN invoices i ON i.vendor_id = v.id AND i.status = 'open'
        """
        params: tuple = ()
        if specialty_keyword:
            query += " WHERE LOWER(v.specialty) LIKE ?"
            params = (f"%{specialty_keyword.lower()}%",)
        rows = con.execute(query + " GROUP BY v.id ORDER BY v.id", params).fetchall()

    vendors = []
    for r in rows:
        arrival = date.fromordinal(today.toordinal() + r["lead_days"])
        vendors.append(
            {
                "vendor_id": r["id"],
                "name": r["name"],
                "specialty": r["specialty"],
                "lead_days": r["lead_days"],
                "open_invoice_count": r["open_invoices"],
                "open_invoice_amount": round(r["open_amount"], 2),
                "can_ship_new_product": r["open_invoices"] == 0,
                "earliest_arrival_if_ordered_today": arrival.isoformat(),
            }
        )
    return {"shop_date": today.isoformat(), "count": len(vendors), "vendors": vendors}


def add_one_month(d: date) -> date:
    """Next monthly due date, keeping the day where the month allows it."""
    year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def price_payment(
    con: sqlite3.Connection,
    kind: str,
    ref_id: int,
    account: str,
    sku: str | None,
    size: str | None,
    qty: int | None,
) -> dict:
    """Work out what a payment is for and how much it costs, from the database only.

    Shared by prepare_payment_request and record_approved_payment so the
    amount a human approves is always recomputed from stored data, never taken
    from an agent. Raises ToolError for anything that may not be paid.
    """
    if kind not in PAYMENT_KINDS:
        raise ToolError(f"Unknown payment kind '{kind}'. Allowed: {list(PAYMENT_KINDS)}")
    today = shop_today(con)
    cash = con.execute(
        "SELECT balance FROM cash_accounts WHERE name = ?", (account,)
    ).fetchone()
    if cash is None:
        raise ToolError(f"No cash account named '{account}'")

    if kind == "invoice":
        row = con.execute(
            """SELECT i.id, i.amount, i.status, i.due_date, i.description, v.name AS vendor
               FROM invoices i JOIN vendors v ON v.id = i.vendor_id WHERE i.id = ?""",
            (ref_id,),
        ).fetchone()
        if row is None:
            raise ToolError(f"No invoice found with id {ref_id}")
        if row["status"] != "open":
            raise ToolError(f"Invoice {ref_id} is '{row['status']}', not open; nothing to pay")
        amount = row["amount"]
        payee = row["vendor"]
        details = {"invoice_id": row["id"], "due_date": row["due_date"], "description": row["description"]}
    elif kind == "rent":
        row = con.execute(
            "SELECT id, landlord, space_name, monthly_rent, next_due FROM leases WHERE id = ?",
            (ref_id,),
        ).fetchone()
        if row is None:
            raise ToolError(f"No lease found with id {ref_id}")
        amount = row["monthly_rent"]
        payee = row["landlord"]
        details = {
            "lease_id": row["id"],
            "space_name": row["space_name"],
            "for_due_date": row["next_due"],
            "next_due_after_payment": add_one_month(date.fromisoformat(row["next_due"])).isoformat(),
        }
    else:  # purchase_order: ref_id is the vendor
        if not sku or not size or qty is None:
            raise ToolError("A purchase_order needs sku, size, and qty")
        if qty <= 0:
            raise ToolError("qty must be a positive whole number")
        vendor = con.execute("SELECT * FROM vendors WHERE id = ?", (ref_id,)).fetchone()
        if vendor is None:
            raise ToolError(f"No vendor found with id {ref_id}")
        if con.execute(
            "SELECT 1 FROM inventory WHERE sku = ? AND size = ?", (sku, size)
        ).fetchone() is None:
            raise ToolError(f"No inventory row for SKU '{sku}' size '{size}'")
        price = con.execute("SELECT unit_cost FROM pricing WHERE sku = ?", (sku,)).fetchone()
        if price is None:
            raise ToolError(f"No pricing found for SKU '{sku}'; cannot cost the order")
        open_inv = con.execute(
            "SELECT id, amount FROM invoices WHERE vendor_id = ? AND status = 'open'", (ref_id,)
        ).fetchall()
        if open_inv:
            raise ToolError(
                f"Vendor {ref_id} ({vendor['name']}) has open invoice(s) "
                f"{[r['id'] for r in open_inv]} and will not ship new product until they are paid"
            )
        amount = round(price["unit_cost"] * qty, 2)
        payee = vendor["name"]
        arrival = date.fromordinal(today.toordinal() + vendor["lead_days"])
        details = {
            "vendor_id": vendor["id"],
            "sku": sku,
            "size": size,
            "qty": qty,
            "unit_cost": price["unit_cost"],
            "lead_days": vendor["lead_days"],
            "expected_arrival": arrival.isoformat(),
        }

    balance = cash["balance"]
    return {
        "kind": kind,
        "ref_id": ref_id,
        "payee": payee,
        "amount": amount,
        "account": account,
        "balance_before": balance,
        "balance_after": round(balance - amount, 2),
        "sufficient_funds": balance >= amount,
        "shop_date": today.isoformat(),
        "details": details,
    }


@mcp.tool(annotations=READ_ONLY)
def prepare_payment_request(
    kind: Literal["invoice", "rent", "purchase_order"],
    ref_id: int,
    account: str = "checking",
    sku: str | None = None,
    size: str | None = None,
    qty: int | None = None,
) -> dict:
    """Draft a payment for human approval. Does NOT move any money.

    kind='invoice': ref_id is an invoice id (must be open).
    kind='rent': ref_id is a lease id; pays one month's rent for leases.next_due.
    kind='purchase_order': ref_id is a vendor id; also pass sku, size, qty.
      Refused if the vendor has an open invoice (it will not ship).
    Reads `invoices`, `vendors`, `leases`, `inventory`, `pricing`,
    `cash_accounts`, and `desk`. The amount always comes from the database.
    Returns the payee, amount, balance before/after, and whether cash covers
    it. The result is a proposal with status 'pending_human_approval'.
    """
    with closing(connect_read_only()) as con:
        request = price_payment(con, kind, ref_id, account, sku, size, qty)
    request["status"] = "pending_human_approval" if request["sufficient_funds"] else "refused_insufficient_funds"
    request["requires_human_approval"] = True
    return request


@mcp.tool(annotations=WRITE)
def record_approved_payment(
    kind: Literal["invoice", "rent", "purchase_order"],
    ref_id: int,
    approved_amount: float,
    approved_by: str,
    account: str = "checking",
    sku: str | None = None,
    size: str | None = None,
    qty: int | None = None,
    for_due_date: str | None = None,
) -> dict:
    """BACKEND ONLY: execute a payment a human has already approved.

    Never exposed to the agents. Recomputes the amount from the database and
    refuses unless it equals `approved_amount`, `approved_by` names a person,
    and cash covers it (no negative balances). In one transaction it inserts
    into `payments`, lowers `cash_accounts.balance`, and updates the paid item:
    `invoices.status` -> 'paid', or `leases.next_due` advances one month for
    rent (pass `for_due_date` = the due date being paid). Purchase orders only
    record the payment; stock arrives after the vendor's lead time.
    """
    approver = (approved_by or "").strip()
    if not approver or approver.lower() in AGENT_NAMES:
        raise ToolError("approved_by must name the human who approved this payment")

    with closing(connect_read_write()) as con:
        try:
            con.execute("BEGIN IMMEDIATE")
            req = price_payment(con, kind, ref_id, account, sku, size, qty)
            if abs(req["amount"] - approved_amount) > 0.005:
                raise ToolError(
                    f"Approved amount {approved_amount} does not match the amount due {req['amount']}; "
                    "re-prepare the request and get approval again"
                )
            if kind == "rent":
                due = req["details"]["for_due_date"]
                if for_due_date != due:
                    raise ToolError(
                        f"Rent for lease {ref_id} is currently due {due}; for_due_date must match "
                        "(this also prevents paying the same month twice)"
                    )
            if not req["sufficient_funds"]:
                raise ToolError(
                    f"Insufficient funds: {account} has {req['balance_before']}, payment needs "
                    f"{req['amount']}. Refused so the balance cannot go negative."
                )

            cur = con.execute(
                "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) VALUES (?, ?, ?, ?, ?, ?)",
                (kind, ref_id, req["amount"], account, req["shop_date"], approver),
            )
            con.execute(
                "UPDATE cash_accounts SET balance = ?, date = ? WHERE name = ?",
                (req["balance_after"], req["shop_date"], account),
            )
            if kind == "invoice":
                con.execute("UPDATE invoices SET status = 'paid' WHERE id = ?", (ref_id,))
            elif kind == "rent":
                con.execute(
                    "UPDATE leases SET next_due = ? WHERE id = ?",
                    (req["details"]["next_due_after_payment"], ref_id),
                )
            con.commit()
        except BaseException:
            con.rollback()
            raise

    return {
        "payment_id": cur.lastrowid,
        "status": "paid",
        "kind": kind,
        "ref_id": ref_id,
        "payee": req["payee"],
        "amount": req["amount"],
        "account": account,
        "approved_by": approver,
        "paid_at": req["shop_date"],
        "balance_after": req["balance_after"],
        "details": req["details"],
    }


@mcp.tool(annotations=WRITE)
def update_ticket_status(
    ticket_id: int,
    status: Literal["open", "in_progress", "awaiting_approval", "resolved"],
) -> dict:
    """BACKEND ONLY: change a ticket's status in `tickets`.

    Never exposed to the agents; the backend sets status after a run and after
    any required human approvals. Only `tickets.status` is written; the
    requester's original notes are left untouched.
    """
    if status not in TICKET_STATUSES:
        raise ToolError(f"Unknown status '{status}'. Allowed: {list(TICKET_STATUSES)}")
    with closing(connect_read_write()) as con:
        row = con.execute("SELECT status FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row is None:
            raise ToolError(f"No ticket found with id {ticket_id}")
        con.execute("UPDATE tickets SET status = ? WHERE id = ?", (status, ticket_id))
        con.commit()
    return {"ticket_id": ticket_id, "previous_status": row["status"], "status": status}


if __name__ == "__main__":
    mcp.run()
