// Thin client for the FastAPI backend (backend/main.py). No business logic lives here:
// amounts, payability and ticket status always come from the backend.
import type {
  ApprovalRequestBody, ApprovalResponse, ApprovalsResponse, CashResponse, DeclineRequestBody, EventsResponse,
  HealthResponse, ResetResponse, Ticket, TicketListResponse, TicketRunResponse,
} from "./types";

export const API_BASE: string = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "")
  || "http://localhost:8000";

/** An HTTP error with the most readable message the backend gave us. */
export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

/** The backend returns either {detail: string}, FastAPI's {detail: [{msg, loc}]}, or an ApprovalResponse. */
export function errorMessage(status: number, body: unknown): string {
  if (body && typeof body === "object") {
    const b = body as Record<string, unknown>;
    if (typeof b.message === "string") return b.message;
    if (typeof b.error === "string" && b.error) return b.error;
    if (typeof b.detail === "string") return b.detail;
    if (Array.isArray(b.detail)) {
      return b.detail
        .map((d: { msg?: string; loc?: unknown[] }) => {
          const field = Array.isArray(d.loc) ? d.loc.filter((x) => x !== "body").join(".") : "";
          return field ? `${field}: ${d.msg}` : d.msg;
        })
        .join("; ");
    }
  }
  if (status === 0) return "Cannot reach the backend. Is it running on " + API_BASE + "?";
  return `Request failed (HTTP ${status})`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(API_BASE + path, {
      ...init,
      headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    });
  } catch {
    throw new ApiError(0, errorMessage(0, null), null);
  }
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (!res.ok) throw new ApiError(res.status, errorMessage(res.status, body), body);
  return body as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  health: () => request<HealthResponse>("/api/health"),
  tickets: () => request<TicketListResponse>("/api/tickets"),
  ticket: (id: number) => request<Ticket>(`/api/tickets/${id}`),
  /** Synchronous on the backend: resolves only when the whole run ends. */
  runTicket: (id: number) => post<TicketRunResponse>(`/api/tickets/${id}/run`),
  latestRun: (id: number) => request<TicketRunResponse>(`/api/tickets/${id}/run`),
  events: (params: { limit?: number; ticket_id?: number; run_id?: string; after?: string }) => {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => v !== undefined && q.set(k, String(v)));
    return request<EventsResponse>(`/api/events?${q}`);
  },
  approvals: () => request<ApprovalsResponse>("/api/approvals"),
  approve: (body: ApprovalRequestBody) => post<ApprovalResponse>("/api/approvals", body),
  decline: (body: DeclineRequestBody) => post<ApprovalResponse>("/api/approvals/decline", body),
  cash: () => request<CashResponse>("/api/cash"),
  reset: () => post<ResetResponse>("/api/reset", { confirm: true }),
};
