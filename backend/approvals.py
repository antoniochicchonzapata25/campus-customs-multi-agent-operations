"""Human approval of payments the agents prepared.

- Pending requests come from `payment_proposed` events in the append-only audit
  trail. Those events hold the real result of the MCP `prepare_payment_request`
  tool, so the client can only point at a request (by its event id). It can
  never describe a payment of its own.
- Every pending request is re-priced through MCP against the current database
  before it is shown or paid, and stale ones are dropped: an invoice already
  paid, rent for a month already paid, or a vendor blocked again.
- Paying goes through the MCP `record_approved_payment` tool, which recomputes
  the amount, refuses a mismatch or insufficient cash, and writes `payments`,
  `cash_accounts`, and the invoice or lease in one transaction.
- A human can also decline a request (`human_decline`). That calls no payment
  tool, so no money, invoice, lease, or inventory changes; the request simply
  stops being pending. A ticket with a declined request is never auto-resolved.
- Every approval, refusal, or decline is appended to the audit trail.
"""

import asyncio
import uuid
from datetime import datetime

from audit import AuditTrail
from models import ApprovalDecision, ApprovalRequest, ApprovalResponse, AuditEvent, DeclineRequest, PendingApproval
from shop import ShopClient, ShopToolError

_approval_lock = asyncio.Lock()


class ApprovalError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _key(request: dict) -> tuple:
    d = request.get("details") or {}
    return (request.get("kind"), request.get("ref_id"), d.get("sku"), d.get("size"), d.get("qty"), d.get("for_due_date"))


def _tool_args(request: dict) -> dict:
    d = request.get("details") or {}
    args = {"kind": request["kind"], "ref_id": request["ref_id"], "account": request.get("account", "checking")}
    if request["kind"] == "purchase_order":
        args.update(sku=d.get("sku"), size=d.get("size"), qty=d.get("qty"))
    return args


def _events(audit: AuditTrail) -> list[AuditEvent]:
    return [AuditEvent.model_validate(e) for e in audit.read()]


DECISION_EVENTS = {"human_approval": "approved", "human_decline": "declined"}


def _since_last_reset(events: list[AuditEvent]) -> list[AuditEvent]:
    """A database reset invalidates every request and decision before it."""
    last_reset = max((i for i, e in enumerate(events) if e.event_type == "database_reset"), default=-1)
    return events[last_reset + 1:]


def _open_proposals(events: list[AuditEvent]) -> list[AuditEvent]:
    """Latest proposal per distinct request that no human has approved or declined since."""
    events = _since_last_reset(events)
    decided_at: dict[tuple, datetime] = {}
    decided_ids: set[str] = set()
    for e in events:
        if e.event_type in DECISION_EVENTS:
            decided_ids.add(e.data.get("request_id"))
            decided_at[tuple(e.data.get("request_key") or ())] = e.timestamp
    latest: dict[tuple, AuditEvent] = {}
    for e in events:
        if e.event_type != "payment_proposed" or e.event_id in decided_ids:
            continue
        key = _key(e.data.get("request") or {})
        if key in decided_at and decided_at[key] >= e.timestamp:
            continue  # an older copy of a request a human already decided
        latest[key] = e
    return list(latest.values())


def _decision_for(events: list[AuditEvent], request_id: str) -> AuditEvent | None:
    return next((e for e in events if e.event_type in DECISION_EVENTS and e.data.get("request_id") == request_id), None)


def list_decisions(audit: AuditTrail, *, ticket_id: int | None = None) -> list[ApprovalDecision]:
    """Approved and declined requests since the last reset, oldest first."""
    out = []
    for e in _since_last_reset(_events(audit)):
        if e.event_type not in DECISION_EVENTS or (ticket_id is not None and e.ticket_id != ticket_id):
            continue
        key = e.data.get("request_key") or [None, None]
        payment = e.data.get("payment") or {}
        out.append(ApprovalDecision(
            request_id=e.data.get("request_id"), ticket_id=e.ticket_id, run_id=e.run_id,
            decision=DECISION_EVENTS[e.event_type],
            decided_by=e.data.get("approved_by") or e.data.get("declined_by") or "",
            decided_at=e.timestamp, kind=key[0], ref_id=key[1],
            amount=payment.get("amount", e.data.get("proposed_amount")), reason=e.data.get("reason"),
        ))
    return out


async def _revalidate(shop: ShopClient, event: AuditEvent) -> PendingApproval | None:
    request = event.data["request"]
    try:
        current = await shop.call("prepare_payment_request", **_tool_args(request))
    except ShopToolError:
        return None  # no longer payable (already paid, vendor blocked, record gone)
    if request["kind"] == "rent" and current["details"].get("for_due_date") != request["details"].get("for_due_date"):
        return None  # that month's rent has already been paid
    return PendingApproval(
        request_id=event.event_id, run_id=event.run_id, ticket_id=event.ticket_id, prepared_by=event.agent,
        proposed_at=event.timestamp, kind=current["kind"], ref_id=current["ref_id"], payee=current.get("payee"),
        amount=current["amount"], sufficient_funds=current["sufficient_funds"],
        balance_before=current["balance_before"], balance_after=current["balance_after"],
        details=current.get("details") or {},
    )


async def list_pending(shop: ShopClient, audit: AuditTrail, *, ticket_id: int | None = None,
                       run_id: str | None = None) -> list[PendingApproval]:
    proposals = [e for e in _open_proposals(_events(audit))
                 if (ticket_id is None or e.ticket_id == ticket_id) and (run_id is None or e.run_id == run_id)]
    out = []
    for e in proposals:
        p = await _revalidate(shop, e)
        if p is not None:
            out.append(p)
    return out


async def approve(shop: ShopClient, audit: AuditTrail, body: ApprovalRequest) -> ApprovalResponse:
    async with _approval_lock:  # one approval at a time: no double spend
        events = _events(audit)
        proposal = next((e for e in events if e.event_type == "payment_proposed" and e.event_id == body.request_id), None)
        if proposal is None:
            raise ApprovalError(404, "No prepared payment request with that id")
        decided = _decision_for(events, body.request_id)
        if decided is not None:
            raise ApprovalError(409, f"This request was already {DECISION_EVENTS[decided.event_type]}")
        if proposal not in _open_proposals(events):
            raise ApprovalError(409, "This request is no longer current (a newer request exists, it was already paid, "
                                     "or the database was reset); refresh the list")

        request = proposal.data["request"]
        args = _tool_args(request) | {"approved_amount": body.approved_amount, "approved_by": body.approved_by.strip()}
        if request["kind"] == "rent":
            args["for_due_date"] = request["details"].get("for_due_date")

        def log(event_type: str, summary: str, data: dict) -> None:
            audit.log(run_id=proposal.run_id, run_type="human_action", ticket_id=proposal.ticket_id, agent=None,
                      event_type=event_type, summary=summary,
                      data={"request_id": body.request_id, "request_key": list(_key(request)),
                            "approved_by": body.approved_by.strip(), **data})

        try:
            payment = await shop.call("record_approved_payment", **args)
        except ShopToolError as exc:
            log("approval_refused", f"Approval refused: {exc.message}",
                {"approved_amount": body.approved_amount, "reason": exc.message, "approval_status": "refused"})
            raise ApprovalError(exc.http_status, exc.message) from exc

        log("human_approval",
            f"{body.approved_by.strip()} approved {payment['kind']} {payment['ref_id']} for {payment['amount']}",
            {"payment": payment, "approval_status": "approved", "executed": True})

        ticket_status = await _maybe_resolve_ticket(shop, audit, proposal)
        return ApprovalResponse(
            status="paid", request_id=body.request_id, ticket_id=proposal.ticket_id,
            message=f"Paid {payment['amount']:.2f} to {payment['payee']}", payment=payment,
            balance_after=payment["balance_after"], ticket_status=ticket_status,
        )


async def decline(shop: ShopClient, audit: AuditTrail, body: DeclineRequest) -> ApprovalResponse:
    """Record a human's decision not to pay. Calls no payment tool: nothing financial changes."""
    async with _approval_lock:  # serialized with approvals, so a request can't be both
        events = _events(audit)
        proposal = next((e for e in events if e.event_type == "payment_proposed" and e.event_id == body.request_id), None)
        if proposal is None:
            raise ApprovalError(404, "No prepared payment request with that id")
        decided = _decision_for(events, body.request_id)
        if decided is not None:
            raise ApprovalError(409, f"This request was already {DECISION_EVENTS[decided.event_type]}")
        if proposal not in _open_proposals(events):
            raise ApprovalError(409, "This request is no longer current (a newer request exists, it was already paid, "
                                     "or the database was reset); refresh the list")

        request = proposal.data["request"]
        audit.log(run_id=proposal.run_id, run_type="human_action", ticket_id=proposal.ticket_id, agent=None,
                  event_type="human_decline",
                  summary=f"{body.declined_by} declined {request['kind']} {request['ref_id']} "
                          f"({request.get('amount')} to {request.get('payee')})",
                  data={"request_id": body.request_id, "request_key": list(_key(request)),
                        "declined_by": body.declined_by, "decision": "declined", "approval_status": "rejected",
                        "reason": body.reason, "proposed_amount": request.get("amount"), "executed": False})

        ticket_status = await _maybe_resolve_ticket(shop, audit, proposal)
        return ApprovalResponse(
            status="declined", request_id=body.request_id, ticket_id=proposal.ticket_id,
            message=f"Declined {request['kind']} {request['ref_id']}; no payment was made",
            ticket_status=ticket_status,
        )


async def _maybe_resolve_ticket(shop: ShopClient, audit: AuditTrail, proposal: AuditEvent) -> str | None:
    """Once none of a ticket's requests are pending, settle its status.

    All of that run's requests approved -> resolved. Any declined -> in_progress:
    the ticket still needs a human or a new agent run to decide what to do next.
    """
    if proposal.ticket_id is None:
        return None
    ticket = (await shop.call("get_tickets", ticket_id=proposal.ticket_id))["tickets"][0]
    if ticket["status"] != "awaiting_approval":
        return ticket["status"]
    if await list_pending(shop, audit, ticket_id=proposal.ticket_id):
        return ticket["status"]
    run_declines = [d for d in list_decisions(audit, ticket_id=proposal.ticket_id)
                    if d.decision == "declined" and d.run_id == proposal.run_id]
    if run_declines:
        return await set_ticket_status(shop, audit, proposal.ticket_id, "in_progress", run_id=proposal.run_id,
                                       reason="a prepared payment was declined by a human; needs follow-up")
    return await set_ticket_status(shop, audit, proposal.ticket_id, "resolved", run_id=proposal.run_id,
                                   reason="all prepared payments approved")


async def set_ticket_status(shop: ShopClient, audit: AuditTrail, ticket_id: int, status: str, *,
                            run_id: str | None, reason: str) -> str:
    result = await shop.call("update_ticket_status", ticket_id=ticket_id, status=status)
    if result["previous_status"] != status:
        audit.log(run_id=run_id or uuid.uuid4().hex, run_type="human_action" if "human" in reason or "approved" in reason else "ticket_run",
                  ticket_id=ticket_id, agent=None, event_type="ticket_status_changed",
                  summary=f"ticket {ticket_id}: {result['previous_status']} -> {status} ({reason})",
                  data={**result, "reason": reason})
    return status
