# Campus Customs Desk: dashboard design (Problem 8)

**What it is:** the React + Vite + TypeScript app in `frontend/`. It talks only to the FastAPI backend (`VITE_API_BASE_URL`, default `http://localhost:8000`).

**The desk metaphor:** the dashboard is built to feel like a real shop counter.
- Tickets look like **ticket stubs**.
- The balance sits in a **till**.
- Money the agents want to spend shows up as **IOU slips** stamped *NOT PAID*, until a person signs off.

**Style:** everything is drawn with CSS: the monogram avatars, the perforated edges, the stamps and the logo. There are no images or web fonts. The palette is the project's default blue-grey.

## 1. Layout and navigation

There is one page, with a dark blue-grey masthead and a three-column work area.

| Area | Contents |
|---|---|
| **Masthead** | The brand, a backend health pill (ready/degraded, shop data connected, `gpt-6-luna` configured; true/false only, no secrets), and the **checking-account till**. |
| **Left column** | The **ticket board** (all tickets from `GET /api/tickets`) and a **Fresh start** card for resetting the working database. |
| **Centre column** | The **ticket workspace** for the selected ticket: its details, a plain-language status explanation, the run banner, *Who did what*, and the **Activity** timeline. |
| **Right column** | **Needs your decision**: the approver-name field, the pending IOU slips and the **Decision log**. |

**Navigation:**
- Clicking a ticket stub selects it.
- Each stub has its own **Run agent team** button.
- The first ticket is selected automatically once tickets load.
- A *Skip to ticket workspace* link is the first focusable element.

## 2. Tickets and statuses

- **Stub contents:** each stub shows the id, subject, type, requester, a one-line summary built only from the ticket's fields (for example `1 × CC-TEE-WHITE, size S · invoice #501`), the requester's note in quotes, and a status badge.
- **Status source:** the status always comes from the backend (`tickets.status`). The UI never infers it. A run that "finished" does not make a ticket resolved; only the backend's status does.
- **Status hint:** in the workspace, every status has a one-line hint, for example *"A payment the agents prepared is waiting for a person to approve or decline it."*

## 3. Agents and their activity

- **Agent identity:** each agent has a colour and a CSS monogram avatar: Boss (navy, BO), Inventory (teal, IN), Accounting (amber, AC), Facilities (violet, FA) and Customer Service (rose, CS). The same colour is used on the avatar and on that agent's *Who did what* card.
- **Who did what (latest run):** one card per agent that took part, with its role, its own final report (from that run's `agent_finished` event), and counts of shop-data checks and hand-offs. If an agent never filed a report (still working, or stopped early), the card says so. No summary is ever made up.
- **Activity timeline:** the audit trail rendered as sentences (`src/present.ts`), each with a timestamp and the agent's avatar. For example:
  - *"Boss asked Facilities for help"*
  - *"Facilities checked the lease and rent: Chapel Street shop: $2,400.00 due 2026-09-02 (in 2 days)"*
  - *"Accounting prepared a payment request — NOT paid"*

  Every row is tinted by kind:

| Kind | Look |
|---|---|
| Delegation (asked / reported back / reused) | grey-blue rail |
| Shop-data tool result | 🔎 prefix |
| Payment prepared (not paid) | violet, like the IOU slips |
| Safeguards (delegation refused, tool refused, usage limit) | amber |
| Errors | red |
| Human approval / decline | green |
| Run start/finish, ticket status changes, reset | slate text |

- **Technical details:** low-level loop steps and raw tool calls are hidden behind a **Show technical steps** toggle. Every row also has a collapsible *Technical details* block with the raw event (type, run id, delegation chain, data) for anyone auditing.
- **Long trails:** the timeline scrolls inside its own panel and renders at most the latest 250 entries, with a note saying so.

### Live runs
`POST /api/tickets/{id}/run` is **synchronous**: it only returns when the whole run ends. So the dashboard (`useDesk.startRun`):
1. Reads the newest audit event id as a **cursor** (`GET /api/events?limit=1`).
2. Sends the run request **without awaiting it**.
3. Polls `GET /api/events?ticket_id=…&after=<cursor>` every 1.5 s and moves the cursor forward. Events are merged by `event_id`, so overlapping pages never show twice.
4. When the run request settles, it polls once more, stops polling, and refreshes tickets, approvals, cash and health.

While a run is active, the stub's button turns into *Team working…* (disabled), and a pulsing **"The team is working on this ticket"** banner appears. A second click can't start a duplicate run, and the backend's own 409 is still shown if it ever occurs.

The **run banner** reports the outcome honestly:
- **Finished (green):** shows the Boss decision, its reason, and the ticket status the backend set.
- **"Stopped at a safety limit — not a complete decision" (amber):** a limit-reached run.
- **"Run did not complete" (red):** an errored run, a model that isn't configured, or the backend being unreachable. The backend's error message is shown.

## 4. Pending approvals and past decisions

**Pending requests:** each one from `GET /api/approvals` is an **IOU slip**: dashed violet border, a tilted **NOT PAID** stamp, the ticket and which agent prepared it, the type and payee, the amount (large), what it's for (invoice and due date, rent month, or quantity/SKU/size and expected arrival), and **Checking now → After paying**.
- **Every number comes from the backend.** The slip shows the backend's re-priced figures. The amount sent on approval is the backend's own `amount` for that `request_id`; the frontend never calculates a payable amount.
- **Approve:** the **Approve & pay $X** button sends `{request_id, approve: true, approved_by, approved_amount}`.
- **Decline:** **Decline…** opens an optional reason box (500 characters, the API limit). **Confirm decline** sends `{request_id, decline: true, declined_by, reason}`.
- **Approver name:** both actions stay disabled until the **Your name** field is filled in. Agent names (Boss, Accounting, Customer Service, "agent", …) are rejected in the UI with a message. The backend makes the same check and is the real gate. The name is kept in `localStorage` for convenience.
- **Insufficient funds:** if the backend reports `sufficient_funds: false`, the slip warns that approval will be refused but still allows a decline.
- **Errors are shown as errors.** Refusals (insufficient funds, amount mismatch, stale request, already approved or declined, validation) appear as a red alert under the slip, with the backend's own message. Nothing is shown as paid unless the backend says `paid`.
- **After any decision,** approvals, decisions, cash, tickets, health and that ticket's activity all reload.

**Decision log:** newest first, from the `decisions` the backend returns. Each entry has a green **PAID** stamp or a red **DECLINED** stamp, plus type, reference, amount, ticket, who decided, when, and any reason.

## 5. Checking balance

- **The till:** the balance is the largest number on the page, in a receipt-style card with a green top edge. It is formatted as US dollars with tabular numerals, and shows the "as of" date and the shop date.
- **Proposed vs. paid:** a note under the balance says *"Only approved payments change this number. Prepared requests don't."* The slips show the balance after paying as a projection, clearly separate from the till.
- **Refresh:** the till reloads on page load, after every run, after every approve or decline, after a reset, and with its ↻ button. It shows a spinner while refreshing, and an inline error if loading fails (keeping the last good value if there was one).

## 6. Resolved, in progress and awaiting approval

| Status | Stub edge | Badge | Workspace hint |
|---|---|---|---|
| `open` | slate | "Open" | Open: no team run has settled this ticket yet |
| `in_progress` | amber | "In progress" | The team ran, but the ticket still needs follow-up (for example, a request was declined) |
| `awaiting_approval` | violet | "⏳ Awaiting approval" | A payment is waiting for a person; the hint also counts the slips in the queue |
| `resolved` | green, with a faint green stub | "✓ Resolved" | The backend has marked this ticket resolved |

Status is never shown by colour alone: there's always a text label, and icons for the two states that matter most.

## 7. Loading, error and empty states

| Area | States |
|---|---|
| **Loading** | "Loading tickets…", "Loading approvals…", "Loading…" in the till, "Loading the desk…" in the workspace (all `aria-busy`). Refreshes show small spinners and keep the old data on screen. |
| **Errors** | "Could not load tickets: …", "Balance unavailable: …", "Could not load approvals: …", "Activity unavailable: …", and "Backend unreachable" in the health pill. Each uses the backend's own message, normalised from `{detail}`, FastAPI's validation list, or an `ApprovalResponse.message`. A network failure says *"Cannot reach the backend. Is it running on http://localhost:8000?"* |
| **Empty** | "No tickets on the desk.", "Nothing is waiting for approval.", "No approvals or declines since the last reset.", "No agent activity recorded for this ticket yet." |

## 8. Responsive behaviour and accessibility

**Responsive layout:**
- **Over 1180 px:** three columns.
- **760–1180 px:** two columns, with approvals moved below.
- **Under 760 px:** a single column, and the till stretches full width.

I checked 1280 px, 768 px and 375 px in a browser; there was no horizontal overflow at any width.

**Accessibility:**
- **Page structure:** semantic landmarks (banner, main, two complementary columns, contentinfo) and labelled regions.
- **Ticket stubs:** buttons with `aria-pressed` and descriptive labels ("Ticket 102: Rent due").
- **Live updates:** the run banner, the cash amount and the activity list are `aria-live`. Errors use `role="alert"` and successes `role="status"`.
- **Form fields:** every input has a label, and the approver field uses `aria-invalid` and `aria-describedby`.
- **Keyboard:** visible focus rings, and the skip link.
- **Motion and contrast:** `prefers-reduced-motion` turns off the pulse and spinner animations, and text colours were chosen for contrast on their tinted backgrounds.

## 9. Creative and usability choices

- **IOU slip vs. PAID stamp:** the most important idea on this desk is that agents can only *propose* spending money. Making a proposal look like an unsigned IOU, and only a person's approval turn it into a stamped receipt, makes that rule visible without anyone having to read it.
- **Plain-language feed, with the audit one click away:** a store manager reads "Accounting prepared a payment request — NOT paid", while an auditor can expand the raw event. Low-level loop steps stay hidden by default so the story is readable.
- **"Who did what":** each agent's own final report, so you can see the delegation chain at a glance instead of scrolling dozens of events.
- **Honest run outcomes:** limit-reached and failed runs get their own amber or red banners. The ticket status always shows the backend's view, even when a run "finished".
- **Typed reset confirmation:** resetting the working database requires typing RESET, and it's disabled while a run is in progress (the backend also refuses with a 409).
- **No hidden business logic:** `src/api.ts` is a thin client. Amounts, payability, stale-request checks and status changes all stay in the backend.
