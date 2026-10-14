"""Agent-team tests: MOCK model (scripted, no API) + REAL MCP server over stdio on an
isolated database copy + REAL audit trail written to a temporary file."""

import asyncio
import json
import sqlite3

import pytest

from agents import AGENT_TOOLS, BACKEND_ONLY_TOOLS
from audit import AuditTrail
from models import RunLimits
from scripted_model import ScriptedLLM, final, specialist, tool
from team import CampusCustomsTeam

BOSS_DONE = final(ticket_id=None, problem="test", resolution_status="unresolved", resolution_reason="test run")


def make_team(llm, iso_db, audit_path, **limits):
    return CampusCustomsTeam(llm.model(), audit=AuditTrail(audit_path), db_path=iso_db,
                             limits=RunLimits(**limits) if limits else None)


def events(audit_path):
    return json.loads(audit_path.read_text(encoding="utf-8"))


def types(audit_path):
    return [e["event_type"] for e in events(audit_path)]


def test_boss_to_specialist_to_specialist_delegation(iso_db, audit_path):
    llm = ScriptedLLM({
        "boss": [
            tool("delegate_to", agent="inventory", task="Check CC-HOOD-NAVY size M against 20 requested and find a restock vendor."),
            final(ticket_id=103, problem="bulk hoodie order short on stock", first_specialist="inventory",
                  delegation_path=["boss->inventory", "inventory->accounting"],
                  resolution_status="awaiting_human_approval", resolution_reason="vendor bill must be approved"),
        ],
        "inventory": [
            tool("get_product_stock_and_price", sku="CC-HOOD-NAVY", size="M", qty_needed=20),
            tool("list_vendors", specialty_keyword="apparel"),
            tool("delegate_to", agent="accounting", task="Vendor 1 is blocked by invoice 501. Check cash and prepare that invoice for approval."),
            specialist("inventory", "short 12; vendor 1 blocked until invoice 501 paid", status="needs_human"),
        ],
        "accounting": [
            tool("get_cash_balance"),
            tool("prepare_payment_request", kind="invoice", ref_id=501),
            specialist("accounting", "invoice 501 prepared for approval", status="needs_human"),
        ],
    })
    team = make_team(llm, iso_db, audit_path)
    result = asyncio.run(team.run("boss", "Work ticket 103.", ticket_id=103, run_type="test"))

    assert result.stopped_reason == "completed", result
    assert result.output["resolution_status"] == "awaiting_human_approval"
    assert result.delegations == 2
    assert llm.calls == ["boss", "inventory", "inventory", "inventory", "accounting", "accounting", "accounting",
                         "inventory", "boss"]
    # The prepared payment is captured from the real tool result, and NOT executed.
    [pr] = result.payment_requests
    assert pr.prepared_by == "accounting" and pr.request["amount"] == 840 and pr.approval_status == "pending_human_approval"
    with sqlite3.connect(iso_db) as con:
        assert con.execute("SELECT COUNT(*) FROM payments").fetchone() == (0,)
        assert con.execute("SELECT balance FROM cash_accounts").fetchone() == (3400.0,)

    ev = events(audit_path)
    t = [e["event_type"] for e in ev]
    assert t[0] == "run_started" and t[-1] == "run_finished"
    for needed in ("agent_started", "loop_step", "mcp_tool_call", "mcp_tool_result", "delegation_request",
                   "delegation_result", "payment_proposed", "agent_finished"):
        assert needed in t, needed
    assert all(e["ticket_id"] == 103 and e["run_id"] == result.run_id for e in ev)
    # Delegated results flow back: inventory's delegation_result carries accounting's report.
    inv_result = next(e for e in ev if e["event_type"] == "delegation_result" and e["agent"] == "inventory")
    assert inv_result["data"]["report"]["agent"] == "accounting"
    assert next(e for e in ev if e["event_type"] == "payment_proposed")["data"]["executed"] is False
    # Steps are numbered per agent loop, and nested agents record their chain.
    acct_steps = [e for e in ev if e["agent"] == "accounting" and e["event_type"] == "loop_step"]
    assert [e["step"] for e in acct_steps] == list(range(1, len(acct_steps) + 1))
    assert acct_steps[0]["chain"] == ["boss", "inventory", "accounting"] and acct_steps[0]["depth"] == 2


def test_agents_only_see_their_allowed_tools(iso_db, audit_path):
    script = {name: [specialist(name, "ok")] for name in AGENT_TOOLS if name != "boss"}
    script["boss"] = [tool("delegate_to", agent=a, task=f"Test task for {a}: just report ok.")
                      for a in ("inventory", "accounting", "facilities", "customer_service")] + [BOSS_DONE]
    llm = ScriptedLLM(script)
    asyncio.run(make_team(llm, iso_db, audit_path).run("boss", "tool visibility test", run_type="test"))
    for name, allowed in AGENT_TOOLS.items():
        assert llm.tools_seen[name] == set(allowed) | {"delegate_to"}, name
        assert not (llm.tools_seen[name] & BACKEND_ONLY_TOOLS)


@pytest.mark.parametrize("target, reason", [("inventory", "itself"), ("boss", "already in the chain")])
def test_self_and_cycle_delegation_refused(iso_db, audit_path, target, reason):
    llm = ScriptedLLM({
        "boss": [tool("delegate_to", agent="inventory", task="Check stock of CC-TEE-WHITE size S for one tee."), BOSS_DONE],
        "inventory": [tool("delegate_to", agent=target, task="Please help me with this stock question."),
                      specialist("inventory", "done")],
    })
    asyncio.run(make_team(llm, iso_db, audit_path).run("boss", "loop test", run_type="test"))
    refused = [e for e in events(audit_path) if e["event_type"] == "delegation_refused"]
    assert len(refused) == 1 and reason in refused[0]["data"]["reason"]


def test_depth_limit(iso_db, audit_path):
    llm = ScriptedLLM({
        "boss": [tool("delegate_to", agent="inventory", task="Check stock of CC-TEE-WHITE size S for one tee."), BOSS_DONE],
        "inventory": [tool("delegate_to", agent="accounting", task="Check the checking balance please."),
                      specialist("inventory", "done")],
    })
    result = asyncio.run(make_team(llm, iso_db, audit_path, max_delegation_depth=1).run("boss", "depth test", run_type="test"))
    refused = [e for e in events(audit_path) if e["event_type"] == "delegation_refused"]
    assert "depth" in refused[0]["data"]["reason"]
    assert "accounting" not in llm.calls and result.stopped_reason == "limit_reached"


def test_delegation_cap_and_repeat_reuse(iso_db, audit_path):
    same = "Check stock of CC-TEE-WHITE size S for one tee."
    llm = ScriptedLLM({
        "boss": [tool("delegate_to", agent="inventory", task=same),
                 tool("delegate_to", agent="inventory", task=same),            # identical -> reused, no new run
                 tool("delegate_to", agent="facilities", task="Check lease 1 rent status."),  # over cap of 1
                 BOSS_DONE],
        "inventory": [specialist("inventory", "S has 0")],
    })
    result = asyncio.run(make_team(llm, iso_db, audit_path, max_delegations_per_run=1).run("boss", "cap test", run_type="test"))
    assert llm.calls.count("inventory") == 1 and "facilities" not in llm.calls
    assert result.delegations == 1
    assert any(e["event_type"] == "delegation_result" and e["data"].get("reused") for e in events(audit_path))
    assert any("max 1 delegations" in e["data"].get("reason", "") for e in events(audit_path))


def test_repeated_tool_calls_are_cached_then_refused(iso_db, audit_path):
    llm = ScriptedLLM({"facilities": [tool("get_lease_rent_status", lease_id=1)] * 5 + [specialist("facilities", "ok")]})
    asyncio.run(make_team(llm, iso_db, audit_path, max_identical_tool_calls=2).run("facilities", "repeat test", run_type="test"))
    t = types(audit_path)
    assert t.count("mcp_tool_call") == 1          # only one real MCP call
    assert t.count("mcp_tool_cache_hit") == 2     # then reused
    assert t.count("limit_reached") == 2          # then refused


def test_agent_loop_step_cap_stops_runaway_agent(iso_db, audit_path):
    llm = ScriptedLLM({"facilities": [tool("get_lease_rent_status", lease_id=1)]}, repeat_last=True)
    result = asyncio.run(make_team(llm, iso_db, audit_path, max_steps_per_agent=3, max_identical_tool_calls=10)
                         .run("facilities", "runaway test", run_type="test"))
    assert result.stopped_reason == "limit_reached"
    assert result.output["status"] == "incomplete"
    assert llm.calls.count("facilities") == 3


def test_team_token_budget_stops_run(iso_db, audit_path):
    llm = ScriptedLLM({
        "boss": [tool("delegate_to", agent="facilities", task="Check lease 1 rent status in detail.")] + [BOSS_DONE],
        "facilities": [tool("get_lease_rent_status", lease_id=1)] * 20,
    })
    result = asyncio.run(make_team(llm, iso_db, audit_path, team_total_tokens_limit=1000, max_steps_per_agent=50,
                                   max_identical_tool_calls=50, max_tool_calls_per_agent=50)
                         .run("boss", "budget test " * 50, run_type="test"))
    assert result.stopped_reason == "limit_reached"
    assert "limit_reached" in types(audit_path)
    assert result.usage["total_tokens"] <= 1000 + 400  # stops at the first request past the cap


def test_audit_trail_appends_across_runs_and_never_overwrites(iso_db, audit_path):
    def one_run():
        llm = ScriptedLLM({"facilities": [tool("get_lease_rent_status", lease_id=1), specialist("facilities", "ok")]})
        return asyncio.run(make_team(llm, iso_db, audit_path).run("facilities", "append test", run_type="test"))

    assert not audit_path.exists()
    r1 = one_run()
    first = events(audit_path)
    r2 = one_run()
    both = events(audit_path)
    assert both[: len(first)] == first and len(both) > len(first)
    assert {e["run_id"] for e in both} == {r1.run_id, r2.run_id}
    assert len({e["event_id"] for e in both}) == len(both)

    audit_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(Exception):
        AuditTrail(audit_path).log(run_id="x", run_type="test", ticket_id=None, agent=None,
                                   event_type="run_started", summary="should not be written")
    assert audit_path.read_text(encoding="utf-8") == "{not json"


def test_audit_redacts_secrets(audit_path, monkeypatch):
    monkeypatch.setenv("PORTKEY_API_KEY", "pk-test-secret-value")
    AuditTrail(audit_path).log(run_id="x", run_type="test", ticket_id=None, agent="boss", event_type="loop_step",
                               summary="saw pk-test-secret-value",
                               data={"api_key": "abc", "auth_token": "def", "note": "pk-test-secret-value",
                                     "usage": {"total_tokens": 123, "input_tokens": 100}})
    text = audit_path.read_text(encoding="utf-8")
    assert "pk-test-secret-value" not in text and "abc" not in text and "def" not in text
    assert json.loads(text)[0]["data"]["usage"] == {"total_tokens": 123, "input_tokens": 100}
