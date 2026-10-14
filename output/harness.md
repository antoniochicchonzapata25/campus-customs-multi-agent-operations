# Campus Customs Multi-Agent Operations: Harness

This is the central technical reference for the Campus Customs agent team. It starts with the database (Problem 2), and later problems will add sections for MCP tools and agents.

---

## 1. Database files

| File | Role |
|---|---|
| `data/campus_customs.db` | **Original**: read-only reference. Never modified, so we can reset from it before a full ticket run. |
| `data/campus_customs_new.db` | **Working copy**: the MCP server and backend read and write this file. |

- **Engine:** SQLite. The database has 9 tables, with no views or triggers.
- **Shop "today":** `desk.date_today` = **2026-08-31**. All overdue and due-soon checks use this date, not the system clock.

---

## 2. Tables

Types come from the SQLite schema. "PK" means primary key and "FK" means a declared foreign key. Row counts are from the original database.

### `desk` (1 row)
| Field | Type | Notes |
|---|---|---|
| `date_today` | TEXT, not null | Shop's current date (`2026-08-31`) |
| `notes` | TEXT | Currently NULL |

**Why it matters:** It's the shop's clock. Every agent needs `date_today` to decide whether an invoice is overdue or rent is coming due.

### `tickets` (3 rows)
| Field | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | 101, 102, 103 |
| `type` | TEXT, not null | `customer_order`, `rent_notice`, `price_override` |
| `requester` | TEXT, not null | Who raised the ticket |
| `subject` | TEXT, not null | Short title |
| `sku` | TEXT | Links to `inventory.sku` / `pricing.sku` (no declared FK) |
| `size` | TEXT | Links to `inventory.size` together with `sku` |
| `qty` | INTEGER | Requested quantity |
| `lease_id` | INTEGER | FK → `leases.id` |
| `invoice_id` | INTEGER | FK → `invoices.id` |
| `status` | TEXT, not null | All three are `open` |
| `notes` | TEXT | Free-text request details |
| `created_at` | TEXT, not null | ISO timestamp with `-04:00` offset |

**Why it matters:** It's the work queue. The Boss reads each ticket and routes it. The `sku`/`size`, `lease_id`, and `invoice_id` fields tell agents which other tables hold the context.

### `inventory` (10 rows)
| Field | Type | Notes |
|---|---|---|
| `sku` | TEXT, PK (part 1) | Product code |
| `name` | TEXT, not null | Product name |
| `size` | TEXT, PK (part 2) | `S`/`M`/`L`/`XL`, or `OS` for one-size |
| `qty` | INTEGER, not null | Units on hand |
| `location` | TEXT, not null | Aisle |

Current stock: `CC-HOOD-NAVY` (Basic Hoodie Big Yale) S 4, M 8, L 14, XL 6 · `CC-TEE-WHITE` (Classic Bulldog Tee) **S 0**, M 5, L 3, XL 2 · `CC-HAT-BLUE` (Yale Cap) OS 40 · `CC-MUG-CREST` (Crest Mug) **OS 0**.

**Why it matters:** The Inventory agent checks stock by SKU **and** size here to fill orders and spot shortfalls.

### `pricing` (4 rows)
| Field | Type | Notes |
|---|---|---|
| `sku` | TEXT PK | One row per SKU (prices don't vary by size) |
| `unit_cost` | REAL, not null | What the shop pays |
| `list_price` | REAL, not null | What the customer pays |

Values: HOOD 22.00 / 58.00 · TEE 8.00 / 28.00 · HAT 6.00 / 22.00 · MUG 3.50 / 14.00 (cost / list).

**Why it matters:** Accounting uses it to check margins, for example whether a bulk discount still leaves profit, and to cost purchase orders.

### `vendors` (3 rows)
| Field | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `name` | TEXT, not null | |
| `specialty` | TEXT, not null | What the vendor supplies |
| `lead_days` | INTEGER, not null | Days from order to delivery |

Values: 1 Bulldog Print Co (apparel reprint, 5 days) · 2 Elm City Gifts (mugs and small goods, 3 days) · 3 QuickShip CT (local courier, 1 day).

**Why it matters:** Inventory uses it to pick who can restock and to estimate arrival from `lead_days`. No table links SKUs to vendors, so the match has to come from `specialty`.

### `invoices` (1 row)
| Field | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `vendor_id` | INTEGER, not null | FK → `vendors.id` |
| `amount` | REAL, not null | |
| `due_date` | TEXT, not null | |
| `status` | TEXT, not null | e.g. `open` |
| `description` | TEXT | |

Value: 501 → vendor 1, $840.00, due 2026-08-28, `open`, "Rush reprint CC-TEE-WHITE S".

**Why it matters:** Accounting tracks bills here. Under the shop rule, a vendor won't ship new product while it has an open unpaid invoice, so this table can block restocking.

### `leases` (1 row)
| Field | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `space_name` | TEXT, not null | |
| `landlord` | TEXT, not null | |
| `monthly_rent` | REAL, not null | |
| `next_due` | TEXT, not null | |
| `notes` | TEXT | Currently NULL |

Value: 1 Chapel Street shop, Elm City Properties, $2,400.00/month, next due 2026-09-02.

**Why it matters:** Facilities owns the shop space. The agent uses this table to verify rent notices and know when and how much rent is due.

### `cash_accounts` (1 row)
| Field | Type | Notes |
|---|---|---|
| `name` | TEXT PK | |
| `balance` | REAL, not null | |
| `date` | TEXT, not null | Balance as-of date |

Value: `checking`, $3,400.00, as of 2026-08-31.

**Why it matters:** Accounting checks this before any payment. The pay tool must refuse if the balance is too low (no negative balances), and money only goes out in this homework.

### `payments` (0 rows)
| Field | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `kind` | TEXT, not null | Payment category |
| `ref_id` | INTEGER | ID of the item being paid |
| `amount` | REAL, not null | |
| `account` | TEXT, not null | Account the money came from |
| `paid_at` | TEXT, not null | |
| `approved_by` | TEXT, not null | Human approver |

**Why it matters:** It's the audit log of money out. Every approved payment must be recorded here with a human `approved_by`. The table is empty now, so the allowed `kind` values aren't established by the data yet, and `ref_id`/`account` have no declared FKs.

---

## 3. Relationships

```
tickets.invoice_id ──FK──> invoices.id ──FK (vendor_id)──> vendors.id
tickets.lease_id   ──FK──> leases.id
tickets.(sku,size) ·······> inventory.(sku,size)     (implied by matching columns, no FK)
tickets.sku        ·······> pricing.sku               (implied, no FK)
payments.account   ·······> cash_accounts.name        (implied by column naming, no FK)
payments.ref_id    ·······> invoices.id / leases.id   (implied; depends on kind)
desk.date_today    —— reference date for invoices.due_date and leases.next_due
```

---

## 4. Open tickets: how each one connects

All three tickets are `status = open`. The arithmetic below (shortfalls, day counts, cash totals) is derived directly from stored values.

### Ticket 101: `customer_order`, Tauhid Zaman: "Bulldog tee"
- **Request:** 1 × `CC-TEE-WHITE` size **S** ("Needs a tee in size S.")
- **inventory:** `CC-TEE-WHITE` / S has **qty 0** (Aisle B), so the order can't be filled from stock.
- **invoice_id → invoices 501:** $840.00 to vendor 1, due **2026-08-28**, status **open**, "Rush reprint CC-TEE-WHITE S". The due date is 3 days before `date_today`, so it is **overdue**.
- **vendors 1:** Bulldog Print Co, apparel reprint, lead time 5 days. It won't ship more until invoice 501 is paid.
- **pricing:** TEE cost $8.00, list $28.00.
- **Agents involved:** Inventory (stock check), Accounting (overdue invoice and payment approval), Customer Service (customer message).

### Ticket 102: `rent_notice`, Elm City Properties: "Rent due"
- **Request:** "Email: shop rent due in 2 days."
- **lease_id → leases 1:** Chapel Street shop, landlord Elm City Properties, $2,400.00, next due **2026-09-02**, which is 2 days after `date_today`. That matches the email.
- **cash_accounts:** checking $3,400.00.
- **Agents involved:** Facilities (lease verification), Accounting (payment with human approval).

### Ticket 103: `price_override`, Yale AI Club: "Bulk hoodie discount"
- **Request:** 20 × `CC-HOOD-NAVY` size **M**, with a bulk discount.
- **inventory:** `CC-HOOD-NAVY` / M has **qty 8**, a shortfall of 12. Other sizes: S 4, L 14, XL 6.
- **pricing:** HOOD cost $22.00, list $58.00, so the margin at list price is $36.00 per unit.
- **No `invoice_id` or `lease_id`.** Restocking would go through `vendors`. The only apparel vendor by specialty is Bulldog Print Co, which has open invoice 501.
- **Agents involved:** Inventory (shortfall/restock), Accounting (margin on any discount), Boss (final call on the override), Customer Service (reply to the club).

### Cross-ticket observations
- Tickets 101 and 103 both depend on **Bulldog Print Co**, which is blocked by unpaid invoice 501.
- Cash: $3,400.00 is enough to pay invoice 501 ($840) **and** rent ($2,400), which would leave **$160.00**. Any restock purchase order would then compete for that remainder.

---

## 5. MCP tools

Server: `mcp_server/server.py` (FastMCP), database `data/campus_customs_new.db`, opened **read-only**. Shop date always comes from `desk.date_today`. See `mcp_server/README.md` for parameters.

| Tool | Tables read | Ticket unlocked |
|---|---|---|
| `get_product_stock_and_price` | `inventory`, `pricing` | **103** (also supports 101) |
| `get_open_vendor_invoices` | `invoices`, `vendors`, `desk` | **101** |
| `get_lease_rent_status` | `leases`, `desk` | **102** |

### `get_product_stock_and_price`: ticket 103
- **Reads:** `inventory` (qty and location for every size of the SKU) and `pricing` (unit_cost, list_price).
- **Why it's the right tool for 103:** Yale AI Club wants 20 `CC-HOOD-NAVY` in size M at a bulk discount. One call with `size="M", qty_needed=20` returns the 8 on hand, the **12-unit shortfall**, and the $22 cost / $58 list price ($36 margin), which is exactly what Inventory needs to plan a restock and Accounting needs to decide how deep a discount the margin allows.
- **Also used for 101:** the same call with `CC-TEE-WHITE`, `S`, `qty_needed=1` confirms **0 on hand**, so the tee can't ship from stock.

### `get_open_vendor_invoices`: ticket 101
- **Reads:** `invoices` (status `open`), joined to `vendors` (name, specialty, lead_days), with `desk.date_today` for overdue math.
- **Why it's the right tool for 101:** the size-S tee is out of stock, and the only apparel vendor, Bulldog Print Co, has **invoice 501 ($840) open and 3 days overdue**. Under the shop rules it won't ship until that's paid. This tool shows the blocker, its amount, and the vendor's 5-day lead time, which is what Accounting needs to prepare the payment for approval and what Customer Service needs to give the customer a realistic date. It also explains why a restock for 103 is blocked by the same vendor.

### `get_lease_rent_status`: ticket 102
- **Reads:** `leases` (space, landlord, monthly_rent, next_due), with `desk.date_today` for days until due.
- **Why it's the right tool for 102:** the ticket is an email from Elm City Properties saying rent is due in 2 days. The tool checks it against the lease on file: lease 1, **$2,400 due 2026-09-02, 2 days after shop date**, not overdue. Facilities can confirm the notice is genuine and the amount is correct before Accounting prepares a rent payment for human approval.

### Vibe-coder connection (Problem 4)
- **Config:** `.mcp.json` at the project root registers one stdio server, `campus-customs`, which runs `.venv/Scripts/python.exe mcp_server/server.py`. The paths are relative to the project root and the file holds no secrets.
- **Database:** the same as above. `server.py` resolves `data/campus_customs_new.db` itself, so the config needs no database setting.
- **Connection verified (2026-10-14):** Claude Code loaded `.mcp.json`, connected to `campus-customs`, and discovered all three tools (as `mcp__campus-customs__<tool>`).
- **Smoke tests:** evidence is in `output/mcp_smoke.json`. Every call went through the live MCP connection, and every output matched `data/campus_customs_new.db`.

| Ticket | Tool | Arguments | Key result |
|---|---|---|---|
| 103 | `get_product_stock_and_price` | `CC-HOOD-NAVY`, `M`, `qty_needed=20` | 8 on hand, shortfall 12; cost $22 / list $58 / margin $36 |
| 101 | `get_product_stock_and_price` | `CC-TEE-WHITE`, `S`, `qty_needed=1` | 0 on hand, can't fill from stock |
| 101 | `get_open_vendor_invoices` | none (all vendors) | Invoice 501, Bulldog Print Co, $840, 3 days overdue, vendor blocked |
| 102 | `get_lease_rent_status` | `lease_id=1` | $2,400 to Elm City Properties, due 2026-09-02, 2 days out, not overdue |

- **Integrity:** both database files were still byte-identical (same SHA-256) after testing, and all three tickets remain `open`.

### Added in Problem 5
These three tools only **read** data. Problem 5 added tools for tickets, cash, vendors, payment preparation, approved payments and ticket status. See section 7 for the full list.

---

## 6. Agent team (Problem 5)

All five agents are built with **PydanticAI** (`pydantic-ai-slim` 2.56) and are defined in `backend/agents.py` (configuration) and `backend/team.py` (agent loops and delegation).

- **Model:** every agent uses **`gpt-6-luna` through Portkey** (`https://api.portkey.ai/v1`, `x-portkey-provider: openai`). The key comes from `PORTKEY_API_KEY` in `.env`.
- **No fallback:** there is no fallback model. If the key is missing, `build_model()` raises `ModelNotConfigured` instead of substituting another model.
- **Data types:** all data types are in `backend/models.py`.

| Agent | Prompt file | Responsibility | MCP tools it can call | Returns |
|---|---|---|---|---|
| **Boss** | `backend/prompts/boss.md` | Reads the ticket and names the real problem. Picks the first specialist, delegates only what the ticket needs, reviews findings, lists the human approvals needed, and decides `resolved` / `awaiting_human_approval` / `blocked` / `unresolved` from verified results. | `get_tickets` | `BossDecision` |
| **Inventory** | `backend/prompts/inventory.md` | Stock by SKU **and** size vs. the requested quantity, and the shortfall. Finds a restock vendor by specialty, checks its lead time and whether an open invoice blocks it, and gets the earliest realistic arrival. | `get_tickets`, `get_product_stock_and_price`, `list_vendors`, `get_open_vendor_invoices` | `SpecialistReport` |
| **Accounting** | `backend/prompts/accounting.md` | Cash balance, the invoices relevant to the task, and margin and discount checks. **Prepares** payments and purchase orders for human approval and shows the running balance after each. Flags anything that would overdraw cash. | `get_tickets`, `get_cash_balance`, `get_open_vendor_invoices`, `get_product_stock_and_price`, `prepare_payment_request` | `SpecialistReport` |
| **Facilities** | `backend/prompts/facilities.md` | Checks each claim in a landlord notice (sender, amount, timing) against the lease on file and gives a verdict of consistent, inconsistent or cannot verify. Hands rent to Accounting to prepare. | `get_tickets`, `get_lease_rent_status` | `SpecialistReport` |
| **Customer Service** | `backend/prompts/customer_service.md` | Drafts the reply to the requester using only verified facts from specialists. Never exposes internal data and never sends anything. | `get_tickets` | `SpecialistReport` with `customer_draft` |

**Data models (`backend/models.py`):**
- `TicketContext`: one `tickets` row.
- `DelegationRequest`: a validated agent-to-agent request.
- `Finding`: a fact plus its source tool and whether it was verified.
- `ProposedAction`: payment, purchase order, message and so on, with its `approval_status`.
- `CustomerMessageDraft`: `is_draft` is always `True`.
- `SpecialistReport`, `BossDecision`.
- `RunLimits`, `PaymentRequestRecord`, `TeamRunResult`.
- `AuditEvent`.

### How agents delegate
- **Real delegation tool:** every agent has a real `delegate_to(agent, task)` tool, so **any agent can call any other** (full connectivity). Calling it runs the target agent's own loop. Its structured report comes back as the tool result, and the caller continues with it.
- **Specialist-to-specialist calls:** specialists delegate to each other directly. For example, Inventory → Accounting to prepare a purchase order or the bill blocking a vendor, Facilities → Accounting to prepare rent, and Customer Service → Inventory for a missing fact.
- **Run context:** each agent's instructions are its prompt file plus a run-context block built for every run. The block holds the ticket record (loaded through MCP `get_tickets`), the delegation chain so far, the agents it may still call, and the limits that remain.
- **Delegation refusals:** a refusal is returned to the caller as a structured result (`delegation_refused: true` plus the reason), so the agent can finish with what it has. Delegation is refused for:
  - an agent calling itself;
  - any agent already in the chain, which prevents loops like A → B → A;
  - going past the depth limit;
  - going past the per-run delegation limit.

  Repeating the exact same task to the same agent returns the earlier report without running it again.
- **Entry points:**
  - `CampusCustomsTeam.run(entry_agent, task, ticket_id=...)` runs any agent with full delegation.
  - `run_ticket(ticket_id)` starts the Boss on a ticket. It is for the backend in Problems 7 and 9 and has **not** been run on the tickets yet.

---

## 7. MCP tools (complete list after Problem 5)

The server is still `mcp_server/server.py` with the database `data/campus_customs_new.db`.
- **Agents' connection:** the agents connect to the same server over **stdio**, through PydanticAI's `MCPToolset` (`backend/agents.py: build_mcp_toolset`).
- **No bypass:** there is no second shop-tools layer. The backend has no SQL of its own, and every shop fact and write goes through MCP.

| Tool | Table(s) | Access | Who can call it |
|---|---|---|---|
| `get_product_stock_and_price` | `inventory`, `pricing` | read | Inventory, Accounting |
| `get_open_vendor_invoices` | `invoices`, `vendors`, `desk` | read | Inventory, Accounting |
| `get_lease_rent_status` | `leases`, `desk` | read | Facilities |
| `get_tickets` | `tickets` | read | all five agents, backend |
| `get_cash_balance` | `cash_accounts`, `desk` | read | Accounting, backend |
| `list_vendors` | `vendors`, `invoices`, `desk` | read | Inventory |
| `prepare_payment_request` | `invoices`, `vendors`, `leases`, `inventory`, `pricing`, `cash_accounts`, `desk` | read (drafts only) | Accounting |
| `record_approved_payment` | `payments`, `cash_accounts`, `invoices`, `leases` (reads `vendors`, `inventory`, `pricing`, `desk`) | **write** | backend approval route only |
| `update_ticket_status` | `tickets` | **write** | backend only |

**Why each new tool exists:**
- `get_tickets`: the Boss needs the ticket fields to route the work, and the backend needs it to list tickets.
- `get_cash_balance`: every payment decision depends on the checking balance.
- `list_vendors`: tickets 101 and 103 need a restock vendor. `get_open_vendor_invoices` only shows vendors that owe a bill, so it can't show who is free to ship.
- `prepare_payment_request`: Accounting needs a database-priced, read-only draft for invoices (101), rent (102) and purchase orders (103), so no agent ever types an amount.
- `record_approved_payment`: the shop rules require the relevant tables to be updated when a human-approved payment is made.
- `update_ticket_status`: the backend has to mark tickets resolved.

### Purchase orders vs. received stock
- **An approved purchase order is a payment, not a delivery.** `record_approved_payment(kind="purchase_order")` writes a `payments` row (`kind = 'purchase_order'`, `ref_id` = vendor id, amount = qty × `unit_cost`, `paid_at` = shop date) and lowers `cash_accounts.balance` in the same transaction.
- **Stock doesn't change.** `inventory` is never written, so the stock tools keep reporting the real shelf quantity and the real shortfall. A test approves 12 × `CC-HOOD-NAVY` M on a temporary copy and checks this: M stays at 8, still 12 short.
- **Lead time:** it is computed, not stored. Both the prepare and the pay results include `lead_days` and `expected_arrival` = shop date + `vendors.lead_days`. A purchase order can only be prepared or paid once the vendor has no open invoice, so the shop date is the earliest date the vendor could start shipping. Because `desk.date_today` never advances, the approval date is the same as the shop date.
- **Order details aren't in the database.** The `payments` table has no columns for SKU, size, quantity or expected arrival. Those details are only kept in the tool results, `TeamRunResult.payment_requests`, and `output/audit_trail.json`.
- **Out of scope:**
  - a purchase-order or receiving table;
  - a tool that marks goods as received and adds them to `inventory`;
  - advancing the shop date to an arrival day.

  None of these are needed for the current tickets.

---

## 8. Audit trail (`output/audit_trail.json`)

**How it is written** (`backend/audit.py`):
- **Format:** the file is one JSON array, and each element is an `AuditEvent`.
- **Append-only:** each event is appended while the agents run. The writer reads the existing array, adds the event at the end, and atomically replaces the file (temp file + `os.replace`), so existing events are never truncated.
- **First run:** if the file doesn't exist yet, it is created.
- **Corrupt file:** if the existing file isn't a valid JSON array, the writer raises `AuditTrailCorrupt` and leaves the file untouched rather than overwriting it.
- **Secrets:** they are stripped before writing. Credential-like keys are redacted, the Portkey key value is never written, and very long strings are truncated.

| Field | Meaning |
|---|---|
| `event_id`, `timestamp` | Unique id and UTC time of the event |
| `run_id`, `run_type`, `ticket_id` | One run = one team run. `run_type` is `ticket_run`, `smoke_test` or `test`. |
| `agent`, `depth`, `chain`, `step` | Which agent, how deep in the delegation chain, the chain (e.g. `boss → inventory → accounting`), and the loop step number within that agent's run |
| `event_type` | One of the event types listed below |
| `summary`, `data` | A readable line, plus the structured details |

**Event types:**
- `run_started` / `run_finished`: the limits, then the stop reason, usage and pending approvals.
- `agent_started` (the task) / `agent_finished` (the structured output).
- `loop_step`: **every** node of the PydanticAI agent loop. That covers the request sent to the model (prompt, tool returns and retries), the model's response (text, tool calls, model name, token usage), and the final output.
- `mcp_tool_call` / `mcp_tool_result` / `mcp_tool_error` / `mcp_tool_cache_hit`: the tool name, arguments and result.
- `delegation_request` / `delegation_result` / `delegation_refused`.
- `payment_proposed`: the real tool result, `approval_status` and `executed: false`.
- `limit_reached`, `agent_error`.

The current file contains only two live **smoke-test** runs (`run_type: "smoke_test"`, no ticket). In each, Inventory checked the Yale Cap and delegated a margin question to Accounting. No ticket runs have been recorded yet.

*Update after Problem 9:* the trail now has 296 events. The first 52 (the smoke tests) are byte-for-byte unchanged. They are followed by 244 new Problem 9 events: the dashboard reset (`database_reset`), the three live ticket runs (235 `ticket_run` events), and the human approvals, the decline and the resulting ticket status changes (8 `human_action` events). See section 12.

**Known limitation in the first smoke run** (`run_id` `b8cfd2ef…`, the first 26 events):
- **What's wrong:** an early version of the redaction rule treated any key containing `token` as a secret. In that run, every token-usage field shows `"[redacted]"` (`input_tokens`, `output_tokens`, `total_tokens` in `usage` / `usage_so_far`), and so does the configured `limits.team_total_tokens_limit` (80,000, as shown in the second run).
- **What's still correct:** nothing else in that run is redacted. The tool arguments and results, delegations, outputs and request counts are complete.
- **The fix:** the rule now matches only credential-style keys.
- **The second run** (`run_id` `a9c1bf84…`) records the token counts correctly: 12,185 input + 604 output = 12,789 total, which equals the sum of its five per-response counts.
- **Left as is:** the first run's events are kept unchanged because the trail is append-only.

---

## 9. Safety: guardrails and token limits

**Money and customers:**
- **Human approval is enforced in code, not just in prompts.** The only tool that moves money, `record_approved_payment`, is not in any agent's tool list (agents literally cannot see it), and a test asserts this. Agents can only call `prepare_payment_request`, which is read-only.
- **The approval itself is checked.** The write tool requires a human `approved_by` (agent names are rejected) and recomputes the amount from the database. It refuses if that amount differs from what was approved.
- **No negative cash.** The pay tool refuses any payment larger than the balance, inside a single database transaction. The prepare tool also reports `sufficient_funds` and `balance_after`.
- **No double payments.** A paid invoice can't be paid again. A rent payment must name the current `next_due`, which moves forward after payment.
- **Vendor rule.** A purchase order to a vendor with an open invoice is refused by both the prepare and the pay tools.
- **Consistent updates.** An approved payment writes `payments`, `cash_accounts` and the invoice or lease together, or not at all.
- **Database safety.**
  - The original `campus_customs.db` can't be served: the server refuses to start on it.
  - Read tools open the working DB read-only.
  - Tests use temporary copies only.
- **Amounts come from the database.** No agent supplies an amount. Pending approvals for the backend are captured from the real tool results (`TeamRunResult.payment_requests`), not from what an agent says.
- **Nothing leaves the shop.** Customer messages are `CustomerMessageDraft` objects with `is_draft = True`. No tool sends email or contacts vendors or landlords.
- **Least privilege.** Each agent sees only the MCP tools its role needs. The MCP server process doesn't receive the Portkey key.
- **Audit.** Every step is logged with its source, so a person can reconstruct who decided what and why.

**Limits on loops and tokens** (`RunLimits` in `backend/models.py`; all are enforced in code):

| Limit | Default | What happens when it is hit |
|---|---|---|
| Delegation depth (Boss = 0) | 3 | The delegation is refused and the caller answers with what it has |
| Delegations per run | 8 | Refused |
| Model steps per agent run | 8 | That agent stops with an `incomplete` report |
| Tool calls per agent run | 10 | Further calls return "limit reached, report now" |
| Identical tool calls (same tool and args) | reused from cache, refused after 2 repeats | No duplicate MCP work |
| Team model requests per run (all agents) | 40 | `UsageLimitExceeded`. The run stops safely as `limit_reached`. |
| Team tool calls per run | 60 | Same as above |
| Team total tokens per run | 250,000 | Same as above |

- **Shared counters:** all agents in a run share one usage counter, so the team caps cover nested delegations too.
- **Safe stops:** when a cap is hit, the run returns a structured "stopped safely" result and a `limit_reached` audit event instead of looping.

**Tests:** `backend/tests/` covers this with 33 tests.
- **Mock model with the real MCP server:** delegation and limit tests use a scripted model, with the real MCP server running on temporary database copies.
- **`tests/live_smoke.py`:** a separate, opt-in live run with real `gpt-6-luna`.

---

## 10. Backend API routes (Problem 7)

**Start:** run `uvicorn main:app --reload --port 8000` from `backend/`, at `http://localhost:8000`. The routes are defined in `backend/main.py`, interactive docs are at `/docs`, and CORS allows `http://localhost:5173` and `http://127.0.0.1:5173`.

**How the backend reaches shop data:** shop data and every database write go through the same `campus-customs` MCP server the agents use (`backend/shop.py`), so the backend has no SQL of its own. Agent runs reuse `CampusCustomsTeam` unchanged. Each stdio MCP connection ends its server process when it closes (`keep_alive=False` in `build_mcp_toolset`), so no stray server processes are left behind.

- `GET /api/health`: **reads**. Reports whether the MCP server is connected and the model is configured (true/false only, no secrets), plus any runs in progress.
- `GET /api/tickets`: **reads**. Lists all tickets with every field, the current `status` (`open` / `in_progress` / `awaiting_approval` / `resolved`), `is_resolved` and `run_in_progress`, via MCP `get_tickets`.
- `GET /api/tickets/{ticket_id}`: **reads**. Returns one ticket. An unknown id gives 404, and a non-positive or non-numeric id gives 422.
- `POST /api/tickets/{ticket_id}/run`: **runs agents** (Boss on gpt-6-luna) and **changes the working DB** (ticket status only).
  - It sets the ticket to `awaiting_approval` if requests are pending, otherwise `resolved` or `in_progress` based on the Boss's decision.
  - It returns the run state, `succeeded`, the Boss's decision, usage and `pending_approvals`.
  - Errors: 409 if the ticket is already running or a reset is in progress, 503 if the model or MCP server is unavailable, 502 if the run failed. A run that hit a limit returns `succeeded: false` and leaves the status unchanged.
- `GET /api/tickets/{ticket_id}/run`: **reads**. Returns the latest run result or `running` state for that ticket since the server started.
- `GET /api/events?limit=&ticket_id=&run_id=&agent=&after=`: **reads** `output/audit_trail.json`. Returns the newest `limit` matching events (1–1000, default 200), **oldest first**, in the existing `AuditEvent` format. `after=<event_id>` lets the frontend poll for new events only. It never rewrites the file.
- `GET /api/approvals?ticket_id=`: **reads**. Lists payment requests the agents prepared that still wait for a human. Each is rebuilt from `payment_proposed` audit events and re-priced through MCP `prepare_payment_request`. Requests from before the last reset are void.
- `POST /api/approvals` with body `{request_id, approve: true, approved_by, approved_amount}`: **human approval; changes the working DB.**
  - It pays the request through MCP `record_approved_payment` and records `human_approval` or `approval_refused` in the audit trail.
  - It resolves the ticket once none of its requests are pending.
  - Errors: 404 for an unknown request, 409 for insufficient funds, an amount mismatch, a duplicate approval or a stale request, and 422 for an invalid body or an agent name as the approver.
  - If an earlier request from the same run was declined, the ticket becomes `in_progress`, not `resolved`.
- `POST /api/approvals/decline` with body `{request_id, decline: true, declined_by, reason?}`: **human decline; no financial change.**
  - It calls no payment tool, so cash, invoices, leases, inventory and `payments` are untouched. Any amount sent is ignored.
  - It records a `human_decline` audit event (request id, decision, who declined, reason, ticket and run). The request stops being pending and can't be approved later.
  - Once nothing for that ticket is pending, the ticket moves to `in_progress` (needs follow-up), never `resolved`. A new agent run on the ticket can prepare a fresh request.
  - Errors: 404 for an unknown request, 409 if already approved or declined, or stale (superseded or before a reset), and 422 for an invalid body or an agent name in `declined_by`.
  - `GET /api/approvals` also returns `decisions`: the approved and declined requests since the last reset, with who decided, when and why.
- `GET /api/cash`: **reads**. Returns the checking `balance`, `balance_as_of` and `shop_date` via MCP `get_cash_balance`.
- `POST /api/reset` with body `{confirm: true}`: **changes the working DB.** It restores `data/campus_customs_new.db` from `data/campus_customs.db`.
  - The paths are fixed in server settings and never taken from the request. The original is only read.
  - The copy is written to a temp file, checked (hash and SQLite integrity) and swapped in atomically. On failure the working DB is left unchanged.
  - Errors: 409 while a run is in progress. On success a `database_reset` audit event is recorded.

**Approval and reset safeguards:**
- **Agents can't pay.** They only prepare requests. The client can only point at a request by its audit `request_id`, never describe a payment of its own.
- **The amount is checked against the database.** The amount the person saw is re-checked against the database inside the MCP write tool, which also refuses a negative balance, a paid invoice, a duplicate rent month, and a purchase order to a vendor with an open invoice.
- **One approval at a time.** Approvals run one after another, so the same money can't be spent twice.
- **No auto-reset.** Reset never runs automatically at startup.
- **Approvals, declines and resets are logged.** They are appended to the audit trail with the person's name.

**Tests:** `backend/tests/test_api.py` uses temporary databases and a temporary audit trail with the real MCP server. Agent runs use the scripted mock model or a fake team.

---

## 11. Dashboard (Problem 8)

`frontend/` is built with React 19, Vite 8 and TypeScript, strict mode. Start it with `npm run dev` from `frontend/` (http://localhost:5173), with the backend running on port 8000. The base URL comes from `VITE_API_BASE_URL` (default `http://localhost:8000`). Design rationale is in `output/design.md`.

- **Routes used:**
  - reads: `GET /api/health`, `/api/tickets`, `/api/cash`, `/api/approvals`, `/api/events`;
  - actions: `POST /api/tickets/{id}/run`, `/api/approvals`, `/api/approvals/decline`, `/api/reset`.

  `src/api.ts` is a thin client and `src/types.ts` mirrors `backend/models.py`. No business logic is duplicated: amounts, payability and statuses come from the backend.
- **Live runs:** the run POST is synchronous, so the UI sends it without awaiting it and polls `GET /api/events?ticket_id=&after=<cursor>` every 1.5 s. The cursor is the newest event id at start. Events are merged by `event_id` (no duplicates). Polling stops when the POST settles, and then tickets, approvals, cash and health are refreshed.
- **Safety in the UI:**
  - Approve and decline are offered only for requests the backend lists as pending, using the backend's `request_id` and `amount`.
  - A human approver name is required, and agent names are rejected (the backend re-checks).
  - Errors are shown with the backend's message and never shown as success.
  - Ticket status always comes from the backend; a finished run is not treated as resolved.
  - Reset needs a typed "RESET" and is disabled during runs.
- **Verification (Problem 8):**
  - `npm run build` (tsc + vite) passes.
  - `npm test`: 16 Vitest + Testing Library tests pass against a **mocked** backend (`src/test/mockBackend.ts`). They cover statuses, loading/error/empty states, a run with overlapping polls (no duplicates, cursor advances, a single POST, the button disabled while running), status coming only from the backend, limit-reached and failed runs, and the exact approve and decline bodies, refusals, stale conflicts and the approver-name guard.
  - The dev server was launched and checked in a browser against the real backend using **read-only GETs only** (the backend log shows only GET requests). Populated states were checked with in-page mock data, with writes blocked. Layout was checked at 1280, 768 and 375 px with no overflow.
  - No ticket was run, nothing was approved, declined or reset, and both databases and the audit trail are unchanged.

---

## 12. Ticket results (Problem 9)

**How to run a fresh three-ticket pass:**
1. Start the backend: from `backend/`, `uvicorn main:app --reload --port 8000`.
2. Start the dashboard: from `frontend/`, `npm run dev` (port 5173).
3. Click **Reset working database…**, type RESET, then **Reset now**. That calls `POST /api/reset`, which copies `data/campus_customs.db` over `data/campus_customs_new.db`. It refuses while a run is active and never touches the original.
4. Run each ticket with **Run agent team**.
5. For each request a run prepares, **approve or decline** it as a named person.

**The Problem 9 run (2026-10-14):**
- **Model and usage:** all agents used `gpt-6-luna` through Portkey (responses came from `gpt-6-luna-global`). There was one run per ticket and no reruns or retries. Usage was 26 + 7 + 11 = **44 model requests** and 88,882 + 19,303 + 36,398 = **144,583 tokens**. No run-level limit was reached.
- **Starting state:** the reset was done through the dashboard. The working DB was verified as byte-identical to the original, with a clean integrity check. Checking started at **$3,400.00**, all three tickets were `open`, and there were 0 payments.

| Ticket | First call (Boss) | Delegations | Prepared request | Human decision | Cash | Final status |
|---|---|---|---|---|---|---|
| 101 | Inventory | boss→inventory, inventory→accounting, boss→accounting, boss→customer_service, customer_service→inventory, inventory→accounting | Invoice 501, $840 (the 1-tee purchase order was refused by the tool 3×: vendor had an open invoice) | Approved by Antonio Chicchón | −$840 → $2,560 | `resolved` (vendor unblocked; the tee is not yet ordered or shipped) |
| 102 | Facilities | boss→facilities, facilities→accounting | Rent lease 1, $2,400 | Approved by Antonio Chicchón | −$2,400 → $160 | `resolved` (genuinely) |
| 103 | Accounting | boss→accounting, boss→inventory, inventory→accounting | Purchase order 12 × hoodie M, $264 (insufficient funds, −$104) | Declined by Antonio Chicchón | $0 → $160 | `in_progress` (not resolved) |

**Cash reconciliation:** $3,400.00 − $840.00 − $2,400.00 = **$160.00**. This equals `cash_accounts.checking` in the working DB.
- `payments` has exactly 2 rows (#1 invoice 501, #2 rent lease 1).
- The $264 purchase order was declined and is not an outflow.
- The balance never went negative.

**Evidence:**
- `output/desk_tickets.html`: Actual sections and Cash tab filled; Expected sections preserved.
- `output/resolved_tickets.json`
- `output/resolved_board.html`: real dashboard screenshots, embedded.
- `output/audit_trail.json`: 296 events.

**Limitations found in the live run:**
1. **"Resolved" can overstate the business result.** When every prepared request is approved, the backend sets the ticket to `resolved`. For ticket 101 that means the bill is paid, but the tee still isn't ordered or delivered.
2. **Unfundable requests count as pending.** An insufficient-funds request is still counted as pending, so ticket 103 showed `awaiting_approval` while the Boss said `blocked`. The human decline then moved it to `in_progress`.
3. **Some agent work was redundant.** On ticket 101, Customer Service re-verified through Inventory → Accounting at depth 3, so that run used 26 requests. The duplicate-call cache absorbed most of the repeated tool work.
4. **Customer Service wasn't called on ticket 103,** so the Yale AI Club has no draft reply. There was also no partial-order path, because only an agent can prepare a smaller purchase order (at most 7 × $22 = $154) and a re-run was not authorized.
5. **Some model text came back with garbled characters,** for example "Weâ€™re" in the ticket 101 draft. It's cosmetic, but a person should fix it before sending.
6. **The app can't receive stock or advance the shop date,** so approved restocks never show as arriving.

---

## 13. Reflection (Problem 10)

The **Reflection** tab of `output/desk_tickets.html` answers the five Problem 10 questions using only this project's evidence: the ticket Actual sections, the Cash tab, `resolved_tickets.json`, `resolved_board.html`, and per-agent usage from the audit trail. No new runs or model calls were made.

**Main conclusions:**
- **Completion vs. resolution:** the workflow completed on all three tickets, but the business problem was genuinely resolved only for 102.
  - **101** is `resolved` only because the backend treats "all of a run's requests approved" as resolved. The tee was never ordered.
  - **103** ended `in_progress` after the $264 restock ($104 short of $160) was declined. Its status mismatch (Boss `blocked`, backend `awaiting_approval`) came from the backend counting unfundable requests as pending.
- **Performance:** 102 was clean (7 calls). 101 used 26 calls, with Accounting invoked 3 times for about 38,000 tokens, even though only 8 distinct successful tool calls were needed. 103 was honest but never answered the customer.
- **One agent vs. many:** for these tickets one agent with the same tools and backend gates would have been simpler, cheaper and just as safe. The safety came from tool and backend rules, not from the number of agents. The multi-agent design's real value was per-role tool permissions and a readable audit chain.
- **New problems:**
  - Solvable: a mug restock from Elm City Gifts ($35), a 30-cap discounted order (no cash needed), and catching an inconsistent rent email.
  - Not solvable: receiving and fulfilling goods, bringing cash in (deposits or sales), and two-way vendor and customer messaging. The tools and agents needed for each are listed in the tab.

---

## 14. GitHub submission (Problem 11)

**Public repository:** https://github.com/antoniochicchonzapata25/campus-customs-multi-agent-operations (also in `output/github_url.txt`).

**Pre-publication audit:**
- **No old history to leak:** the folder had no earlier Git history.
- **The real Portkey key** was searched for, without displaying it, in every project file and in the staged content, binaries included. It was not found.
- **Other secret patterns:** none found. No `.env` file is committed, and `.env.example` holds only a placeholder.
- **Personal data:** no local paths or email addresses appear in any committed file. Commits use the GitHub no-reply address.

**What's in the repository:**
- Everything in the assignment's file layout, plus `README.md` (setup, key configuration, starting the MCP server, backend and dashboard, and the reset procedure) and `.gitignore`.
- `.gitignore` excludes `.env`, `.venv/`, `node_modules/`, build output, caches, logs and the course instruction transcripts.
- Both databases are included and byte-identical to the local copies. `campus_customs.db` is the unchanged original; `campus_customs_new.db` is the final Problem 9 state (checking $160.00, 2 payments).
