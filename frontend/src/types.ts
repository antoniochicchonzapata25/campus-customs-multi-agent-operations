// Mirrors the Pydantic models in backend/models.py (API section). Keep in sync.

export type AgentName = "boss" | "inventory" | "accounting" | "facilities" | "customer_service";
export type TicketStatus = "open" | "in_progress" | "awaiting_approval" | "resolved";
export type RunState = "running" | "completed" | "limit_reached" | "error";
export type PaymentKind = "invoice" | "rent" | "purchase_order";

export interface Ticket {
  id: number;
  type: string;
  requester: string;
  subject: string;
  sku: string | null;
  size: string | null;
  qty: number | null;
  lease_id: number | null;
  invoice_id: number | null;
  notes: string | null;
  created_at: string;
  status: TicketStatus;
  is_resolved: boolean;
  run_in_progress: boolean;
}

export interface TicketListResponse {
  count: number;
  tickets: Ticket[];
}

export interface PendingApproval {
  request_id: string;
  run_id: string;
  ticket_id: number | null;
  prepared_by: string | null;
  proposed_at: string;
  kind: PaymentKind;
  ref_id: number;
  payee: string | null;
  amount: number;
  sufficient_funds: boolean;
  balance_before: number;
  balance_after: number;
  details: Record<string, unknown>;
}

export interface ApprovalDecision {
  request_id: string;
  ticket_id: number | null;
  run_id: string;
  decision: "approved" | "declined";
  decided_by: string;
  decided_at: string;
  kind: PaymentKind | null;
  ref_id: number | null;
  amount: number | null;
  reason: string | null;
}

export interface ApprovalsResponse {
  count: number;
  approvals: PendingApproval[];
  decisions: ApprovalDecision[];
}

export interface ApprovalRequestBody {
  request_id: string;
  approve: true;
  approved_by: string;
  approved_amount: number;
}

export interface DeclineRequestBody {
  request_id: string;
  decline: true;
  declined_by: string;
  reason?: string | null;
}

export interface ApprovalResponse {
  status: "paid" | "refused" | "declined";
  request_id: string;
  ticket_id: number | null;
  message: string;
  payment: Record<string, unknown> | null;
  balance_after: number | null;
  ticket_status: string | null;
}

export interface TicketRunResponse {
  ticket_id: number;
  run_id: string | null;
  state: RunState;
  succeeded: boolean;
  resolution_status: string | null;
  summary: string | null;
  ticket_status: string | null;
  delegations: number;
  usage: Record<string, number>;
  pending_approvals: PendingApproval[];
  output: Record<string, unknown> | null;
  error: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface AuditEvent {
  event_id: string;
  timestamp: string;
  run_id: string;
  run_type: string;
  ticket_id: number | null;
  agent: AgentName | null;
  depth: number | null;
  chain: string[];
  step: number | null;
  event_type: string;
  summary: string;
  data: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
}

export interface EventsResponse {
  total: number;
  returned: number;
  skipped: number;
  order: "oldest_first";
  events: AuditEvent[];
}

export interface CashResponse {
  account: string;
  balance: number;
  balance_as_of: string;
  shop_date: string;
}

export interface ResetResponse {
  status: "reset";
  working_db: string;
  original_db: string;
  sha256: string;
  message: string;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  mcp_connected: boolean;
  model: string;
  model_configured: boolean;
  working_db: string;
  runs_in_progress: number[];
}
