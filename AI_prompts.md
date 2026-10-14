# AI Prompts Log: Campus Customs Multi-Agent Operations (Homework 5)

This file logs the prompts I gave my AI coding assistant (vibe coder) for Homework 5. I describe each problem in my own words, one problem at a time. I will update this file throughout the homework with the main prompt for each problem and any follow-up prompts I needed, plus a short note on what the first response was missing.

---

## Problem 1: Vibe coder prompts

**Prompt (summarized):**
> I'm starting Homework 5, Campus Customs Multi-Agent Operations. For this first problem, set up the prompt log for the whole assignment: create `AI_prompts.md` in the project root and add a Problem 1 section with the problem number/title and a short summary of this prompt. Say briefly in the file that it will be updated throughout the homework with my prompts for each problem and any follow-ups. Don't build any homework functionality yet and don't work ahead. I'll give you each problem one at a time in my own words.

**Follow-up prompt:** No follow-up prompt was necessary. The first response completed all of the requested Problem 1 setup: it created the prompt log, added the Problem 1 section, documented the initial prompt, and confirmed that no later homework functionality was started.

---

## Problem 2: Study the Campus Customs database

**Prompt (summarized):**
> Work only on Problem 2: no MCP server, agents, backend, or frontend. Find `campus_customs.db` in the project's data folder and verify it's the original. Inspect every table: all fields and types, enough real data to understand what each table represents and how they relate. Trace how the three open tickets (101, 102, 103) connect to the other tables, without inventing facts the data doesn't support. Keep the original untouched, copy it to `data/campus_customs_new.db`, and verify the copy matches. Create `output/harness.md` as the central technical reference: for every table, give the name, fields, and a short, specific note on why it matters for the agents, organized so it's easy to expand later. Add this Problem 2 section to `AI_prompts.md`. Don't modify or resolve any tickets, and preserve Problem 1. Verify everything before reporting, then give me a completion report (findings, files, checks, original unmodified, issues, and whether a follow-up is needed).

**Follow-up prompt:** No follow-up prompt was necessary. All requested Problem 2 work was completed successfully: database inspection, working-copy creation, ticket analysis, harness documentation, and verification checks.

---

## Problem 3: Build the MCP server

**Prompt (summarized):**
> Work only on Problem 3. Don't connect the server to Claude Code, don't test it through the vibe coder, and don't build agents, FastAPI, or React. Using the Problem 2 analysis, build the initial MCP server in `mcp_server/` with FastMCP, pointed at `data/campus_customs_new.db`. Implement exactly three clearly named, focused tools (no generic "run SQL") that help resolve tickets 101, 102, and 103 and will be useful to the five agents later. They should read real data instead of hardcoding ticket values, prefer read-only access, and use a project-relative path. Don't invent data, modify tickets, or touch the original database. Write `mcp_server/README.md` (purpose, database, the three tools, and the ticket/agent need each supports). In `output/harness.md`, list each tool with the tables it reads, the ticket it unlocks, and a specific reason it fits that ticket. Add this Problem 3 section to `AI_prompts.md`. Run local checks (imports, tool registration, queries match the data, correct database, original untouched, docs complete), then give me a completion report with the tools and why, tables read, tickets supported, files, checks, design decisions/limitations to review before Problem 4, and whether a follow-up is needed.

**Follow-up prompt:** No follow-up prompt was necessary. The three MCP tools were implemented, documented, locally tested against the working database, and verified without modifying either database.

---

## Problem 4: Add the MCP server to vibe coder and test each tool

**Prompt (summarized):**
> Work only on Problem 4: no agents, backend, frontend, or new MCP tools. Connect the existing Problem 3 MCP server to the vibe coder through a project-level `.mcp.json` at the project root that points to `mcp_server/server.py` and the working database setup, without creating a second server or duplicating tools. Verify the vibe coder can discover `get_product_stock_and_price`, `get_open_vendor_invoices`, and `get_lease_rent_status`. Test each one through the actual MCP connection (not by importing the module or using the in-memory client), with my own test prompts based on tickets 101 (tee stock and vendor invoice), 102 (lease/rent), and 103 (hoodie stock, pricing, shortfall), and check the results against `data/campus_customs_new.db`. Save the prompt, exact tool name, and real output for each tool in a valid, readable `output/mcp_smoke.json`. Update `output/harness.md` with the connection/testing info without removing Problem 3 content, and add this Problem 4 section to `AI_prompts.md` without a follow-up statement. Don't modify or reset either database, resolve tickets, replace the Problem 3 implementation, fake tool outputs, or expose secrets. Verify everything, then give me a completion report.

**Follow-up prompt:** No follow-up prompt was necessary. The MCP server was successfully connected to Claude Code, all three tools were called through the actual MCP connection, their outputs were verified against `data/campus_customs_new.db`, and `output/mcp_smoke.json` and `output/harness.md` were completed.

---

## Problem 5: Build the agent team and grow the MCP tools

**Prompt (summarized):**
> Work only on Problem 5. Don't start Problems 6–10 or resolve the tickets. Review the existing project first and build on it rather than replacing working pieces. Build the five-agent team in PydanticAI (Boss, Inventory, Accounting, Facilities, Customer Service), each with a clear role. The Boss analyzes the ticket, picks who goes first, delegates only what's needed, reviews findings, flags human approvals, and decides from verified results. Every agent must use `gpt-6-luna` through Portkey with `PORTKEY_API_KEY` from the environment: no hardcoded keys, no other or fallback model, and report precisely if it can't be configured. Write a detailed, role-specific prompt per agent in `backend/prompts/` (scope, what to gather, when to delegate, what to return, rules, limits, how to handle errors and uncertainty) and typed models in `backend/models.py`. Implement real, functional delegation (any agent to any agent, including specialist-to-specialist) with limits on depth, loop iterations, repeated tool calls, and tokens that stop safely. Extend the existing MCP server only with the tools the tickets genuinely need, keeping the three existing tools working and never bypassing MCP with a separate data layer. Enforce the financial rules in the tools: human approval for payments, refuse payments that exceed cash, respect the open-invoice vendor rule, and update records consistently. Never touch the original database. Record every agent-loop step in an append-only `output/audit_trail.json`. Update `output/harness.md` (agents, prompts, tools and tables, delegation, audit, safety, limits), `mcp_server/README.md`, and add this Problem 5 section here without a follow-up conclusion yet. Test configuration, delegation, MCP integration, the audit trail, and safety, clearly separating mocked tests from live ones. Then give me a detailed completion report.

**Follow-up prompt:** No additional follow-up prompt was necessary. The five-agent team, agent-to-agent delegation, MCP integration, append-only audit trail, and financial safety controls were implemented and tested. A focused verification also reviewed, documented, and verified the purchase-order behavior (an approved purchase order moves cash but does not add inventory) and the audit-trail limitation (token-count fields redacted in the first live smoke run), and neither required further code changes.

---

## Problem 6: Plan the three tickets

**Prompt (summarized):**
> Work only on Problem 6; Problems 1–5 are closed. Create `output/desk_tickets.html`, a self-contained page that opens by double-clicking (no server, build step, framework, or network), with tabs or clear sections for Ticket 101, Ticket 102, Ticket 103, Cash, and Reflection. Use the assignment, `output/harness.md`, `AI_prompts.md`, the agent code and prompts in `backend/`, and the working database as the source of truth, and keep database facts separate from my expectations. Each ticket gets an Expected section only, covering the ticket context from the database, who the Boss should call first and why, the expected delegation sequence (only the agents that matter, with alternatives marked as alternatives), the expected MCP tools (separating read-only checks and payment preparation from human-approved execution), and the expected outcome with its blockers, approvals, cash limits, and lead times. Cash and Reflection should exist but say they come later, with no made-up results. Don't run tickets or the live agents, don't approve or record any payments, and don't change the databases, audit trail, implementation, prompts, or tests. Add this Problem 6 section here, verify the page and that the databases and audit trail are unchanged (hashes before and after), confirm only the HTML file and this log changed, and give me a completion report.

**Follow-up prompt (final review):**
> Before closing Problem 6, do a narrow check of `output/desk_tickets.html` against the agent code, prompts, and MCP server: delegation paths, the split between `prepare_payment_request` and `record_approved_payment`, statuses shown as predictions, ticket 101's $840 invoice not shown as fulfilling the order, and ticket 103's $264 purchase order and $104 combined shortfall shown as conditional. Fix only material factual errors and record the outcome here.

**Review outcome:** The page matched the implementation on every point except one. On the ticket 103 tab, the "Restock cost" row in the database-facts table said $264 is what `prepare_payment_request` "would compute". That read as unconditional, but the MCP server refuses a purchase order to vendor 1 while invoice 501 is open. I corrected only that row to say the $264 comes from `pricing` and the tool would only produce it once vendor 1 has no open invoice. Everything else was already accurate, so no other changes or follow-up implementation were needed. The delegation paths follow the prompts and the `delegate_to` rules. The page marks `record_approved_payment` as backend-only after human approval. Statuses are labelled as expected. Ticket 101 states that paying #501 does not by itself fulfil the order. Ticket 103's $264 and $104 figures are correct and framed as depending on run order and human approvals.

---

## Problem 7: Backend routes

**Prompt (summarized):**
> Work only on Problem 7; Problems 1–6 are closed. Inspect the existing team, MCP server, databases, audit trail, and docs first, and build `backend/main.py` with FastAPI on top of them instead of a parallel implementation. Add REST-style routes for: listing the three tickets with their current open/resolved status (read through the MCP architecture, nothing hardcoded); running the existing agent team on one ticket (validate the id, return useful errors, block overlapping runs, never report a failed or limit-reached run as success); recent audit events in the existing schema with a documented order and a limit, without rewriting the append-only file; human approval of a payment or purchase (explicit approval and approver name, amount re-derived and checked against the database, existing invoice/rent/duplicate/purchase-order rules kept, insufficient funds refused, written through the MCP write tool); the checking balance; and a safe reset of the working database from the untouched original (fixed paths, atomic, nothing left half-copied, no reset at startup). Use Pydantic models, sensible HTTP codes, CORS for the Vite origin `http://localhost:5173`, no exposed secrets, and only gpt-6-luna. Write API tests with temporary databases and a mocked team covering tickets, invalid ids, events, cash, approvals and refusals, reset and failed reset, CORS, unavailable services, and secrets. Check that `uvicorn main:app --reload --port 8000` starts from `backend/` and verify the safe GET routes over HTTP. Don't run the real tickets, make real payments, reset or change the real databases or audit trail, or start the frontend. Document every route in one line in `output/harness.md`, update the backend docs, add this section here, and report back.

**Follow-up prompt:**
> Add a way for a human to decline a pending payment or purchase request. Require the request id, an explicit decline, and the person's name, with the same protections against agents, made-up requests, and stale requests as approval. Don't treat any amount as authoritative. A decline must not move money, mark invoices paid, or create payment records. It must be recorded in the append-only audit trail and must stop the request from showing as pending. It must not mark the ticket resolved, and the decision should be visible through the API. Test it on isolated data, rerun the full suite, update the harness, and record this follow-up here.

**What was lacking after the first prompt:** the first approval lifecycle had no way for a human to decline. A request a person rejected stayed pending until a reset or a newer run replaced it, and the ticket could sit in `awaiting_approval` indefinitely.

**Closeout:** No further follow-up prompt was needed. The backend routes, the approval and decline lifecycle, the financial safety controls and the automated tests (60 passing) were implemented and verified. Two known limitations remain documented. First, agents do not react to a decline on their own: the ticket waits in `in_progress` until someone re-runs it. Second, a declined request cannot be reversed: a new run has to prepare a fresh request.

---

## Problem 8: Agent dashboard

**Prompt (summarized):**
> Work only on Problem 8. Look at the backend first and confirm its real request and response formats, then build a React + Vite + TypeScript dashboard in `frontend/` that talks to the existing FastAPI backend (configurable URL, default `http://localhost:8000`) without copying any of its business logic. It should show the three tickets with their real statuses; let me start the agent team on a ticket without freezing the page (the run request is synchronous, so poll the events endpoint with its cursor and never show an event twice); show each agent's activity, delegations, tool calls, prepared payments, safeguards and errors in plain language with timestamps and optional technical detail; summarize what each agent contributed; report limit-reached or failed runs honestly; and offer approve and decline (with a reason) only for requests the backend lists as pending, using the backend's request id and amount and a human approver name, showing every refusal or conflict and refreshing everything afterward. Show the checking balance as currency, make clear the difference between a prepared request and a paid one, never mark a ticket resolved unless the backend says so, and include loading, error and empty states and a responsive, accessible, polished design. Write `output/design.md`, update `output/harness.md` and this log, test with a mocked backend, build it, and check it in a browser. Don't run real tickets, approve, decline or reset anything real, change the databases, audit trail or `desk_tickets.html`, or start Problem 9. Then report back.

**Completion summary:**
- **What was built:** the dashboard is in `frontend/`, with the components `Header` (cash till and health), `TicketBoard`, `TicketDetail` (run banner, "Who did what", activity timeline) and `ApprovalsPanel` (IOU slips, decision log, typed reset), plus `useDesk` for state and polling.
- **Tests:** `npm run build` passes, and all 16 Vitest + Testing Library tests pass against a mocked backend.
- **Browser check:** the app was launched and checked in a browser against the real backend using only read requests (the backend log shows GETs only). Populated states were checked with in-page sample data. The layout was checked on desktop, tablet and phone widths.
- **Nothing real was touched:** no real ticket was run, nothing was approved, declined or reset, and the databases and audit trail are unchanged.

**Remaining limitations:**
- A live end-to-end run with the real model has not been seen in the dashboard yet; that happens in Problem 9.
- The run result banner lives in browser memory and the backend's in-memory latest run, so it clears on a page reload. The activity, statuses and decisions do persist, because they come from the audit trail and the database.

**Closeout:** Problem 8 is complete, and no further follow-up prompt is needed:
- All the required dashboard features are built.
- The production build succeeds.
- All 16 frontend tests pass.
- The dashboard was checked against the real backend with read-only requests.

Three known limitations remain, and none of them blocks closing this problem:
- The full live workflow with the real model hasn't been tested yet; that belongs to Problem 9.
- The finished-run banner doesn't survive a page reload.
- The desktop screenshots captured only part of the page.

---

## Problem 9: Resolve the tickets

**Prompt (summarized):**
> Run Problem 9 for real: no work on Problems 10–11, no GitHub, no extra spending. Before any model call, check the model, limits, retries, timeouts and the risk of duplicate runs, and stop if you can't confirm the Portkey usage is funded. Reset the working database through the app without touching the original, verify it, and record the starting cash ($3,400 expected, but check it). Run tickets 101, 102 and 103 once each, in order, through the dashboard and the real five-agent team on gpt-6-luna. Record what the agents actually do, and stop instead of retrying on errors or limits. Never approve anything yourself: for every payment or purchase, show me the purpose, amount, current and projected balance, and the effect on the other tickets, and wait for my decision. Keep in mind that $840 + $2,400 + $264 = $3,504 is more than $3,400, never allow a negative balance, and never invent money or call a ticket resolved when it isn't. Then fill the Actual sections and the Cash tab in `desk_tickets.html` (Expected stays as written), create `resolved_tickets.json` and `resolved_board.html` with real dashboard screenshots, keep the audit trail intact, finish `harness.md`, add this section, and give me a full report.

**Follow-up prompts:**
> 1. "The course key is funded, go ahead with ticket 101." I confirmed the funding, then repeated the run order and the rule to pause before every approval.
> 2. "Approve invoice 501 for $840.00, recording Antonio Chicchón as the (human) approver," then verify and continue.
> 3. "Approve the rent payment, recording Antonio Chicchón as approver," then verify and go on to ticket 103.
> 4. "Decline the $264.00 purchase order" with the reason "Insufficient cash: $264 required versus $160 available after paying invoice 501 and rent. No purchase commitment is authorized." Then finish the deliverables, with no reruns and no more model calls.

**What was lacking after the first prompt:** the first prompt correctly stopped after the preflight, because nothing in the project showed the Portkey key was funded. Each later follow-up was a human decision the workflow requires by design (funding confirmation, then approve, approve, decline), not a fix for a mistake.

**Completion summary:**
- **Runs:** each ticket was run once, live, through the dashboard. That came to 44 model requests and 144,583 tokens in total, with no errors, no run-limit stops and no reruns.
- **Ticket 101: `resolved` (status mismatch).** The Boss decided `awaiting_human_approval`, and invoice 501 ($840) was approved and paid, which unblocks the vendor. The backend then set the ticket to `resolved` because all of the run's requests were approved. In business terms it is not resolved: the tee is not yet ordered or delivered (size-S stock is still 0), and the customer reply is only a draft.
- **Ticket 102: `resolved`.** The notice was verified, and the $2,400 rent was approved and paid. This one is genuinely resolved.
- **Ticket 103: `in_progress` (not resolved).** The 12-hoodie restock cost $264, but only $160 was left, a $104 shortfall, so the tool marked it insufficient funds. The Boss decided `blocked`, while the backend showed `awaiting_approval` until the human decline moved the ticket to `in_progress`. No discount was decided.
- **Cash:** $3,400 − $840 (payment #1, invoice 501) − $2,400 (payment #2, rent) = **$160.00**, which matches `cash_accounts`. The declined $264 purchase order and the tool-refused $8 tee order are not counted as outflows. The original database is unchanged.

**Remaining limitations:**
- "Resolved" on ticket 101 overstates the business result, since the tee isn't ordered yet.
- An unfundable request still counts as pending, so ticket 103 showed `awaiting_approval` until the decline.
- Ticket 101's run did redundant agent work.
- No reply was drafted for ticket 103, and there's no partial-restock path without another run.
- Some model text came back with garbled characters.
- The app can't receive stock.

**Closeout:** No follow-up implementation prompt was needed during Problem 9. The existing agents, backend, dashboard and safeguards ran all three tickets live without errors or limit stops, and the gaps found are documented as limitations rather than fixed. Changing the code mid-run would have meant reruns and extra model usage.

---

## Problem 10: Reflection

**Prompt (summarized):**
> Start Problem 10. Review the assignment and the existing evidence (`desk_tickets.html`, `resolved_tickets.json`, `resolved_board.html`, the audit trail, `harness.md`, this log, and the backend, prompts and dashboard), and fill the Reflection tab using only the real ticket runs; don't invent results or claim untested functionality. Cover:
> - Expected vs. Actual for 101–103: delegation order, who took part, statuses, money decisions, outcomes.
> - Where specialization and delegation helped, and where agents duplicated work or wasted model calls, with audit-trail evidence.
> - Whether the multi-agent design was justified.
> - Three new problems the current tools could solve, and why.
> - Three they couldn't, naming the missing data, tool, capability or human decision.
>
> Be candid that ticket 101 was marked resolved without the tee being ordered or delivered, and discuss 103's insufficient-funds outcome and the Boss-vs-backend status mismatch. Don't change code, rerun tickets, call the model, or touch the databases or audit trail. Update the harness and this log, validate locally, and report back.

**Completion summary:**
- **The Reflection tab** answers the assignment's five questions with evidence from this project:
  - a graded evaluation of each ticket (101 B−, 102 A, 103 B);
  - an Expected-vs-Actual table;
  - a one-agent vs. multi-agent analysis using per-agent model calls and tokens from the audit trail;
  - three solvable and three unsolvable new problems.
- **Main finding:** the workflow completed on all three tickets, but the business problem was genuinely resolved only for 102. 101's "resolved" means no approvals are pending, not that the customer got a tee. 103 was blocked by the $104 cash gap, and its status mismatch came from the backend counting unfundable requests as pending.
- **One agent vs. many:** one agent with the same tools and gates would have been simpler and cheaper for these tickets. Safety came from the tool and backend rules, not the number of agents.
- **Checks:** the HTML is well-formed, the ticket and Cash tabs are unchanged, the Expected sections still match Problem 6, and the databases and audit trail are untouched.

**Limitations:** the one-agent alternative is reasoned from audit-trail evidence, not tested; no single-agent run was made, to avoid extra model usage.

**Follow-up prompt:** none needed. The reflection is analysis of existing evidence, and nothing had to be implemented or rerun.

**Closeout:** Problem 10 is complete. The Reflection tab answers all five assignment questions, ties every answer to tickets 101–103 and the Cash tab, and passed local validation. The ticket tabs, Cash tab, databases and audit trail are unchanged. One small limitation: the tab was checked structurally, not viewed in a browser.

---

## Problem 11: Submit to GitHub

**Prompt (summarized):**
> Final problem. Read the assignment and inspect the whole project and its Git state first. Before publishing anything, audit for secrets: check `git status`, branches, remotes, `.gitignore`, `.env`, `.mcp.json`, logs and outputs. Search files and Git history for keys without ever printing them, and stop and propose a fix if anything was exposed. Confirm every required deliverable, including both databases: the original unchanged, and the working copy at the final $160 with two payments. Make sure the README explains installing, configuring the Portkey key without publishing it, starting the MCP server, backend and dashboard, and resetting before a fresh run. Don't call the model, rerun tickets, approve payments, reset databases or change the audit trail. Then create a public repo (e.g. `campus-customs-multi-agent-operations`), commit, push, check the public URL works, and save it in `output/github_url.txt`.

**What was done:**
- **Audit, all clean:**
  - There was no earlier Git history.
  - The real key was not found in any file or in the staged content, binaries included.
  - No `.env` file is published, and `.env.example` holds only placeholders.
  - No local paths or email addresses appear in committed files.
- **Added:** `.gitignore` and the root `README.md`.
- **Privacy:** commits use the GitHub no-reply email instead of the personal address.
- **Git ownership warning:** the folder belongs to another Windows account, so Git flagged it as unsafe. Each command was told to trust it explicitly, leaving the global Git config unchanged.
- **Published:** a public repository with all 63 project files, both databases byte-identical to the local copies. The URL is in `output/github_url.txt`.

**Follow-up prompt:** none needed. The audit was clean, so publishing went ahead as the prompt authorized. The only problem was Git's folder-ownership warning, solved without changing any settings or files.
