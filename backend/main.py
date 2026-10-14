"""Campus Customs backend: FastAPI routes for the React desk (Problem 7).

Start from the backend/ folder:
    uvicorn main:app --reload --port 8000

- Shop data and every database write go through the campus-customs MCP server
  (shop.py). The backend has no SQL of its own.
- Agent runs reuse CampusCustomsTeam (team.py) unchanged: same model
  (gpt-6-luna via Portkey), delegation, limits, and audit trail.
- Payments only happen in POST /api/approvals, after a human approves a request
  an agent prepared. Reset only touches the working database.
"""

import asyncio
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Path as PathParam, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

import approvals
from agents import MODEL_NAME, ModelNotConfigured, build_model
from audit import AuditTrail, AuditTrailCorrupt
from db_reset import ResetError, reset_working_db
from models import (
    AuditEvent, ApprovalRequest, ApprovalResponse, CashResponse, DeclineRequest, EventsResponse, HealthResponse,
    PendingApprovalsResponse, ResetRequest, ResetResponse, TicketListResponse, TicketRunResponse, TicketSummary,
)
from shop import ShopClient, ShopToolError, ShopUnavailable

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

# Boss resolution -> ticket status. Prepared payments always wait for a human first.
STATUS_AFTER_RUN = {"resolved": "resolved", "awaiting_human_approval": "in_progress",
                    "blocked": "in_progress", "unresolved": "in_progress"}


@dataclass
class Settings:
    original_db: Path = ROOT / "data" / "campus_customs.db"
    working_db: Path = ROOT / "data" / "campus_customs_new.db"
    audit_path: Path = ROOT / "output" / "audit_trail.json"
    # None = the MCP server's own default (data/campus_customs_new.db). Tests pass a temp copy.
    mcp_db_override: Path | None = None
    frontend_origins: list[str] = field(default_factory=lambda: list(FRONTEND_ORIGINS))


class ApiError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code, self.detail = status_code, detail


class AppState:
    def __init__(self, settings: Settings, team_factory: Callable[[], Any] | None):
        self.settings = settings
        self.audit = AuditTrail(settings.audit_path)
        self.shop = ShopClient(settings.mcp_db_override)
        self._team_factory = team_factory
        self._team = None
        self.running: set[int] = set()
        self.runs: dict[int, TicketRunResponse] = {}
        self.resetting = False

    def team(self):
        if self._team is None:
            if self._team_factory is not None:
                self._team = self._team_factory()
            else:
                from team import CampusCustomsTeam
                self._team = CampusCustomsTeam(audit=self.audit, db_path=self.settings.mcp_db_override)
        return self._team


def create_app(settings: Settings | None = None, team_factory: Callable[[], Any] | None = None) -> FastAPI:
    settings = settings or Settings()
    state = AppState(settings, team_factory)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            await state.shop.connect()
        except ShopUnavailable:
            pass  # routes report 503 and retry the connection on the next call
        yield
        try:
            await asyncio.wait_for(state.shop.close(), timeout=10)
        except (asyncio.TimeoutError, Exception):
            pass  # never hang or crash on shutdown

    app = FastAPI(title="Campus Customs Desk API", version="1.0", lifespan=lifespan)
    app.state.desk = state
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.frontend_origins, allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"], allow_credentials=False,
    )

    # ---------- errors: readable, never a traceback or a secret ----------

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(ShopUnavailable)
    async def _unavailable(_: Request, exc: ShopUnavailable):
        return JSONResponse(status_code=503, content={"detail": "Shop data service (MCP server) is unavailable"})

    @app.exception_handler(ShopToolError)
    async def _tool_error(_: Request, exc: ShopToolError):
        return JSONResponse(status_code=exc.http_status, content={"detail": exc.message})

    @app.exception_handler(AuditTrailCorrupt)
    async def _audit_corrupt(_: Request, exc: AuditTrailCorrupt):
        return JSONResponse(status_code=500, content={"detail": "Audit trail is unreadable; it was not modified"})

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception):
        return JSONResponse(status_code=500, content={"detail": f"Internal error ({type(exc).__name__})"})

    async def get_ticket(ticket_id: int) -> dict:
        return (await state.shop.call("get_tickets", ticket_id=ticket_id))["tickets"][0]

    def summary(t: dict) -> TicketSummary:
        return TicketSummary(**t, is_resolved=t["status"] == "resolved", run_in_progress=t["id"] in state.running)

    # ---------- routes ----------

    @app.get("/api/health", response_model=HealthResponse)
    async def health():
        try:
            await state.shop.connect()
            mcp_ok = True
        except ShopUnavailable:
            mcp_ok = False
        try:
            build_model()
            model_ok = True
        except ModelNotConfigured:
            model_ok = False
        return HealthResponse(status="ok" if mcp_ok and model_ok else "degraded", mcp_connected=mcp_ok,
                              model=MODEL_NAME, model_configured=model_ok,
                              working_db=settings.working_db.name, runs_in_progress=sorted(state.running))

    @app.get("/api/tickets", response_model=TicketListResponse)
    async def list_tickets():
        data = await state.shop.call("get_tickets")
        tickets = [summary(t) for t in data["tickets"]]
        return TicketListResponse(count=len(tickets), tickets=tickets)

    @app.get("/api/tickets/{ticket_id}", response_model=TicketSummary)
    async def ticket_detail(ticket_id: int = PathParam(ge=1)):
        return summary(await get_ticket(ticket_id))

    @app.post("/api/tickets/{ticket_id}/run", response_model=TicketRunResponse,
              responses={409: {"description": "Already running or reset in progress"},
                         502: {"description": "Run failed"}, 503: {"description": "Model or MCP unavailable"}})
    async def run_ticket(ticket_id: int = PathParam(ge=1)):
        await get_ticket(ticket_id)  # 404 for an unknown ticket
        if state.resetting:
            raise ApiError(409, "Database reset in progress")
        if ticket_id in state.running:
            raise ApiError(409, f"Ticket {ticket_id} is already being worked on")
        try:
            team = state.team()
        except ModelNotConfigured:
            raise ApiError(503, f"{MODEL_NAME} is not configured (PORTKEY_API_KEY missing)")

        state.running.add(ticket_id)
        started = datetime.now(timezone.utc)
        state.runs[ticket_id] = TicketRunResponse(ticket_id=ticket_id, run_id=None, state="running",
                                                  succeeded=False, started_at=started)
        try:
            result = await team.run_ticket(ticket_id)
        except Exception as exc:
            response = TicketRunResponse(ticket_id=ticket_id, run_id=None, state="error", succeeded=False,
                                         error=f"Run failed: {type(exc).__name__}", started_at=started,
                                         finished_at=datetime.now(timezone.utc))
            state.runs[ticket_id] = response
            return JSONResponse(status_code=502, content=response.model_dump(mode="json"))
        finally:
            state.running.discard(ticket_id)

        output = result.output or {}
        is_decision = "resolution_status" in output
        succeeded = result.stopped_reason == "completed" and is_decision
        pending = await approvals.list_pending(state.shop, state.audit, run_id=result.run_id)
        ticket_status = None
        if succeeded:
            new_status = "awaiting_approval" if pending else STATUS_AFTER_RUN[output["resolution_status"]]
            ticket_status = await approvals.set_ticket_status(
                state.shop, state.audit, ticket_id, new_status, run_id=result.run_id,
                reason=f"Boss decision: {output['resolution_status']}")
        response = TicketRunResponse(
            ticket_id=ticket_id, run_id=result.run_id, state=result.stopped_reason, succeeded=succeeded,
            resolution_status=output.get("resolution_status"),
            summary=output.get("resolution_reason") or output.get("summary"),
            ticket_status=ticket_status, delegations=result.delegations, usage=result.usage,
            pending_approvals=pending, output=result.output,
            error=result.error or (None if succeeded else "Run did not produce a complete Boss decision"),
            started_at=started, finished_at=datetime.now(timezone.utc),
        )
        state.runs[ticket_id] = response
        if result.stopped_reason == "error":
            return JSONResponse(status_code=502, content=response.model_dump(mode="json"))
        return response

    @app.get("/api/tickets/{ticket_id}/run", response_model=TicketRunResponse)
    async def latest_run(ticket_id: int = PathParam(ge=1)):
        if ticket_id not in state.runs:
            raise ApiError(404, f"No run of ticket {ticket_id} since the server started")
        return state.runs[ticket_id]

    @app.get("/api/events", response_model=EventsResponse)
    async def events(
        limit: int = Query(200, ge=1, le=1000, description="Most recent N matching events, returned oldest first"),
        ticket_id: int | None = Query(None, ge=1),
        run_id: str | None = Query(None, max_length=64),
        agent: str | None = Query(None, max_length=32),
        after: str | None = Query(None, max_length=64, description="Only events after this event_id"),
    ):
        raw = await asyncio.to_thread(state.audit.read)
        parsed, skipped = [], 0
        for item in raw:
            try:
                parsed.append(AuditEvent.model_validate(item))
            except ValidationError:
                skipped += 1
        if after is not None:
            idx = next((i for i, e in enumerate(parsed) if e.event_id == after), None)
            if idx is None:
                raise ApiError(404, "Unknown event id in 'after'")
            parsed = parsed[idx + 1:]
        matched = [e for e in parsed
                   if (ticket_id is None or e.ticket_id == ticket_id) and (run_id is None or e.run_id == run_id)
                   and (agent is None or e.agent == agent)]
        recent = matched[-limit:]
        return EventsResponse(total=len(matched), returned=len(recent), skipped=skipped, events=recent)

    @app.get("/api/approvals", response_model=PendingApprovalsResponse)
    async def pending_approvals(ticket_id: int | None = Query(None, ge=1)):
        items = await approvals.list_pending(state.shop, state.audit, ticket_id=ticket_id)
        decisions = await asyncio.to_thread(approvals.list_decisions, state.audit, ticket_id=ticket_id)
        return PendingApprovalsResponse(count=len(items), approvals=items, decisions=decisions)

    @app.post("/api/approvals", response_model=ApprovalResponse,
              responses={404: {"description": "Unknown request"}, 409: {"description": "Refused by a shop rule"},
                         422: {"description": "Invalid approval"}})
    async def approve(body: ApprovalRequest):
        if state.resetting:
            raise ApiError(409, "Database reset in progress")
        try:
            return await approvals.approve(state.shop, state.audit, body)
        except approvals.ApprovalError as exc:
            return JSONResponse(status_code=exc.status_code, content=ApprovalResponse(
                status="refused", request_id=body.request_id, ticket_id=None, message=exc.message,
            ).model_dump(mode="json"))

    @app.post("/api/approvals/decline", response_model=ApprovalResponse,
              responses={404: {"description": "Unknown request"}, 409: {"description": "Already decided or stale"},
                         422: {"description": "Invalid decline"}})
    async def decline(body: DeclineRequest):
        """A human declines a prepared request. No payment tool is called; nothing financial changes."""
        if state.resetting:
            raise ApiError(409, "Database reset in progress")
        try:
            return await approvals.decline(state.shop, state.audit, body)
        except approvals.ApprovalError as exc:
            return JSONResponse(status_code=exc.status_code, content=ApprovalResponse(
                status="refused", request_id=body.request_id, ticket_id=None, message=exc.message,
            ).model_dump(mode="json"))

    @app.get("/api/cash", response_model=CashResponse)
    async def cash():
        return CashResponse(**await state.shop.call("get_cash_balance", account="checking"))

    @app.post("/api/reset", response_model=ResetResponse)
    async def reset(body: ResetRequest):
        if state.running:
            raise ApiError(409, f"Cannot reset while tickets {sorted(state.running)} are running")
        if state.resetting:
            raise ApiError(409, "A reset is already in progress")
        state.resetting = True
        try:
            new_hash = await asyncio.to_thread(reset_working_db, settings.original_db, settings.working_db)
        except (ResetError, OSError) as exc:
            reason = exc if isinstance(exc, ResetError) else type(exc).__name__
            raise ApiError(500, f"Reset failed; working database left unchanged: {reason}")
        finally:
            state.resetting = False
        state.runs.clear()
        state.audit.log(run_id=uuid.uuid4().hex, run_type="backend", ticket_id=None, agent=None,
                        event_type="database_reset", summary="working database restored from the original",
                        data={"working_db": settings.working_db.name, "original_db": settings.original_db.name,
                              "sha256": new_hash})
        return ResetResponse(status="reset", working_db=settings.working_db.name,
                             original_db=settings.original_db.name, sha256=new_hash,
                             message="Working database restored to the original values")

    return app


app = create_app()
