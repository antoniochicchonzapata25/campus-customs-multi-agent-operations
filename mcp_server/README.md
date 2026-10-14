# Campus Customs MCP Server

This server is the **single source of shop facts and shop operations** for the Campus Customs agent team (Boss, Inventory, Accounting, Facilities, Customer Service). Agents don't query the database directly. They call these tools, so every answer comes from real data rather than the model's guesses. The backend uses the same server for anything that changes the database.

- **Framework:** [FastMCP](https://gofastmcp.com) (`server.py`), stdio transport
- **Database:** `data/campus_customs_new.db`, the **working copy**. The path is resolved relative to this folder, so it works wherever the repo is cloned. The original `data/campus_customs.db` is never touched, and the server refuses to start if pointed at it.
- **Test override:** the `CAMPUS_CUSTOMS_DB` environment variable points the server at another file. It is used only by `backend/tests` with a temporary copy.
- **Access:** read tools open the database **read-only** (`mode=ro`, annotated `readOnlyHint: true`). The two write tools open it read-write and are annotated `destructiveHint: true`.
- **Shop date:** "today" is always `desk.date_today`, never the system clock.

## Run

```bash
pip install -r requirements.txt
python mcp_server/server.py
```

Claude Code connects through `.mcp.json`. The agents in `backend/` start the same script over stdio (`backend/agents.py: build_mcp_toolset`).

## Tools

| Tool | Reads / writes | Main ticket | Used by |
|---|---|---|---|
| `get_product_stock_and_price` | reads `inventory`, `pricing` | 103 (also 101) | Inventory, Accounting |
| `get_open_vendor_invoices` | reads `invoices`, `vendors`, `desk` | 101 | Inventory, Accounting |
| `get_lease_rent_status` | reads `leases`, `desk` | 102 | Facilities |
| `get_tickets` | reads `tickets` | all | all agents, backend |
| `get_cash_balance` | reads `cash_accounts`, `desk` | 101, 102, 103 | Accounting, backend |
| `list_vendors` | reads `vendors`, `invoices`, `desk` | 101, 103 | Inventory |
| `prepare_payment_request` | reads `invoices`, `vendors`, `leases`, `inventory`, `pricing`, `cash_accounts`, `desk` | 101, 102, 103 | Accounting |
| `record_approved_payment` | **writes** `payments`, `cash_accounts`, `invoices` / `leases` | 101, 102, 103 | **backend approval route only** |
| `update_ticket_status` | **writes** `tickets.status` | all | **backend only** |

### Tools from Problem 3 (unchanged)

**`get_product_stock_and_price(sku, size=None, qty_needed=None)`**
- Returns stock for every size of a SKU (qty and location), plus unit cost, list price and per-unit margin.
- With `size` and `qty_needed`, it also reports whether the order can be filled from stock, and the shortfall.

**`get_open_vendor_invoices(vendor_id=None)`**
- Lists unpaid (`status = 'open'`) invoices joined with vendor name, specialty and lead days.
- Flags each invoice as overdue relative to the shop date, with days past due. A vendor with an open invoice won't ship.

**`get_lease_rent_status(lease_id)`**
- Returns the lease's space, landlord, monthly rent and next due date.
- Also returns days until due and an overdue flag, relative to the shop date.

### Tools added in Problem 5

**`get_tickets(ticket_id=None, status=None)`**
- Returns one ticket, or all tickets (optionally filtered by status), with every stored field.
- The Boss reads a ticket's `sku`/`size`/`qty`, `lease_id` and `invoice_id` to decide who works on it.

**`get_cash_balance(account="checking")`**
- Returns the current balance and the shop date. Accounting checks it before proposing any payment.
- Cash only goes out, so this balance is the ceiling.

**`list_vendors(specialty_keyword=None)`**
- Returns vendors with lead days, open-invoice count and amount, `can_ship_new_product`, and the earliest arrival if ordered on the shop date.
- There is no SKU-to-vendor table, so the specialty keyword (for example `apparel`) is how Inventory finds who can restock.

**`prepare_payment_request(kind, ref_id, account="checking", sku=None, size=None, qty=None)`**
- Drafts a payment and **does not move money**. Kinds:
  - `invoice`: `ref_id` is the invoice id.
  - `rent`: `ref_id` is the lease id.
  - `purchase_order`: `ref_id` is the vendor id, plus `sku`, `size` and `qty`.
- The amount always comes from the database, never from the agent.
- Returns the payee, amount, balance before and after, `sufficient_funds`, and status `pending_human_approval` or `refused_insufficient_funds`.
- Refuses a closed invoice, unknown ids, and a purchase order from a vendor that still has an open invoice.

**`record_approved_payment(kind, ref_id, approved_amount, approved_by, account="checking", sku=None, size=None, qty=None, for_due_date=None)`**
- **Backend only, called after a human approves.** It recomputes the amount from the database and refuses if:
  - the amount differs from `approved_amount`;
  - `approved_by` is empty or an agent name;
  - cash would go negative;
  - the invoice is already paid;
  - for rent, `for_due_date` isn't the lease's current `next_due` (this prevents paying the same month twice);
  - for a purchase order, the vendor still has an open invoice.
- In one transaction it:
  - inserts a `payments` row (`paid_at` = shop date);
  - lowers `cash_accounts.balance`;
  - marks the invoice `paid`, or moves `leases.next_due` forward one month.
- A purchase order only records the payment. Stock arrives after the vendor's lead time, so `inventory` is not changed.

**`update_ticket_status(ticket_id, status)`**
- **Backend only.** Sets `tickets.status` to `open`, `in_progress`, `awaiting_approval` or `resolved`.
- It never edits the requester's notes.

## How the agents use it

- **One connection per run:** each agent run opens one stdio connection to this server, shared by all five agents.
- **Per-agent filtering:** each agent sees only the read tools its role needs (see `backend/agents.py: AGENT_TOOLS`). No agent can see `record_approved_payment` or `update_ticket_status`. A human must approve a payment in the backend before the backend calls those tools.
- **Errors:** unknown SKUs, sizes, leases, invoices, vendors, tickets or accounts, and invalid arguments, are returned as MCP tool errors with a clear message instead of made-up data.
