// UI tests against a MOCKED backend (mockBackend.ts). No real API, database, or model is used.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
import type { AuditEvent, TicketRunResponse } from "../types";
import { baseRoutes, CASH, ev, mockBackend, PENDING_RENT, TICKETS } from "./mockBackend";

function setup(routes = baseRoutes()) {
  const backend = mockBackend(routes);
  vi.stubGlobal("fetch", backend.fetchMock);
  const user = userEvent.setup();
  render(<App pollMs={25} />);
  return { ...backend, user };
}

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

const eventsBody = (events: AuditEvent[]) => ({ body: { total: events.length, returned: events.length, skipped: 0, order: "oldest_first", events } });

describe("overview", () => {
  it("shows the three tickets, their backend statuses, and the cash balance", async () => {
    const routes = baseRoutes();
    routes["GET /api/tickets"] = () => ({ body: { count: 3, tickets: [TICKETS[0], { ...TICKETS[1], status: "awaiting_approval" }, { ...TICKETS[2], status: "resolved", is_resolved: true }] } });
    setup(routes);
    const board = await screen.findByRole("region", { name: "Tickets" });
    expect(within(board).getByText("Bulldog tee")).toBeInTheDocument();
    expect(within(board).getByText("Rent due")).toBeInTheDocument();
    expect(within(board).getByText("Bulk hoodie discount")).toBeInTheDocument();
    expect(within(board).getByText("1 × CC-TEE-WHITE, size S · invoice #501")).toBeInTheDocument();
    expect(within(board).getByText("Open")).toBeInTheDocument();
    expect(within(board).getByText("Awaiting approval")).toBeInTheDocument();
    expect(within(board).getByText("Resolved")).toBeInTheDocument();
    expect(await screen.findByTestId("cash-balance")).toHaveTextContent("$3,400.00");
    expect(screen.getByText(/Nothing is waiting for approval/)).toBeInTheDocument();
    expect(await screen.findByText(/No agent activity recorded/)).toBeInTheDocument();
  });

  it("shows clear error and empty states", async () => {
    const routes = baseRoutes();
    routes["GET /api/tickets"] = () => ({ status: 503, body: { detail: "Shop data service (MCP server) is unavailable" } });
    routes["GET /api/cash"] = () => ({ status: 503, body: { detail: "Shop data service (MCP server) is unavailable" } });
    routes["GET /api/approvals"] = () => ({ status: 500, body: { detail: "Audit trail is unreadable; it was not modified" } });
    routes["GET /api/health"] = () => ({ status: 500, body: {} });
    setup(routes);
    expect(await screen.findByText(/Could not load tickets: Shop data service/)).toBeInTheDocument();
    expect(await screen.findByText(/Balance unavailable/)).toBeInTheDocument();
    expect(await screen.findByText(/Could not load approvals: Audit trail is unreadable/)).toBeInTheDocument();
    expect(screen.getByText("Backend unreachable")).toBeInTheDocument();
  });

  it("shows an empty desk when there are no tickets", async () => {
    const routes = baseRoutes();
    routes["GET /api/tickets"] = () => ({ body: { count: 0, tickets: [] } });
    setup(routes);
    expect(await screen.findByText("No tickets on the desk.")).toBeInTheDocument();
  });
});

describe("running the team", () => {
  it("polls events without duplicates while the run request is pending, then shows the backend's status", async () => {
    let finishRun!: (r: { status?: number; body: unknown }) => void;
    let ticketStatus = "open";
    const cursor = ev({ event_type: "database_reset", ticket_id: null, run_id: "x", event_id: "cursor0" });
    const e1 = ev({ event_type: "run_started", data: { entry_agent: "boss", task: "Work ticket 102" } });
    const e2 = ev({ event_type: "delegation_request", agent: "boss", data: { to_agent: "facilities", task: "Verify the notice" } });
    const e3 = ev({ event_type: "payment_proposed", agent: "accounting", data: { request: { kind: "rent", payee: "Elm City Properties", amount: 2400 }, approval_status: "pending_human_approval" } });
    const polls: (string | null)[] = [];
    let pollCount = 0;
    const routes = baseRoutes();
    routes["GET /api/tickets"] = () => ({ body: { count: 3, tickets: TICKETS.map((t) => (t.id === 102 ? { ...t, status: ticketStatus } : t)) } });
    routes["GET /api/events"] = (c) => {
      if (c.query.get("limit") === "1") return eventsBody([cursor]);
      if (!c.query.get("after")) return eventsBody([]); // history load
      polls.push(c.query.get("after"));
      pollCount += 1;
      // Overlapping pages on purpose: e1 and e2 come back more than once.
      return eventsBody(pollCount === 1 ? [e1, e2] : pollCount === 2 ? [e1, e2, e3] : [e3]);
    };
    routes["POST /api/tickets/102/run"] = () => new Promise((resolve) => { finishRun = resolve; });
    const { user, calls } = setup(routes);

    const card = (await screen.findByRole("button", { name: /Ticket 102/ })).closest("li")!;
    await user.click(within(card).getByRole("button", { name: "Run agent team" }));

    expect(await screen.findByText("The team is working on this ticket.")).toBeInTheDocument();
    const runButton = within(card).getByRole("button", { name: /Team working/ });
    expect(runButton).toBeDisabled();
    await user.click(runButton); // disabled: no second run
    await screen.findByText(/Accounting prepared a payment request — NOT paid/);

    // Each event appears exactly once despite overlapping polls.
    expect(screen.getAllByText("Boss asked Facilities for help")).toHaveLength(1);
    expect(screen.getAllByText(/Team run started/)).toHaveLength(1);
    expect(polls[0]).toBe("cursor0");
    expect(polls).toContain(e2.event_id); // cursor advanced
    expect(calls.filter((c) => c.method === "POST" && c.path === "/api/tickets/102/run")).toHaveLength(1);
    expect(calls.some((c) => c.path === "/api/events" && c.query.get("ticket_id") === "102")).toBe(true);

    // The run ends successfully, but the backend says the ticket awaits approval: we show that, not "Resolved".
    ticketStatus = "awaiting_approval";
    const result: TicketRunResponse = {
      ticket_id: 102, run_id: "run-1", state: "completed", succeeded: true, resolution_status: "awaiting_human_approval",
      summary: "Rent verified and prepared for approval.", ticket_status: "awaiting_approval", delegations: 2,
      usage: { requests: 6, total_tokens: 9000 }, pending_approvals: [PENDING_RENT], output: {}, error: null,
      started_at: "2026-10-14T15:00:00Z", finished_at: "2026-10-14T15:01:00Z",
    };
    finishRun({ body: result });
    expect(await screen.findByText("Run finished")).toBeInTheDocument();
    expect(screen.getByText("Rent verified and prepared for approval.")).toBeInTheDocument();
    await waitFor(() => expect(within(card).getByText("Awaiting approval")).toBeInTheDocument());
    expect(within(card).queryByText("Resolved")).not.toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Run agent team" })).toBeEnabled();
    // Polling stopped and views were refreshed after the run.
    const after = calls.length;
    await new Promise((r) => setTimeout(r, 120));
    expect(calls.slice(after).filter((c) => c.query.get("after"))).toHaveLength(0);
    expect(calls.filter((c) => c.path === "/api/cash").length).toBeGreaterThanOrEqual(2);
    expect(calls.filter((c) => c.path === "/api/approvals").length).toBeGreaterThanOrEqual(2);
  });

  it("reports a limit-reached run honestly and a failed run as an error", async () => {
    const routes = baseRoutes();
    routes["POST /api/tickets/101/run"] = () => ({ body: {
      ticket_id: 101, run_id: "r", state: "limit_reached", succeeded: false, resolution_status: null, summary: "Stopped safely: cap",
      ticket_status: null, delegations: 8, usage: {}, pending_approvals: [], output: null,
      error: "Run did not produce a complete Boss decision", started_at: "2026-10-14T15:00:00Z", finished_at: null } });
    routes["POST /api/tickets/103/run"] = () => ({ status: 503, body: { detail: "gpt-6-luna is not configured (PORTKEY_API_KEY missing)" } });
    const { user } = setup(routes);
    const card101 = (await screen.findByRole("button", { name: /Ticket 101/ })).closest("li")!;
    await user.click(within(card101).getByRole("button", { name: "Run agent team" }));
    expect(await screen.findByText(/stopped at a safety limit — not a complete decision/)).toBeInTheDocument();
    expect(screen.getByText("Run did not produce a complete Boss decision")).toBeInTheDocument();
    expect(within(card101).getByText("Open")).toBeInTheDocument();

    const card103 = screen.getByRole("button", { name: /Ticket 103/ }).closest("li")!;
    await user.click(within(card103).getByRole("button", { name: "Run agent team" }));
    expect(await screen.findByText("Run did not complete")).toBeInTheDocument();
    expect(screen.getByText(/gpt-6-luna is not configured/)).toBeInTheDocument();
  });
});

describe("approvals", () => {
  function withPending() {
    const routes = baseRoutes();
    let pending = [PENDING_RENT];
    let decisions: unknown[] = [];
    routes["GET /api/approvals"] = () => ({ body: { count: pending.length, approvals: pending, decisions } });
    return { routes, settle: (d: unknown) => { pending = []; decisions = [d]; } };
  }

  it("requires a human name and blocks agent names", async () => {
    const { routes } = withPending();
    const { user, calls } = setup(routes);
    const approve = await screen.findByRole("button", { name: "Approve & pay $2,400.00" });
    expect(approve).toBeDisabled();
    await user.type(screen.getByLabelText(/Your name/), "Accounting");
    expect(screen.getByText(/agents cannot approve or decline/)).toBeInTheDocument();
    expect(approve).toBeDisabled();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("approves with the backend's request id and amount, then refreshes cash and decisions", async () => {
    const { routes, settle } = withPending();
    let balance = 3400;
    routes["GET /api/cash"] = () => ({ body: { ...CASH, balance } });
    routes["POST /api/approvals"] = (c) => {
      balance = 1000;
      settle({ request_id: c.body.request_id, ticket_id: 102, run_id: "run-1", decision: "approved", decided_by: c.body.approved_by,
        decided_at: "2026-10-14T15:02:00Z", kind: "rent", ref_id: 1, amount: 2400, reason: null });
      return { body: { status: "paid", request_id: c.body.request_id, ticket_id: 102, message: "Paid 2400.00 to Elm City Properties",
        payment: { amount: 2400 }, balance_after: 1000, ticket_status: "resolved" } };
    };
    const { user, calls } = setup(routes);
    await user.type(await screen.findByLabelText(/Your name/), "Store Manager");
    expect(screen.getByText("NOT PAID")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Approve & pay $2,400.00" }));

    const post = calls.find((c) => c.method === "POST" && c.path === "/api/approvals")!;
    expect(post.body).toEqual({ request_id: PENDING_RENT.request_id, approve: true, approved_by: "Store Manager", approved_amount: 2400 });
    expect(await screen.findByTestId("cash-balance")).toHaveTextContent("$1,000.00");
    expect(await screen.findByText(/Approved by Store Manager/)).toBeInTheDocument();
    expect(screen.getByText("PAID")).toBeInTheDocument();
    expect(screen.getByText(/Nothing is waiting for approval/)).toBeInTheDocument();
  });

  it("shows a refused approval as an error and never as paid", async () => {
    const { routes } = withPending();
    routes["POST /api/approvals"] = (c) => ({ status: 409, body: { status: "refused", request_id: c.body.request_id, ticket_id: null,
      message: "Insufficient funds: checking has 500.0, payment needs 2400.0. Refused so the balance cannot go negative.",
      payment: null, balance_after: null, ticket_status: null } });
    const { user } = setup(routes);
    await user.type(await screen.findByLabelText(/Your name/), "Store Manager");
    await user.click(screen.getByRole("button", { name: "Approve & pay $2,400.00" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Insufficient funds/);
    expect(screen.queryByText("PAID")).not.toBeInTheDocument();
    expect(screen.getByTestId("cash-balance")).toHaveTextContent("$3,400.00");
    expect(screen.getByText("NOT PAID")).toBeInTheDocument(); // still pending
  });

  it("declines with an explicit decision, name, and reason", async () => {
    const { routes, settle } = withPending();
    routes["POST /api/approvals/decline"] = (c) => {
      settle({ request_id: c.body.request_id, ticket_id: 102, run_id: "run-1", decision: "declined", decided_by: c.body.declined_by,
        decided_at: "2026-10-14T15:02:00Z", kind: "rent", ref_id: 1, amount: 2400, reason: c.body.reason });
      return { body: { status: "declined", request_id: c.body.request_id, ticket_id: 102,
        message: "Declined rent 1; no payment was made", payment: null, balance_after: null, ticket_status: "in_progress" } };
    };
    const { user, calls } = setup(routes);
    await user.type(await screen.findByLabelText(/Your name/), "Store Manager");
    await user.click(screen.getByRole("button", { name: "Decline…" }));
    await user.type(screen.getByLabelText(/Reason/), "Check with the landlord first");
    await user.click(screen.getByRole("button", { name: "Confirm decline" }));
    const post = calls.find((c) => c.method === "POST" && c.path === "/api/approvals/decline")!;
    expect(post.body).toEqual({ request_id: PENDING_RENT.request_id, decline: true, declined_by: "Store Manager", reason: "Check with the landlord first" });
    expect(await screen.findByText("DECLINED")).toBeInTheDocument();
    expect(screen.getByText("“Check with the landlord first”")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.path === "/api/approvals")).toBe(false);
    expect(screen.getByTestId("cash-balance")).toHaveTextContent("$3,400.00");
  });

  it("surfaces stale / already-decided conflicts", async () => {
    const { routes } = withPending();
    routes["POST /api/approvals/decline"] = (c) => ({ status: 409, body: { status: "refused", request_id: c.body.request_id,
      ticket_id: null, message: "This request was already approved", payment: null, balance_after: null, ticket_status: null } });
    const { user } = setup(routes);
    await user.type(await screen.findByLabelText(/Your name/), "Store Manager");
    await user.click(screen.getByRole("button", { name: "Decline…" }));
    await user.click(screen.getByRole("button", { name: "Confirm decline" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This request was already approved");
    expect(screen.queryByText("DECLINED")).not.toBeInTheDocument();
  });
});
