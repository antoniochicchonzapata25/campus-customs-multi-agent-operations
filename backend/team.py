"""Agent loops and delegation for the Campus Customs team.

- Every agent has a `delegate_to(agent, task)` tool, so any agent can hand work
  to any other (full connectivity). The delegated agent runs its own loop and
  its report comes back as the tool result, so the caller continues with it.
- Delegation is bounded: no self-delegation, no cycles (A -> B -> A), a depth
  cap, a per-run delegation cap, and repeated identical requests return the
  earlier report instead of running again.
- All agents in one run share one usage counter, so request, tool-call, and
  token caps apply to the whole team. Each agent also has its own cap on loop
  steps and tool calls.
- Each agent loop is driven node by node with `Agent.iter`, and each step is
  appended to output/audit_trail.json while it happens. MCP tool calls are
  audited (and de-duplicated) in `process_tool_call`.
"""

import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.mcp import CallToolFunc, MCPToolset
from pydantic_ai.models import Model
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import RunUsage, UsageLimits

from agents import AGENT_DESCRIPTIONS, AGENT_OUTPUT_TYPES, AGENT_TOOLS, build_mcp_toolset, build_model, load_prompt
from audit import AuditTrail
from models import (
    AGENT_NAMES,
    AgentName,
    DelegationRequest,
    PaymentRequestRecord,
    RunLimits,
    TeamRunResult,
    TicketContext,
)


@dataclass
class TeamRun:
    """State shared by every agent working on one run (one ticket)."""

    run_id: str
    run_type: str
    ticket_id: int | None
    limits: RunLimits
    audit: AuditTrail
    ticket: TicketContext | None = None
    usage: RunUsage = field(default_factory=RunUsage)
    delegations: int = 0
    delegation_cache: dict[tuple[str, str, str], dict] = field(default_factory=dict)
    tool_cache: dict[str, Any] = field(default_factory=dict)
    tool_call_counts: dict[str, int] = field(default_factory=dict)
    payment_requests: list[PaymentRequestRecord] = field(default_factory=list)
    limit_hit: bool = False

    def log(self, agent: str | None, event_type: str, summary: str, data: dict | None = None, *,
            depth: int | None = None, chain: list[str] | None = None, step: int | None = None) -> None:
        self.audit.log(
            run_id=self.run_id, run_type=self.run_type, ticket_id=self.ticket_id, agent=agent,
            event_type=event_type, summary=summary, data=data, depth=depth, chain=chain, step=step,
        )

    def usage_limits(self) -> UsageLimits:
        return UsageLimits(
            request_limit=self.limits.team_request_limit,
            tool_calls_limit=self.limits.team_tool_calls_limit,
            total_tokens_limit=self.limits.team_total_tokens_limit,
        )

    def usage_summary(self) -> dict:
        u = self.usage
        return {"requests": u.requests, "tool_calls": u.tool_calls, "input_tokens": u.input_tokens,
                "output_tokens": u.output_tokens, "total_tokens": u.total_tokens}


@dataclass
class AgentDeps:
    """Per-agent-run dependencies: who is running, how deep, and the shared run."""

    team: "CampusCustomsTeam"
    run: TeamRun
    agent_name: AgentName
    depth: int
    chain: list[str]
    tool_calls: int = 0

    def log(self, event_type: str, summary: str, data: dict | None = None, step: int | None = None) -> None:
        self.run.log(self.agent_name, event_type, summary, data, depth=self.depth, chain=self.chain, step=step)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        return str(value)


# ---------- delegation tool (given to every agent) ----------

async def delegate_to(ctx: RunContext[AgentDeps], agent: AgentName, task: str) -> dict:
    """Ask another Campus Customs agent to do part of this ticket and wait for its report.

    Args:
        agent: Who to ask: boss, inventory, accounting, facilities, or customer_service.
        task: A specific request with the ids, SKU/size/qty, or amounts they need,
            and exactly what you want back.

    Returns the other agent's structured report (or a refusal explaining which
    limit stopped the delegation). Do not re-send a task you already got a report for.
    """
    return await ctx.deps.team.delegate(ctx.deps, agent, task)


def _run_context_instructions(ctx: RunContext[AgentDeps]) -> str:
    """Per-run instructions: the ticket, the chain so far, and what limits remain."""
    d = ctx.deps
    limits = d.run.limits
    can_go_deeper = d.depth < limits.max_delegation_depth
    left = max(limits.max_delegations_per_run - d.run.delegations, 0)
    targets = [a for a in AGENT_NAMES if a not in d.chain]
    if not can_go_deeper:
        delegation_line = "You are at the maximum delegation depth: do not delegate; answer with what you can verify."
    elif left == 0:
        delegation_line = "No delegations are left in this run: answer with what you can verify."
    else:
        delegation_line = (
            f"You may delegate to: {', '.join(f'{a} ({AGENT_DESCRIPTIONS[a]})' for a in targets) or 'nobody'}. "
            f"Delegations left in this run: {left}. Agents already in the chain cannot be called again "
            "(that would be a loop); return your report instead."
        )
    ticket = d.run.ticket.model_dump_json(indent=2) if d.run.ticket else "No ticket is attached to this run."
    return (
        "## Run context\n"
        f"- You are: {d.agent_name}. Delegation chain: {' -> '.join(d.chain)} (depth {d.depth} of max {limits.max_delegation_depth}).\n"
        f"- {delegation_line}\n"
        f"- Your MCP tools: {', '.join(sorted(AGENT_TOOLS[d.agent_name]))}. "
        f"You have at most {limits.max_tool_calls_per_agent} tool calls and {limits.max_steps_per_agent} model steps.\n"
        f"- Ticket record from get_tickets:\n```json\n{ticket}\n```"
    )


# ---------- the team ----------

class CampusCustomsTeam:
    """Builds the five agents around one MCP connection and runs them."""

    def __init__(
        self,
        model: Model | None = None,
        *,
        audit: AuditTrail | None = None,
        limits: RunLimits | None = None,
        db_path: Path | None = None,
        mcp_toolset: MCPToolset | None = None,
    ):
        self.model = model if model is not None else build_model()
        self.audit = audit or AuditTrail()
        self.limits = limits or RunLimits()
        self.mcp = mcp_toolset or build_mcp_toolset(self._process_tool_call, db_path=db_path)
        delegation = FunctionToolset([delegate_to], max_retries=1)
        self.agents: dict[AgentName, Agent[AgentDeps, Any]] = {}
        for name in AGENT_NAMES:
            allowed = AGENT_TOOLS[name]
            self.agents[name] = Agent(
                self.model,
                name=name,
                deps_type=AgentDeps,
                output_type=AGENT_OUTPUT_TYPES[name],
                instructions=[load_prompt(name), _run_context_instructions],
                toolsets=[
                    self.mcp.filtered(lambda ctx, td, allowed=allowed: td.name in allowed),
                    delegation,
                ],
                retries=2,
            )

    # ----- MCP calls: audit, per-agent caps, de-duplication -----

    async def _process_tool_call(self, ctx: RunContext[AgentDeps], call_tool: CallToolFunc, name: str, args: dict) -> Any:
        deps = ctx.deps
        run = deps.run
        limits = run.limits
        deps.tool_calls += 1
        key = f"{name}:{json.dumps(args, sort_keys=True)}"
        if deps.tool_calls > limits.max_tool_calls_per_agent:
            run.limit_hit = True
            deps.log("limit_reached", f"{deps.agent_name} hit its tool-call cap ({limits.max_tool_calls_per_agent})",
                     {"tool": name, "args": args})
            return {"error": "Tool-call limit reached for this agent. Stop calling tools and report what you have."}

        run.tool_call_counts[key] = run.tool_call_counts.get(key, 0) + 1
        if key in run.tool_cache:
            if run.tool_call_counts[key] > limits.max_identical_tool_calls + 1:
                deps.log("limit_reached", f"Repeated identical call to {name} refused", {"tool": name, "args": args})
                return {"error": f"{name} was already called with these arguments; use the earlier result."}
            deps.log("mcp_tool_cache_hit", f"{name} already called with same args this run; reused result",
                     {"tool": name, "args": args, "result": run.tool_cache[key]})
            return run.tool_cache[key]

        deps.log("mcp_tool_call", f"{deps.agent_name} -> MCP {name}", {"tool": name, "args": args})
        try:
            result = await call_tool(name, args)
        except Exception as exc:
            deps.log("mcp_tool_error", f"MCP {name} failed: {exc}", {"tool": name, "args": args, "error": str(exc)})
            raise
        result = _jsonable(result)
        run.tool_cache[key] = result
        deps.log("mcp_tool_result", f"MCP {name} returned", {"tool": name, "args": args, "result": result})

        if name == "prepare_payment_request" and isinstance(result, dict):
            status = "pending_human_approval" if result.get("sufficient_funds") else "refused"
            run.payment_requests.append(PaymentRequestRecord(
                run_id=run.run_id, ticket_id=run.ticket_id, prepared_by=deps.agent_name,
                request=result, approval_status=status,
            ))
            deps.log("payment_proposed",
                     f"{result.get('kind')} {result.get('ref_id')} to {result.get('payee')} for {result.get('amount')}: {status}",
                     {"request": result, "approval_status": status, "executed": False})
        return result

    # ----- delegation -----

    async def delegate(self, parent: AgentDeps, to_agent: str, task: str) -> dict:
        run = parent.run
        limits = run.limits

        def refuse(reason: str) -> dict:
            parent.log("delegation_refused", f"{parent.agent_name} -> {to_agent} refused: {reason}",
                       {"to_agent": to_agent, "task": task, "reason": reason})
            return {"delegation_refused": True, "reason": reason}

        try:
            req = DelegationRequest(from_agent=parent.agent_name, to_agent=to_agent, task=task,
                                    ticket_id=run.ticket_id, depth=parent.depth + 1)
        except ValidationError as exc:
            return refuse(f"invalid delegation request: {exc.errors()[0]['msg']}")
        if req.to_agent == parent.agent_name:
            return refuse("an agent cannot delegate to itself")
        if req.to_agent in parent.chain:
            return refuse(f"{req.to_agent} is already in the chain {' -> '.join(parent.chain)}; that would loop")
        if req.depth > limits.max_delegation_depth:
            run.limit_hit = True
            return refuse(f"max delegation depth {limits.max_delegation_depth} reached")
        cache_key = (parent.agent_name, req.to_agent, _normalize(req.task))
        if cache_key in run.delegation_cache:
            parent.log("delegation_result", f"{req.to_agent} already answered this exact task; reused report",
                       {"to_agent": req.to_agent, "task": task, "reused": True})
            return run.delegation_cache[cache_key]
        if run.delegations >= limits.max_delegations_per_run:
            run.limit_hit = True
            return refuse(f"max {limits.max_delegations_per_run} delegations per run reached")

        run.delegations += 1
        parent.log("delegation_request", f"{parent.agent_name} -> {req.to_agent}: {task}",
                   {"to_agent": req.to_agent, "task": task, "depth": req.depth, "delegation_number": run.delegations})
        report = await self._run_agent(run, req.to_agent, task, depth=req.depth, chain=parent.chain + [req.to_agent])
        parent.log("delegation_result", f"{req.to_agent} reported back to {parent.agent_name}",
                   {"to_agent": req.to_agent, "report": report})
        run.delegation_cache[cache_key] = report
        return report

    # ----- one agent loop -----

    async def _run_agent(self, run: TeamRun, name: AgentName, task: str, *, depth: int, chain: list[str]) -> dict:
        deps = AgentDeps(team=self, run=run, agent_name=name, depth=depth, chain=chain)
        deps.log("agent_started", f"{name} started: {task}", {"task": task})
        model_steps = 0
        step = 0
        try:
            async with self.agents[name].iter(task, deps=deps, usage=run.usage, usage_limits=run.usage_limits()) as agent_run:
                async for node in agent_run:
                    step += 1
                    if Agent.is_model_request_node(node):
                        model_steps += 1
                        if model_steps > run.limits.max_steps_per_agent:
                            run.limit_hit = True
                            deps.log("limit_reached", f"{name} hit its loop cap ({run.limits.max_steps_per_agent} model steps)",
                                     {"limit": "max_steps_per_agent"}, step=step)
                            return self._stopped_report(name, f"stopped after {run.limits.max_steps_per_agent} model steps")
                        deps.log("loop_step", f"{name} step {step}: model request #{model_steps}",
                                 {"node": "model_request", "parts": _request_parts(node.request)}, step=step)
                    elif Agent.is_call_tools_node(node):
                        resp = node.model_response
                        deps.log("loop_step", f"{name} step {step}: model response",
                                 {"node": "model_response", "model_name": resp.model_name,
                                  "parts": _response_parts(resp), "usage": _usage(resp.usage)}, step=step)
                    elif Agent.is_end_node(node):
                        deps.log("loop_step", f"{name} step {step}: final output",
                                 {"node": "end", "output": _jsonable(node.data.output)}, step=step)
                    else:
                        deps.log("loop_step", f"{name} step {step}: {type(node).__name__}",
                                 {"node": type(node).__name__}, step=step)
                output = agent_run.result.output
        except UsageLimitExceeded as exc:
            run.limit_hit = True
            deps.log("limit_reached", f"team usage limit reached while {name} was working: {exc}", {"error": str(exc)})
            return self._stopped_report(name, f"team usage limit reached: {exc}")
        except Exception as exc:
            deps.log("agent_error", f"{name} failed: {type(exc).__name__}: {exc}", {"error": f"{type(exc).__name__}: {exc}"})
            return self._stopped_report(name, f"error: {type(exc).__name__}: {exc}")
        result = output.model_dump(mode="json")
        deps.log("agent_finished", f"{name} finished", {"output": result, "usage_so_far": run.usage_summary()})
        return result

    @staticmethod
    def _stopped_report(name: AgentName, reason: str) -> dict:
        return {"agent": name, "status": "incomplete", "summary": f"Stopped safely: {reason}",
                "findings": [], "recommendations": [], "proposed_actions": [], "open_questions": [reason]}

    # ----- entry points -----

    async def run(self, entry_agent: AgentName, task: str, *, ticket_id: int | None = None,
                  run_type: str = "ticket_run", limits: RunLimits | None = None) -> TeamRunResult:
        """Run one agent (normally the Boss) on a task, with full delegation available."""
        run = TeamRun(run_id=uuid.uuid4().hex, run_type=run_type, ticket_id=ticket_id,
                      limits=limits or self.limits, audit=self.audit)
        run.log(None, "run_started", f"{run_type}: {entry_agent} on ticket {ticket_id}",
                {"entry_agent": entry_agent, "task": task, "limits": run.limits.model_dump()})
        output: dict | None = None
        error: str | None = None
        try:
            async with self.mcp:  # one MCP server process for the whole team run
                if ticket_id is not None:
                    run.ticket = await self._load_ticket(run, ticket_id)
                output = await self._run_agent(run, entry_agent, task, depth=0, chain=[entry_agent])
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        stopped = "error" if error else ("limit_reached" if run.limit_hit else "completed")
        if output and output.get("status") == "incomplete" and str(output.get("summary", "")).startswith("Stopped safely: error"):
            stopped = "error"
        result = TeamRunResult(
            run_id=run.run_id, run_type=run_type, ticket_id=ticket_id, entry_agent=entry_agent,
            output=output, stopped_reason=stopped, error=error, delegations=run.delegations,
            usage=run.usage_summary(), payment_requests=run.payment_requests,
        )
        run.log(None, "run_finished", f"run {stopped}", {"stopped_reason": stopped, "error": error,
                "delegations": run.delegations, "usage": result.usage,
                "pending_approvals": [p.model_dump() for p in run.payment_requests]})
        return result

    async def run_ticket(self, ticket_id: int) -> TeamRunResult:
        """Boss works one ticket end to end (used by the backend in Problem 7/9)."""
        return await self.run("boss", f"Work ticket {ticket_id}. Decide who to call first, delegate only what it needs, "
                                      "review the findings, and return your decision.", ticket_id=ticket_id)

    async def _load_ticket(self, run: TeamRun, ticket_id: int) -> TicketContext:
        args = {"ticket_id": ticket_id}
        run.log(None, "mcp_tool_call", "load ticket context via MCP get_tickets", {"tool": "get_tickets", "args": args})
        data = await self.mcp.direct_call_tool("get_tickets", args)
        run.log(None, "mcp_tool_result", "ticket context loaded", {"tool": "get_tickets", "args": args, "result": data})
        return TicketContext(**data["tickets"][0])


# ---------- helpers that turn message parts into audit-friendly dicts ----------

def _request_parts(request) -> list[dict]:
    out = []
    for p in request.parts:
        kind = getattr(p, "part_kind", type(p).__name__)
        if kind == "tool-return":
            out.append({"kind": kind, "tool": p.tool_name, "content": _jsonable(p.content)})
        elif kind == "retry-prompt":
            out.append({"kind": kind, "tool": getattr(p, "tool_name", None), "content": _jsonable(p.content)})
        elif kind == "user-prompt":
            out.append({"kind": kind, "content": _jsonable(p.content)})
        else:
            out.append({"kind": kind})
    return out


def _response_parts(response) -> list[dict]:
    out = []
    for p in response.parts:
        kind = getattr(p, "part_kind", type(p).__name__)
        if kind == "tool-call":
            out.append({"kind": kind, "tool": p.tool_name, "args": _jsonable(p.args)})
        elif kind == "text":
            out.append({"kind": kind, "content": p.content})
        else:
            out.append({"kind": kind})
    return out


def _usage(u) -> dict:
    return {"input_tokens": getattr(u, "input_tokens", 0), "output_tokens": getattr(u, "output_tokens", 0)}
