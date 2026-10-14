import { errorMessage } from "../api";
import { approverProblem, contributions, describe as describeEvent, latestRunId, mergeEvents, money, ticketLine } from "../present";
import { ev, TICKETS } from "./mockBackend";

describe("mergeEvents", () => {
  it("drops duplicates by event_id and keeps oldest-first order", () => {
    const a = ev({ event_type: "run_started", timestamp: "2026-10-14T15:00:01Z" });
    const b = ev({ event_type: "agent_started", timestamp: "2026-10-14T15:00:02Z" });
    const c = ev({ event_type: "agent_finished", timestamp: "2026-10-14T15:00:03Z" });
    const once = mergeEvents([], [a, b]);
    const twice = mergeEvents(once, [b, c, a]); // overlapping poll
    expect(twice.map((e) => e.event_id)).toEqual([a.event_id, b.event_id, c.event_id]);
    expect(mergeEvents(twice, [a, b, c])).toBe(twice); // nothing new: same array, no re-render
  });
});

describe("describe", () => {
  it("turns events into plain language from their real fields", () => {
    expect(describeEvent(ev({ event_type: "delegation_request", agent: "boss", data: { to_agent: "facilities", task: "Verify lease 1" } })).title)
      .toBe("Boss asked Facilities for help");
    const pay = describeEvent(ev({ event_type: "payment_proposed", agent: "accounting",
      data: { request: { kind: "rent", payee: "Elm City Properties", amount: 2400 }, approval_status: "pending_human_approval" } }));
    expect(pay.title).toMatch(/NOT paid/);
    expect(pay.detail).toContain("$2,400.00");
    const tool = describeEvent(ev({ event_type: "mcp_tool_result", agent: "facilities", data: { tool: "get_lease_rent_status",
      result: { space_name: "Chapel Street shop", monthly_rent: 2400, next_due: "2026-09-02", is_overdue: false, days_until_due: 2 } } }));
    expect(tool.title).toBe("Facilities checked the lease and rent");
    expect(tool.detail).toBe("Chapel Street shop: $2,400.00 due 2026-09-02 (in 2 days)");
    expect(describeEvent(ev({ event_type: "limit_reached", summary: "cap" })).tone).toBe("warning");
    expect(describeEvent(ev({ event_type: "run_finished", data: { stopped_reason: "limit_reached" } })).title).toMatch(/safety limit/);
    expect(describeEvent(ev({ event_type: "human_decline", data: { declined_by: "Sam", proposed_amount: 840, reason: "later" } })).title)
      .toBe("Sam declined a payment request");
    expect(describeEvent(ev({ event_type: "loop_step", data: { node: "model_request" } })).technical).toBe(true);
  });
});

describe("contributions / latestRunId", () => {
  it("summarise each agent of the latest run from agent_finished outputs", () => {
    const events = [
      ev({ event_type: "run_started", run_id: "old" }),
      ev({ event_type: "agent_finished", run_id: "old", agent: "boss", data: { output: { resolution_reason: "old run" } } }),
      ev({ event_type: "run_started", run_id: "new" }),
      ev({ event_type: "delegation_request", run_id: "new", agent: "boss" }),
      ev({ event_type: "mcp_tool_result", run_id: "new", agent: "facilities" }),
      ev({ event_type: "agent_finished", run_id: "new", agent: "facilities", data: { output: { summary: "notice consistent", status: "needs_human" } } }),
      ev({ event_type: "human_approval", run_id: "new", agent: null }),
    ];
    const run = latestRunId(events);
    expect(run).toBe("new");
    const c = contributions(events, run);
    expect(c.map((x) => x.agent)).toEqual(["boss", "facilities"]);
    expect(c[1]).toMatchObject({ summary: "notice consistent", toolsUsed: 1, status: "needs_human" });
    expect(c[0]).toMatchObject({ handoffs: 1, summary: "" });
  });
});

describe("helpers", () => {
  it("format money and ticket lines from data", () => {
    expect(money(3400)).toBe("$3,400.00");
    expect(money(null)).toBe("—");
    expect(ticketLine(TICKETS[0])).toBe("1 × CC-TEE-WHITE, size S · invoice #501");
    expect(ticketLine(TICKETS[1])).toBe("lease #1");
  });
  it("pre-checks approver names (backend still decides)", () => {
    expect(approverProblem("")).not.toBeNull();
    expect(approverProblem("Accounting")).toMatch(/agents/);
    expect(approverProblem("customer service")).toMatch(/agents/);
    expect(approverProblem("Store Manager")).toBeNull();
  });
  it("reads every backend error shape", () => {
    expect(errorMessage(404, { detail: "No ticket found with id 999" })).toBe("No ticket found with id 999");
    expect(errorMessage(422, { detail: [{ loc: ["body", "approved_by"], msg: "String should have at least 2 characters" }] }))
      .toBe("approved_by: String should have at least 2 characters");
    expect(errorMessage(409, { status: "refused", message: "Insufficient funds" })).toBe("Insufficient funds");
    expect(errorMessage(0, null)).toMatch(/Cannot reach the backend/);
  });
});
