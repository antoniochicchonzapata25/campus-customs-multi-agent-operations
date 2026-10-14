// Turns real API data into words a non-technical person can follow.
// Nothing here invents facts: every sentence is built from fields of an actual event.
import type { AgentName, AuditEvent, PaymentKind, Ticket, TicketStatus } from "./types";

export const money = (n: number | null | undefined) =>
  n === null || n === undefined || Number.isNaN(n)
    ? "—"
    : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);

export const time = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
};

// ---------- agents ----------

export interface AgentMeta { name: string; role: string; initials: string; cls: string }

export const AGENTS: Record<AgentName, AgentMeta> = {
  boss: { name: "Boss", role: "Routes the ticket and makes the final call", initials: "BO", cls: "agent-boss" },
  inventory: { name: "Inventory", role: "Stock, shortfalls and restocking", initials: "IN", cls: "agent-inventory" },
  accounting: { name: "Accounting", role: "Cash, bills and payment requests", initials: "AC", cls: "agent-accounting" },
  facilities: { name: "Facilities", role: "Lease and rent checks", initials: "FA", cls: "agent-facilities" },
  customer_service: { name: "Customer Service", role: "Drafts customer replies", initials: "CS", cls: "agent-cs" },
};

export const agentName = (a: string | null | undefined) =>
  a && a in AGENTS ? AGENTS[a as AgentName].name : a ? a : "Desk";

// ---------- tickets ----------

export const STATUS: Record<TicketStatus, { label: string; cls: string; hint: string }> = {
  open: { label: "Open", cls: "status-open", hint: "Open: no team run has settled this ticket yet." },
  in_progress: { label: "In progress", cls: "status-progress", hint: "The team ran, but the ticket still needs follow-up." },
  awaiting_approval: { label: "Awaiting approval", cls: "status-approval", hint: "A payment the agents prepared is waiting for a person to approve or decline it." },
  resolved: { label: "Resolved", cls: "status-resolved", hint: "The backend has marked this ticket resolved." },
};

export const statusMeta = (s: string) =>
  STATUS[s as TicketStatus] ?? { label: s, cls: "status-open", hint: "" };

const TYPE_LABEL: Record<string, string> = {
  customer_order: "Customer order",
  rent_notice: "Rent notice",
  price_override: "Price / discount request",
};

export const ticketType = (t: string) => TYPE_LABEL[t] ?? t.replace(/_/g, " ");

/** A one-line description built only from the ticket's own fields. */
export function ticketLine(t: Ticket): string {
  const parts: string[] = [];
  if (t.qty !== null && t.sku) parts.push(`${t.qty} × ${t.sku}${t.size ? `, size ${t.size}` : ""}`);
  if (t.lease_id !== null) parts.push(`lease #${t.lease_id}`);
  if (t.invoice_id !== null) parts.push(`invoice #${t.invoice_id}`);
  return parts.join(" · ");
}

// ---------- payments ----------

export const KIND_LABEL: Record<PaymentKind, string> = {
  invoice: "Vendor invoice",
  rent: "Rent payment",
  purchase_order: "Purchase order (restock)",
};

export const kindLabel = (k: string | null | undefined) => (k && k in KIND_LABEL ? KIND_LABEL[k as PaymentKind] : k ?? "Payment");

// ---------- MCP tools ----------

const TOOL_LABEL: Record<string, string> = {
  get_tickets: "read the ticket",
  get_product_stock_and_price: "checked stock and price",
  get_open_vendor_invoices: "checked unpaid vendor invoices",
  get_lease_rent_status: "checked the lease and rent",
  get_cash_balance: "checked the cash balance",
  list_vendors: "looked up vendors",
  prepare_payment_request: "prepared a payment request",
  record_approved_payment: "recorded an approved payment",
  update_ticket_status: "updated the ticket status",
};

export const toolLabel = (tool: string) => TOOL_LABEL[tool] ?? `used ${tool}`;

/** Short, factual summary of a tool result. Falls back to nothing rather than guessing. */
export function toolResultLine(tool: string, r: any): string { // eslint-disable-line @typescript-eslint/no-explicit-any
  if (!r || typeof r !== "object") return "";
  try {
    switch (tool) {
      case "get_product_stock_and_price": {
        const rs = r.requested_size;
        const base = `${r.name ?? r.sku}`;
        if (rs) {
          const need = rs.qty_needed !== undefined ? `, needed ${rs.qty_needed}, short ${rs.shortfall}` : "";
          return `${base} size ${rs.size}: ${rs.qty_on_hand} on hand${need}`;
        }
        return `${base}: ${r.total_qty_all_sizes} on hand across sizes${r.pricing ? `, cost ${money(r.pricing.unit_cost)} / list ${money(r.pricing.list_price)}` : ""}`;
      }
      case "get_open_vendor_invoices":
        return `${r.open_invoice_count} open invoice(s), ${money(r.total_open_amount)} total` +
          (r.invoices?.length ? ` — e.g. #${r.invoices[0].invoice_id} to ${r.invoices[0].vendor_name}${r.invoices[0].is_overdue ? `, ${r.invoices[0].days_past_due} days overdue` : ""}` : "");
      case "get_lease_rent_status":
        return `${r.space_name}: ${money(r.monthly_rent)} due ${r.next_due} (${r.is_overdue ? "overdue" : `in ${r.days_until_due} days`})`;
      case "get_cash_balance":
        return `Checking balance ${money(r.balance)}`;
      case "list_vendors":
        return (r.vendors ?? []).map((v: any) => `${v.name} (${v.lead_days}d, ${v.can_ship_new_product ? "can ship" : "blocked"})`).join("; "); // eslint-disable-line @typescript-eslint/no-explicit-any
      case "prepare_payment_request":
        return `${kindLabel(r.kind)} to ${r.payee}: ${money(r.amount)} — ${r.sufficient_funds ? "cash covers it" : "NOT enough cash"}; not paid yet`;
      case "get_tickets":
        return r.tickets?.[0] ? `#${r.tickets[0].id} ${r.tickets[0].subject}` : "";
      default:
        return "";
    }
  } catch {
    return "";
  }
}

// ---------- events ----------

export type Tone = "agent" | "delegation" | "tool" | "payment" | "warning" | "error" | "human" | "system";

export interface FeedItem {
  id: string;
  ts: string;
  agent: string | null;
  tone: Tone;
  title: string;
  detail: string;
  technical: boolean; // low-level loop steps: hidden unless the user asks for them
  event: AuditEvent;
}

const clip = (s: unknown, n = 220) => {
  const t = typeof s === "string" ? s : s === undefined || s === null ? "" : JSON.stringify(s);
  return t.length > n ? t.slice(0, n - 1) + "…" : t;
};

export function describe(e: AuditEvent): FeedItem {
  const d = e.data ?? {};
  const who = agentName(e.agent);
  const base = { id: e.event_id, ts: e.timestamp, agent: e.agent, event: e, technical: false };
  switch (e.event_type) {
    case "run_started":
      return { ...base, tone: "system", title: `Team run started (${agentName(d.entry_agent)} leads)`, detail: clip(d.task) };
    case "run_finished": {
      const r = d.stopped_reason as string;
      const tone: Tone = r === "completed" ? "system" : r === "limit_reached" ? "warning" : "error";
      const label = r === "completed" ? "Team run finished" : r === "limit_reached" ? "Team run stopped at a safety limit" : "Team run failed";
      const pending = Array.isArray(d.pending_approvals) ? d.pending_approvals.length : 0;
      return { ...base, tone, title: label, detail: `${d.delegations ?? 0} delegation(s), ${d.usage?.requests ?? "?"} model calls${pending ? `, ${pending} payment request(s) prepared` : ""}${d.error ? ` — ${d.error}` : ""}` };
    }
    case "agent_started":
      return { ...base, tone: "agent", title: `${who} started working`, detail: clip(d.task) };
    case "agent_finished": {
      const o = d.output ?? {};
      const line = o.resolution_reason ?? o.summary ?? "";
      const status = o.resolution_status ?? o.status;
      return { ...base, tone: "agent", title: `${who} finished${status ? ` (${String(status).replace(/_/g, " ")})` : ""}`, detail: clip(line, 400) };
    }
    case "agent_error":
      return { ...base, tone: "error", title: `${who} hit an error`, detail: clip(d.error) };
    case "delegation_request":
      return { ...base, tone: "delegation", title: `${who} asked ${agentName(d.to_agent)} for help`, detail: clip(d.task, 300) };
    case "delegation_result":
      return d.reused
        ? { ...base, tone: "delegation", title: `${who} reused ${agentName(d.to_agent)}'s earlier answer`, detail: clip(d.task) }
        : { ...base, tone: "delegation", title: `${agentName(d.to_agent)} reported back to ${who}`, detail: clip(d.report?.summary ?? d.report?.resolution_reason, 300) };
    case "delegation_refused":
      return { ...base, tone: "warning", title: `Safeguard: ${who} could not hand off to ${agentName(d.to_agent)}`, detail: clip(d.reason) };
    case "mcp_tool_call":
      return { ...base, tone: "tool", technical: true, title: `${who} called ${d.tool}`, detail: clip(d.args) };
    case "mcp_tool_result":
      return { ...base, tone: "tool", title: `${who} ${toolLabel(d.tool)}`, detail: toolResultLine(d.tool, d.result) };
    case "mcp_tool_cache_hit":
      return { ...base, tone: "tool", technical: true, title: `${who} reused an earlier ${d.tool} result`, detail: "" };
    case "mcp_tool_error":
      return { ...base, tone: "warning", title: `${who}: shop data tool refused the request`, detail: clip(d.error) };
    case "payment_proposed": {
      const r = d.request ?? {};
      return { ...base, tone: "payment", title: `${who} prepared a payment request — NOT paid`, detail: `${kindLabel(r.kind)} to ${r.payee}: ${money(r.amount)}. ${d.approval_status === "refused" ? "Cash would not cover it." : "Waiting for a person to approve or decline."}` };
    }
    case "limit_reached":
      return { ...base, tone: "warning", title: "Safeguard: a usage limit stopped further work", detail: clip(e.summary) };
    case "human_approval":
      return { ...base, tone: "human", title: `${d.approved_by} approved a payment — PAID`, detail: `${kindLabel(d.payment?.kind)} to ${d.payment?.payee}: ${money(d.payment?.amount)}; checking now ${money(d.payment?.balance_after)}` };
    case "human_decline":
      return { ...base, tone: "human", title: `${d.declined_by} declined a payment request`, detail: `${money(d.proposed_amount)} not paid${d.reason ? ` — “${d.reason}”` : ""}` };
    case "approval_refused":
      return { ...base, tone: "warning", title: `Approval refused by the shop's safeguards`, detail: clip(d.reason) };
    case "ticket_status_changed":
      return { ...base, tone: "system", title: `Ticket status: ${statusMeta(d.previous_status).label} → ${statusMeta(d.status).label}`, detail: clip(d.reason) };
    case "database_reset":
      return { ...base, tone: "system", title: "Working database reset to the original", detail: "" };
    case "loop_step":
      return describeLoopStep(e, base, who);
    default:
      return { ...base, tone: "system", technical: true, title: e.event_type.replace(/_/g, " "), detail: clip(e.summary) };
  }
}

function describeLoopStep(e: AuditEvent, base: Omit<FeedItem, "tone" | "title" | "detail">, who: string): FeedItem {
  const d = e.data ?? {};
  if (d.node === "model_response") {
    const parts: any[] = d.parts ?? []; // eslint-disable-line @typescript-eslint/no-explicit-any
    const text = parts.filter((p) => p.kind === "text").map((p) => p.content).join(" ");
    const calls = parts.filter((p) => p.kind === "tool-call").map((p) => p.tool);
    if (text) return { ...base, tone: "agent", technical: false, title: `${who} said`, detail: clip(text, 400) };
    return { ...base, tone: "agent", technical: true, title: `${who} decided next step`, detail: calls.length ? `calls: ${calls.join(", ")}` : "" };
  }
  return { ...base, tone: "agent", technical: true, title: `${who} loop step ${e.step ?? ""}`.trim(), detail: String(d.node ?? "") };
}

/** Merge new events into a list: no duplicates (by event_id), oldest first. */
export function mergeEvents(current: AuditEvent[], incoming: AuditEvent[]): AuditEvent[] {
  if (!incoming.length) return current;
  const seen = new Set(current.map((e) => e.event_id));
  const fresh = incoming.filter((e) => !seen.has(e.event_id) && seen.add(e.event_id));
  if (!fresh.length) return current;
  return [...current, ...fresh].sort((a, b) => a.timestamp.localeCompare(b.timestamp));
}

export interface AgentContribution {
  agent: AgentName;
  summary: string;
  status: string | null;
  toolsUsed: number;
  handoffs: number;
}

/** Per-agent summary for one run, taken from that run's agent_finished outputs and counted events. */
export function contributions(events: AuditEvent[], runId: string | null): AgentContribution[] {
  if (!runId) return [];
  const out = new Map<AgentName, AgentContribution>();
  for (const e of events) {
    if (e.run_id !== runId || !e.agent) continue;
    const c = out.get(e.agent) ?? { agent: e.agent, summary: "", status: null, toolsUsed: 0, handoffs: 0 };
    if (e.event_type === "mcp_tool_result") c.toolsUsed += 1;
    if (e.event_type === "delegation_request") c.handoffs += 1;
    if (e.event_type === "agent_finished") {
      const o = e.data?.output ?? {};
      c.summary = String(o.resolution_reason ?? o.summary ?? "");
      c.status = (o.resolution_status ?? o.status ?? null) as string | null;
    }
    out.set(e.agent, c);
  }
  const order: AgentName[] = ["boss", "inventory", "accounting", "facilities", "customer_service"];
  return order.filter((a) => out.has(a)).map((a) => out.get(a)!);
}

/** The newest run on this ticket that has a run_started event (agent runs, not human actions). */
export function latestRunId(events: AuditEvent[]): string | null {
  for (let i = events.length - 1; i >= 0; i--) if (events[i].event_type === "run_started") return events[i].run_id;
  return null;
}

const AGENT_WORDS = new Set(["boss", "inventory", "accounting", "facilities", "customer service", "customer_service", "agent"]);

/** Friendly pre-check only; the backend is the real gate. */
export function approverProblem(name: string): string | null {
  const n = name.trim();
  if (n.length < 2) return "Enter your name (at least 2 characters).";
  if (AGENT_WORDS.has(n.toLowerCase())) return "Use your own name — agents cannot approve or decline.";
  return null;
}
