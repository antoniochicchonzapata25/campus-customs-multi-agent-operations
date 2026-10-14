"""Data types shared by the Campus Customs agent team.

Agents talk to each other through these models: a specialist always hands back
a SpecialistReport, the Boss hands back a BossDecision, and every agent-loop
step is written to output/audit_trail.json as an AuditEvent.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, NonNegativeFloat, PositiveInt, field_validator

AgentName = Literal["boss", "inventory", "accounting", "facilities", "customer_service"]
AGENT_NAMES: tuple[AgentName, ...] = ("boss", "inventory", "accounting", "facilities", "customer_service")

PaymentKind = Literal["invoice", "rent", "purchase_order"]
ApprovalStatus = Literal["not_required", "pending_human_approval", "approved", "rejected", "refused"]
ReportStatus = Literal["complete", "blocked", "needs_human", "incomplete"]
ResolutionStatus = Literal["resolved", "awaiting_human_approval", "blocked", "unresolved"]


# ---------- ticket context ----------

class TicketContext(BaseModel):
    """One row of `tickets`, as returned by the get_tickets MCP tool."""

    id: int
    type: str
    requester: str
    subject: str
    sku: str | None = None
    size: str | None = None
    qty: int | None = None
    lease_id: int | None = None
    invoice_id: int | None = None
    status: str
    notes: str | None = None
    created_at: str


# ---------- agent-to-agent messages ----------

class DelegationRequest(BaseModel):
    """One agent asking another for help (validated before the target runs)."""

    from_agent: AgentName
    to_agent: AgentName
    task: str = Field(min_length=10, max_length=2000)
    ticket_id: int | None = None
    depth: int = Field(ge=0)


class Finding(BaseModel):
    """A fact an agent established, with where it came from."""

    fact: str
    source: str = Field(description="MCP tool name or agent the fact came from")
    verified: bool = Field(description="True only if it came straight from a tool result")


class ProposedAction(BaseModel):
    """Something an agent wants done. Money actions always wait for a human."""

    action_type: Literal["payment", "purchase_order", "customer_message", "restock", "discount", "other"]
    description: str
    kind: PaymentKind | None = None
    ref_id: int | None = None
    payee: str | None = None
    amount: NonNegativeFloat | None = None
    sku: str | None = None
    size: str | None = None
    qty: PositiveInt | None = None
    requires_human_approval: bool = True
    approval_status: ApprovalStatus = "pending_human_approval"


class CustomerMessageDraft(BaseModel):
    """A reply for a human to review. It is never sent by the agents."""

    to: str
    subject: str
    body: str
    facts_used: list[str] = Field(default_factory=list)
    is_draft: Literal[True] = True


class SpecialistReport(BaseModel):
    """What Inventory, Accounting, Facilities, and Customer Service hand back."""

    agent: AgentName
    status: ReportStatus
    summary: str
    findings: list[Finding] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    proposed_actions: list[ProposedAction] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    customer_draft: CustomerMessageDraft | None = None


class BossDecision(BaseModel):
    """The Boss's final call on a ticket."""

    ticket_id: int | None
    problem: str
    first_specialist: AgentName | None = None
    first_specialist_reason: str = ""
    delegation_path: list[str] = Field(default_factory=list, description="e.g. ['boss->inventory', 'inventory->accounting']")
    findings: list[Finding] = Field(default_factory=list)
    proposed_actions: list[ProposedAction] = Field(default_factory=list)
    human_approvals_needed: list[ProposedAction] = Field(default_factory=list)
    customer_message: CustomerMessageDraft | None = None
    resolution_status: ResolutionStatus
    resolution_reason: str
    unresolved_issues: list[str] = Field(default_factory=list)


# ---------- run control ----------

class RunLimits(BaseModel):
    """Caps that keep a ticket run bounded in loops, delegations, and tokens."""

    max_delegation_depth: int = Field(3, ge=0, description="Boss is depth 0")
    max_delegations_per_run: int = Field(8, ge=0)
    max_steps_per_agent: int = Field(8, ge=1, description="Model requests one agent may make in one run")
    max_tool_calls_per_agent: int = Field(10, ge=1)
    max_identical_tool_calls: int = Field(2, ge=1, description="Same tool + same args before it is refused")
    team_request_limit: int = Field(40, ge=1, description="Model requests across all agents in a run")
    team_tool_calls_limit: int = Field(60, ge=1)
    team_total_tokens_limit: int = Field(250_000, ge=1000)


class PaymentRequestRecord(BaseModel):
    """A payment prepared by the prepare_payment_request MCP tool during a run.

    Captured from the real tool result (not from what an agent says), so the
    backend's approval route has a trustworthy list of what awaits a human.
    """

    run_id: str
    ticket_id: int | None
    prepared_by: AgentName
    request: dict[str, Any]
    approval_status: ApprovalStatus


class TeamRunResult(BaseModel):
    run_id: str
    run_type: str
    ticket_id: int | None
    entry_agent: AgentName
    output: dict[str, Any] | None
    stopped_reason: Literal["completed", "limit_reached", "error"]
    error: str | None = None
    delegations: int
    usage: dict[str, Any]
    payment_requests: list[PaymentRequestRecord] = Field(default_factory=list)


# ---------- audit ----------

AuditEventType = Literal[
    "run_started",
    "run_finished",
    "agent_started",
    "agent_finished",
    "agent_error",
    "loop_step",
    "mcp_tool_call",
    "mcp_tool_result",
    "mcp_tool_error",
    "mcp_tool_cache_hit",
    "delegation_request",
    "delegation_result",
    "delegation_refused",
    "payment_proposed",
    "limit_reached",
    # backend (human / API) actions, added in Problem 7
    "human_approval",
    "human_decline",
    "approval_refused",
    "ticket_status_changed",
    "database_reset",
]


class AuditEvent(BaseModel):
    """One line of output/audit_trail.json."""

    event_id: str
    timestamp: datetime
    run_id: str
    run_type: str
    ticket_id: int | None
    agent: AgentName | None
    depth: int | None = None
    chain: list[str] = Field(default_factory=list)
    step: int | None = None
    event_type: AuditEventType
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)


# ---------- API (backend/main.py) ----------

TicketStatus = Literal["open", "in_progress", "awaiting_approval", "resolved"]
RunState = Literal["running", "completed", "limit_reached", "error"]


class TicketSummary(BaseModel):
    """One ticket as the dashboard sees it (read through MCP get_tickets)."""

    id: int
    type: str
    requester: str
    subject: str
    sku: str | None = None
    size: str | None = None
    qty: int | None = None
    lease_id: int | None = None
    invoice_id: int | None = None
    notes: str | None = None
    created_at: str
    status: TicketStatus
    is_resolved: bool
    run_in_progress: bool = False


class TicketListResponse(BaseModel):
    count: int
    tickets: list[TicketSummary]


class PendingApproval(BaseModel):
    """A payment an agent prepared that still waits for a human.

    `request_id` is the audit event id of the `payment_proposed` event, so the
    request itself always comes from a real MCP tool result, never from the client.
    `current` is the same request re-priced from the database right now.
    """

    request_id: str
    run_id: str
    ticket_id: int | None
    prepared_by: str | None
    proposed_at: datetime
    kind: PaymentKind
    ref_id: int
    payee: str | None
    amount: float
    sufficient_funds: bool
    balance_before: float
    balance_after: float
    details: dict[str, Any] = Field(default_factory=dict)


class ApprovalDecision(BaseModel):
    """A human decision on a prepared request (since the last reset), from the audit trail."""

    request_id: str
    ticket_id: int | None
    run_id: str
    decision: Literal["approved", "declined"]
    decided_by: str
    decided_at: datetime
    kind: PaymentKind | None = None
    ref_id: int | None = None
    amount: float | None = None
    reason: str | None = None


class PendingApprovalsResponse(BaseModel):
    count: int
    approvals: list[PendingApproval]
    decisions: list[ApprovalDecision] = Field(default_factory=list, description="Approved/declined requests, newest last")


class ApprovalRequest(BaseModel):
    """The human's explicit approval of one prepared request."""

    request_id: str = Field(min_length=8, max_length=64)
    approve: Literal[True] = Field(description="Must be true: an explicit approval action")
    approved_by: str = Field(min_length=2, max_length=80, description="Name of the person approving")
    approved_amount: float = Field(gt=0, description="The amount the human saw; must equal the database amount")


def _human_name(value: str) -> str:
    name = value.strip()
    if len(name) < 2 or name.lower() in {a.replace("_", " ") for a in AGENT_NAMES} | set(AGENT_NAMES) | {"agent"}:
        raise ValueError("must name the human making the decision, not an agent")
    return name


class DeclineRequest(BaseModel):
    """The human's explicit decision NOT to pay one prepared request."""

    request_id: str = Field(min_length=8, max_length=64)
    decline: Literal[True] = Field(description="Must be true: an explicit decline action")
    declined_by: str = Field(min_length=2, max_length=80, description="Name of the person declining")
    reason: str | None = Field(None, max_length=500)

    @field_validator("declined_by")
    @classmethod
    def _declined_by_is_human(cls, v: str) -> str:
        return _human_name(v)


class ApprovalResponse(BaseModel):
    status: Literal["paid", "refused", "declined"]
    request_id: str
    ticket_id: int | None
    message: str
    payment: dict[str, Any] | None = None
    balance_after: float | None = None
    ticket_status: str | None = None


class TicketRunResponse(BaseModel):
    ticket_id: int
    run_id: str | None
    state: RunState
    succeeded: bool
    resolution_status: str | None = None
    summary: str | None = None
    ticket_status: str | None = None
    delegations: int = 0
    usage: dict[str, Any] = Field(default_factory=dict)
    pending_approvals: list[PendingApproval] = Field(default_factory=list)
    output: dict[str, Any] | None = None
    error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


class EventsResponse(BaseModel):
    total: int = Field(description="Events in the trail that match the filters")
    returned: int
    skipped: int = Field(0, description="Entries in the file that do not match the AuditEvent schema")
    order: Literal["oldest_first"] = "oldest_first"
    events: list[AuditEvent]


class CashResponse(BaseModel):
    account: str
    balance: float
    balance_as_of: str
    shop_date: str


class ResetRequest(BaseModel):
    confirm: Literal[True] = Field(description="Must be true to reset the working database")


class ResetResponse(BaseModel):
    status: Literal["reset"]
    working_db: str
    original_db: str
    sha256: str
    message: str


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    mcp_connected: bool
    model: str
    model_configured: bool
    working_db: str
    runs_in_progress: list[int]
