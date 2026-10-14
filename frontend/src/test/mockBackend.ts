// A fake FastAPI backend for tests: routes fetch() calls, records them, and returns
// responses shaped exactly like backend/models.py. No real backend is touched.
import type { AuditEvent, PendingApproval, Ticket } from "../types";

export interface Call { method: string; path: string; query: URLSearchParams; body: any } // eslint-disable-line @typescript-eslint/no-explicit-any
type Handler = (call: Call) => { status?: number; body: unknown } | Promise<{ status?: number; body: unknown }>;

export const TICKETS: Ticket[] = [
  { id: 101, type: "customer_order", requester: "Tauhid Zaman", subject: "Bulldog tee", sku: "CC-TEE-WHITE", size: "S", qty: 1,
    lease_id: null, invoice_id: 501, notes: "Needs a tee in size S.", created_at: "2026-08-31T09:15:00-04:00",
    status: "open", is_resolved: false, run_in_progress: false },
  { id: 102, type: "rent_notice", requester: "Elm City Properties", subject: "Rent due", sku: null, size: null, qty: null,
    lease_id: 1, invoice_id: null, notes: "Email: shop rent due in 2 days.", created_at: "2026-08-31T11:05:00-04:00",
    status: "open", is_resolved: false, run_in_progress: false },
  { id: 103, type: "price_override", requester: "Yale AI Club", subject: "Bulk hoodie discount", sku: "CC-HOOD-NAVY", size: "M",
    qty: 20, lease_id: null, invoice_id: null, notes: "Student org wants 20 hoodies, size M, asking for a bulk discount.",
    created_at: "2026-08-31T16:55:00-04:00", status: "open", is_resolved: false, run_in_progress: false },
];

export const CASH = { account: "checking", balance: 3400, balance_as_of: "2026-08-31", shop_date: "2026-08-31" };

export const PENDING_RENT: PendingApproval = {
  request_id: "a".repeat(32), run_id: "run-1", ticket_id: 102, prepared_by: "accounting",
  proposed_at: "2026-10-14T15:00:00Z", kind: "rent", ref_id: 1, payee: "Elm City Properties", amount: 2400,
  sufficient_funds: true, balance_before: 3400, balance_after: 1000,
  details: { lease_id: 1, space_name: "Chapel Street shop", for_due_date: "2026-09-02" },
};

let n = 0;
export function ev(partial: Partial<AuditEvent> & { event_type: string }): AuditEvent {
  n += 1;
  return {
    event_id: partial.event_id ?? `ev${String(n).padStart(4, "0")}`,
    timestamp: partial.timestamp ?? new Date(Date.UTC(2026, 9, 14, 15, 0, n)).toISOString(),
    run_id: "run-1", run_type: "ticket_run", ticket_id: 102, agent: null, depth: 0, chain: [], step: null,
    summary: "", data: {}, ...partial,
  };
}

export function mockBackend(routes: Record<string, Handler>) {
  const calls: Call[] = [];
  const fetchMock = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const method = (init?.method ?? "GET").toUpperCase();
    const call: Call = { method, path: url.pathname, query: url.searchParams, body: init?.body ? JSON.parse(String(init.body)) : undefined };
    calls.push(call);
    const handler = routes[`${method} ${url.pathname}`];
    const res = handler ? await handler(call) : { status: 404, body: { detail: `no mock for ${method} ${url.pathname}` } };
    return new Response(JSON.stringify(res.body), { status: res.status ?? 200, headers: { "Content-Type": "application/json" } });
  };
  return { calls, fetchMock };
}

/** Default happy-path routes; tests override what they need. */
export function baseRoutes(): Record<string, Handler> {
  return {
    "GET /api/health": () => ({ body: { status: "ok", mcp_connected: true, model: "gpt-6-luna", model_configured: true, working_db: "campus_customs_new.db", runs_in_progress: [] } }),
    "GET /api/tickets": () => ({ body: { count: 3, tickets: TICKETS } }),
    "GET /api/cash": () => ({ body: CASH }),
    "GET /api/approvals": () => ({ body: { count: 0, approvals: [], decisions: [] } }),
    "GET /api/events": () => ({ body: { total: 0, returned: 0, skipped: 0, order: "oldest_first", events: [] } }),
  };
}
