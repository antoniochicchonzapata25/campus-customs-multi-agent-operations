"""API tests for backend/main.py.

Each test builds the app on ISOLATED copies: a temp original DB, a temp working
DB (served by the REAL MCP server over stdio), and a temp audit trail. Agent
runs use the real CampusCustomsTeam driven by the scripted MOCK model, or a fake
team for failure cases. No live model calls; the real databases and audit
trail are guarded by conftest.protected_files_unchanged.
"""

import asyncio
import json
import shutil
import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import agents
import db_reset
from audit import AuditTrail
from conftest import ORIGINAL_DB, WORKING_DB, sha256
from main import Settings, create_app
from models import TeamRunResult
from scripted_model import ScriptedLLM, final, specialist, tool
from team import CampusCustomsTeam


@pytest.fixture
def env(tmp_path):
    original = tmp_path / "original.db"
    working = tmp_path / "working.db"
    shutil.copyfile(ORIGINAL_DB, original)
    shutil.copyfile(WORKING_DB, working)
    settings = Settings(original_db=original, working_db=working, audit_path=tmp_path / "audit_trail.json",
                        mcp_db_override=working)
    return settings


def client(settings, team_factory=None) -> TestClient:
    return TestClient(create_app(settings, team_factory))


def q(db, sql, *params):
    with sqlite3.connect(db) as con:
        return con.execute(sql, params).fetchall()


def scripted_team(settings, script):
    llm = ScriptedLLM(script)
    return lambda: CampusCustomsTeam(llm.model(), audit=AuditTrail(settings.audit_path), db_path=settings.working_db)


RENT_SCRIPT = {
    "boss": [tool("delegate_to", agent="facilities", task="Verify the rent notice against lease 1 and get rent prepared."),
             final(ticket_id=102, problem="rent notice", first_specialist="facilities",
                   resolution_status="awaiting_human_approval", resolution_reason="rent prepared for approval")],
    "facilities": [tool("get_lease_rent_status", lease_id=1),
                   tool("delegate_to", agent="accounting", task="Notice is consistent. Prepare rent for lease 1."),
                   specialist("facilities", "notice consistent", status="needs_human")],
    "accounting": [tool("get_cash_balance"), tool("prepare_payment_request", kind="rent", ref_id=1),
                   specialist("accounting", "rent prepared", status="needs_human")],
}


def run_rent_ticket(c) -> dict:
    r = c.post("/api/tickets/102/run")
    assert r.status_code == 200, r.text
    return r.json()


# ---------- tickets / cash / events ----------

def test_list_tickets_reads_current_status_from_db(env):
    q(env.working_db, "UPDATE tickets SET status = 'resolved' WHERE id = 102")  # isolated copy only
    with client(env) as c:
        body = c.get("/api/tickets").json()
        assert body["count"] == 3
        by_id = {t["id"]: t for t in body["tickets"]}
        assert set(by_id) == {101, 102, 103}
        assert by_id[101]["status"] == "open" and by_id[101]["is_resolved"] is False
        assert by_id[102]["status"] == "resolved" and by_id[102]["is_resolved"] is True
        assert by_id[103]["requester"] == "Yale AI Club" and by_id[103]["qty"] == 20
        assert c.get("/api/tickets/101").json()["sku"] == "CC-TEE-WHITE"


@pytest.mark.parametrize("path, method, code", [
    ("/api/tickets/999", "get", 404), ("/api/tickets/999/run", "post", 404),
    ("/api/tickets/0/run", "post", 422), ("/api/tickets/abc/run", "post", 422), ("/api/tickets/-1", "get", 422),
])
def test_invalid_or_unknown_ticket_ids(env, path, method, code):
    with client(env, team_factory=lambda: pytest.fail("team must not run")) as c:
        r = getattr(c, method)(path)
        assert r.status_code == code and "detail" in r.json()


def test_cash_balance_reflects_db(env):
    q(env.working_db, "UPDATE cash_accounts SET balance = 1234.5")
    with client(env) as c:
        assert c.get("/api/cash").json() == {"account": "checking", "balance": 1234.5,
                                             "balance_as_of": "2026-08-31", "shop_date": "2026-08-31"}


def test_events_structure_order_limit_and_filters(env):
    with client(env, scripted_team(env, RENT_SCRIPT)) as c:
        run = run_rent_ticket(c)
        before = env.audit_path.read_text(encoding="utf-8")
        all_ev = c.get("/api/events", params={"limit": 1000}).json()
        assert all_ev["order"] == "oldest_first" and all_ev["skipped"] == 0
        stamps = [e["timestamp"] for e in all_ev["events"]]
        assert stamps == sorted(stamps)
        types = {e["event_type"] for e in all_ev["events"]}
        assert {"run_started", "loop_step", "mcp_tool_call", "mcp_tool_result", "delegation_request",
                "delegation_result", "payment_proposed", "agent_finished", "run_finished",
                "ticket_status_changed"} <= types
        last3 = c.get("/api/events", params={"limit": 3}).json()
        assert last3["returned"] == 3 and last3["events"] == all_ev["events"][-3:]
        acct = c.get("/api/events", params={"agent": "accounting", "limit": 1000}).json()
        assert acct["events"] and all(e["agent"] == "accounting" for e in acct["events"])
        assert c.get("/api/events", params={"run_id": run["run_id"]}).json()["total"] > 10
        mid = all_ev["events"][5]["event_id"]
        assert c.get("/api/events", params={"after": mid, "limit": 1000}).json()["events"] == all_ev["events"][6:]
        assert c.get("/api/events", params={"limit": 0}).status_code == 422
        assert env.audit_path.read_text(encoding="utf-8") == before  # reading never rewrites


def test_events_missing_malformed_and_corrupt_audit(env):
    with client(env) as c:
        assert c.get("/api/events").json()["events"] == []  # file does not exist yet
        AuditTrail(env.audit_path).log(run_id="r1", run_type="test", ticket_id=None, agent="boss",
                                       event_type="loop_step", summary="ok")
        data = json.loads(env.audit_path.read_text(encoding="utf-8")) + [{"not": "an event"}]
        env.audit_path.write_text(json.dumps(data), encoding="utf-8")
        body = c.get("/api/events").json()
        assert body["returned"] == 1 and body["skipped"] == 1
        env.audit_path.write_text("[{broken", encoding="utf-8")
        r = c.get("/api/events")
        assert r.status_code == 500 and "unreadable" in r.json()["detail"]
        assert env.audit_path.read_text(encoding="utf-8") == "[{broken"


# ---------- running the team ----------

def test_run_ticket_with_scripted_team_end_to_end_approval(env):
    with client(env, scripted_team(env, RENT_SCRIPT)) as c:
        run = run_rent_ticket(c)
        assert run["state"] == "completed" and run["succeeded"] is True
        assert run["resolution_status"] == "awaiting_human_approval" and run["ticket_status"] == "awaiting_approval"
        [pending] = run["pending_approvals"]
        assert pending["kind"] == "rent" and pending["amount"] == 2400 and pending["prepared_by"] == "accounting"
        # The run moved no money.
        assert c.get("/api/cash").json()["balance"] == 3400
        assert q(env.working_db, "SELECT COUNT(*) FROM payments") == [(0,)]
        assert c.get("/api/tickets/102/run").json()["run_id"] == run["run_id"]
        assert c.get("/api/approvals").json()["approvals"][0]["request_id"] == pending["request_id"]

        ok = c.post("/api/approvals", json={"request_id": pending["request_id"], "approve": True,
                                            "approved_by": "Store Manager", "approved_amount": 2400})
        assert ok.status_code == 200, ok.text
        body = ok.json()
        assert body["status"] == "paid" and body["balance_after"] == 1000 and body["ticket_status"] == "resolved"
        assert c.get("/api/cash").json()["balance"] == 1000
        assert c.get("/api/tickets/102").json()["is_resolved"] is True
        assert c.get("/api/approvals").json()["count"] == 0
        assert q(env.working_db, "SELECT kind, ref_id, amount, approved_by FROM payments") == [
            ("rent", 1, 2400.0, "Store Manager")]
        assert q(env.working_db, "SELECT next_due FROM leases") == [("2026-10-02",)]

        again = c.post("/api/approvals", json={"request_id": pending["request_id"], "approve": True,
                                               "approved_by": "Store Manager", "approved_amount": 2400})
        assert again.status_code == 409 and again.json()["status"] == "refused"
        assert c.get("/api/cash").json()["balance"] == 1000
        types = [e["event_type"] for e in json.loads(env.audit_path.read_text(encoding="utf-8"))]
        assert "human_approval" in types and types.count("ticket_status_changed") == 2


class FakeTeam:
    def __init__(self, result=None, exc=None, gate=None):
        self.result, self.exc, self.gate, self.calls = result, exc, gate, 0

    async def run_ticket(self, ticket_id):
        self.calls += 1
        if self.gate is not None:
            await self.gate.wait()
        if self.exc:
            raise self.exc
        return self.result


def _result(stopped, output, error=None):
    return TeamRunResult(run_id="fake-run", run_type="ticket_run", ticket_id=101, entry_agent="boss", output=output,
                         stopped_reason=stopped, error=error, delegations=0, usage={})


def test_limit_reached_run_is_not_success_and_leaves_status(env):
    fake = FakeTeam(_result("limit_reached", {"agent": "boss", "status": "incomplete", "summary": "Stopped safely: cap"}))
    with client(env, lambda: fake) as c:
        r = c.post("/api/tickets/101/run")
        assert r.status_code == 200
        body = r.json()
        assert body["state"] == "limit_reached" and body["succeeded"] is False and body["error"]
        assert c.get("/api/tickets/101").json()["status"] == "open"


def test_errored_and_crashing_runs_return_502(env):
    with client(env, lambda: FakeTeam(_result("error", None, "ModelHTTPError: boom"))) as c:
        r = c.post("/api/tickets/101/run")
        assert r.status_code == 502 and r.json()["state"] == "error" and r.json()["succeeded"] is False
    with client(env, lambda: FakeTeam(exc=RuntimeError("secret internals"))) as c:
        r = c.post("/api/tickets/101/run")
        assert r.status_code == 502 and "secret internals" not in r.text
        assert c.get("/api/tickets/101").json()["status"] == "open"


def test_model_not_configured_returns_503(env):
    def factory():
        raise agents.ModelNotConfigured("PORTKEY_API_KEY is not set")
    with client(env, factory) as c:
        r = c.post("/api/tickets/101/run")
        assert r.status_code == 503 and "gpt-6-luna" in r.json()["detail"]


def test_overlapping_runs_on_same_ticket_rejected(env):
    async def scenario():
        gate = asyncio.Event()
        fake = FakeTeam(_result("completed", {"ticket_id": 101, "problem": "x", "resolution_status": "unresolved",
                                              "resolution_reason": "x"}), gate=gate)
        app = create_app(env, lambda: fake)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            first = asyncio.create_task(c.post("/api/tickets/101/run"))
            for _ in range(200):
                await asyncio.sleep(0.05)
                if fake.calls:
                    break
            second = await c.post("/api/tickets/101/run")
            reset = await c.post("/api/reset", json={"confirm": True})
            listed = (await c.get("/api/tickets")).json()
            gate.set()
            done = await first
            await app.state.desk.shop.close()
            return second, reset, listed, done, fake.calls
    second, reset, listed, done, calls = asyncio.run(scenario())
    assert second.status_code == 409 and reset.status_code == 409
    assert [t["run_in_progress"] for t in listed["tickets"] if t["id"] == 101] == [True]
    assert done.status_code == 200 and calls == 1


# ---------- approvals: refusals ----------

def test_approval_refusals(env):
    with client(env, scripted_team(env, RENT_SCRIPT)) as c:
        rid = run_rent_ticket(c)["pending_approvals"][0]["request_id"]

        def post(**kw):
            body = {"request_id": rid, "approve": True, "approved_by": "Store Manager", "approved_amount": 2400} | kw
            return c.post("/api/approvals", json=body)

        assert post(approve=False).status_code == 422
        assert post(approved_by="").status_code == 422
        assert post(approved_amount=-1).status_code == 422
        assert c.post("/api/approvals", json={"approve": True}).status_code == 422
        assert c.post("/api/approvals", content="not json", headers={"Content-Type": "application/json"}).status_code == 422
        assert post(request_id="0" * 32).status_code == 404
        r = post(approved_by="accounting")  # agents can't approve
        assert r.status_code == 422 and r.json()["status"] == "refused"
        r = post(approved_amount=2000)  # amount must match the database
        assert r.status_code == 409 and "does not match" in r.json()["message"]

        q(env.working_db, "UPDATE cash_accounts SET balance = 500")  # isolated copy only
        r = post()
        assert r.status_code == 409 and "Insufficient funds" in r.json()["message"]
        assert c.get("/api/cash").json()["balance"] == 500
        assert q(env.working_db, "SELECT COUNT(*) FROM payments") == [(0,)]
        assert c.get("/api/tickets/102").json()["status"] == "awaiting_approval"
        refusals = [e for e in json.loads(env.audit_path.read_text(encoding="utf-8")) if e["event_type"] == "approval_refused"]
        assert len(refusals) == 3


def test_invoice_and_blocked_purchase_order_flow(env):
    script = {
        "boss": [tool("delegate_to", agent="accounting", task="Prepare invoice 501 and a restock of 12 hoodies M from vendor 1."),
                 final(ticket_id=103, problem="bulk order", resolution_status="awaiting_human_approval",
                       resolution_reason="invoice prepared; restock blocked")],
        "accounting": [tool("prepare_payment_request", kind="invoice", ref_id=501),
                       tool("prepare_payment_request", kind="purchase_order", ref_id=1, sku="CC-HOOD-NAVY", size="M", qty=12),
                       specialist("accounting", "501 prepared; PO refused while 501 open", status="needs_human")],
    }
    with client(env, scripted_team(env, script)) as c:
        run = c.post("/api/tickets/103/run").json()
        assert [p["kind"] for p in run["pending_approvals"]] == ["invoice"]  # PO was refused by the tool
        inventory_before = q(env.working_db, "SELECT * FROM inventory")
        r = c.post("/api/approvals", json={"request_id": run["pending_approvals"][0]["request_id"], "approve": True,
                                           "approved_by": "Store Manager", "approved_amount": 840})
        assert r.json()["status"] == "paid" and r.json()["balance_after"] == 2560
        assert q(env.working_db, "SELECT status FROM invoices WHERE id = 501") == [("paid",)]
        assert q(env.working_db, "SELECT * FROM inventory") == inventory_before
        assert r.json()["ticket_status"] == "resolved"


# ---------- reset ----------

def test_reset_restores_working_db_from_unchanged_original(env):
    original_hash = sha256(env.original_db)
    with client(env, scripted_team(env, RENT_SCRIPT)) as c:
        rid = run_rent_ticket(c)["pending_approvals"][0]["request_id"]
        c.post("/api/approvals", json={"request_id": rid, "approve": True, "approved_by": "Store Manager",
                                       "approved_amount": 2400})
        assert c.get("/api/cash").json()["balance"] == 1000
        assert c.post("/api/reset", json={}).status_code == 422
        assert c.post("/api/reset", json={"confirm": False}).status_code == 422
        r = c.post("/api/reset", json={"confirm": True})
        assert r.status_code == 200 and r.json()["sha256"] == original_hash
        assert sha256(env.working_db) == original_hash and sha256(env.original_db) == original_hash
        # The MCP server sees the restored file immediately.
        assert c.get("/api/cash").json()["balance"] == 3400
        assert all(t["status"] == "open" for t in c.get("/api/tickets").json()["tickets"])
        assert c.get("/api/approvals").json()["count"] == 0  # requests from before the reset are void
        assert c.get("/api/tickets/102/run").status_code == 404
        assert "database_reset" in [e["event_type"] for e in json.loads(env.audit_path.read_text(encoding="utf-8"))]


def test_failed_reset_leaves_both_databases_untouched(env, monkeypatch):
    q(env.working_db, "UPDATE cash_accounts SET balance = 999")  # make working differ from original
    working_hash, original_hash = sha256(env.working_db), sha256(env.original_db)

    def broken_copy(src, dst):
        Path(dst).write_bytes(b"partial")
        raise OSError("disk full")

    with client(env) as c:
        monkeypatch.setattr(db_reset.shutil, "copyfile", broken_copy)
        r = c.post("/api/reset", json={"confirm": True})
        assert r.status_code == 500 and "unchanged" in r.json()["detail"]
        monkeypatch.undo()
        assert sha256(env.working_db) == working_hash and sha256(env.original_db) == original_hash
        assert not list(env.working_db.parent.glob("*.reset-tmp"))
        assert c.get("/api/cash").json()["balance"] == 999

        env.original_db.write_bytes(b"this is not a sqlite database")  # corrupt source -> refused
        r = c.post("/api/reset", json={"confirm": True})
        assert r.status_code == 500 and sha256(env.working_db) == working_hash
        assert not list(env.working_db.parent.glob("*.reset-tmp"))


def test_reset_refuses_same_path():
    with pytest.raises(db_reset.ResetError):
        db_reset.reset_working_db(ORIGINAL_DB, ORIGINAL_DB)


# ---------- CORS, availability, secrets ----------

def test_cors_allows_vite_origin_only(env):
    with client(env) as c:
        ok = c.options("/api/tickets", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
        assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
        post = c.options("/api/approvals", headers={"Origin": "http://localhost:5173",
                                                    "Access-Control-Request-Method": "POST",
                                                    "Access-Control-Request-Headers": "content-type"})
        assert post.status_code == 200
        bad = c.options("/api/tickets", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
        assert "access-control-allow-origin" not in bad.headers
        assert c.get("/api/cash", headers={"Origin": "http://localhost:5173"}).headers[
            "access-control-allow-origin"] == "http://localhost:5173"


def test_mcp_unavailable_returns_503(env, monkeypatch):
    monkeypatch.setattr(agents, "MCP_SERVER_SCRIPT", Path(env.working_db.parent / "missing_server.py"))
    with client(env) as c:
        for method, path in (("get", "/api/tickets"), ("get", "/api/cash"), ("post", "/api/tickets/101/run")):
            r = getattr(c, method)(path)
            assert r.status_code == 503 and r.json() == {"detail": "Shop data service (MCP server) is unavailable"}
        # With no prepared requests in the trail, the approvals list needs no MCP call at all.
        assert c.get("/api/approvals").json() == {"count": 0, "approvals": [], "decisions": []}
        health = c.get("/api/health").json()
        assert health["status"] == "degraded" and health["mcp_connected"] is False


def test_responses_never_expose_secrets(env, monkeypatch):
    secret = "pk-live-very-secret-123"
    monkeypatch.setenv("PORTKEY_API_KEY", secret)
    with client(env, scripted_team(env, RENT_SCRIPT)) as c:
        texts = [c.post("/api/tickets/102/run").text]
        for path in ("/api/health", "/api/tickets", "/api/tickets/102", "/api/tickets/102/run", "/api/events?limit=1000",
                     "/api/approvals", "/api/cash", "/api/tickets/999", "/openapi.json"):
            texts.append(c.get(path).text)
        texts.append(c.post("/api/approvals", json={"request_id": "x" * 32, "approve": True,
                                                    "approved_by": "Someone", "approved_amount": 1}).text)
        health = c.get("/api/health").json()
        assert health["model"] == "gpt-6-luna" and health["model_configured"] is True
    for t in texts:
        assert secret not in t and "PORTKEY_API_KEY=" not in t
    assert secret not in env.audit_path.read_text(encoding="utf-8")


# ---------- human decline (Problem 7 follow-up) ----------

def _snapshot(db):
    return {t: q(db, f"SELECT * FROM {t}") for t in ("cash_accounts", "invoices", "inventory", "payments", "leases", "pricing")}


def _decline(c, request_id, **kw):
    return c.post("/api/approvals/decline",
                  json={"request_id": request_id, "decline": True, "declined_by": "Store Manager"} | kw)


def test_decline_changes_nothing_financial_and_is_audited(env):
    with client(env, scripted_team(env, RENT_SCRIPT)) as c:
        run = run_rent_ticket(c)
        rid = run["pending_approvals"][0]["request_id"]
        before = _snapshot(env.working_db)

        r = _decline(c, rid, reason="Confirm the notice with the landlord first")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "declined" and body["ticket_id"] == 102 and body["payment"] is None
        assert body["ticket_status"] == "in_progress"  # not resolved: needs follow-up

        assert _snapshot(env.working_db) == before  # no cash, invoice, inventory, payment, or lease change
        assert c.get("/api/cash").json()["balance"] == 3400
        assert c.get("/api/tickets/102").json()["is_resolved"] is False

        listed = c.get("/api/approvals").json()
        assert listed["count"] == 0 and listed["approvals"] == []
        [decision] = listed["decisions"]
        assert decision == decision | {"request_id": rid, "ticket_id": 102, "run_id": run["run_id"],
                                       "decision": "declined", "decided_by": "Store Manager", "kind": "rent",
                                       "ref_id": 1, "amount": 2400.0,
                                       "reason": "Confirm the notice with the landlord first"}

        events = json.loads(env.audit_path.read_text(encoding="utf-8"))
        [ev] = [e for e in events if e["event_type"] == "human_decline"]
        assert ev["ticket_id"] == 102 and ev["run_id"] == run["run_id"] and ev["timestamp"]
        assert ev["data"]["request_id"] == rid and ev["data"]["declined_by"] == "Store Manager"
        assert ev["data"]["decision"] == "declined" and ev["data"]["executed"] is False
        assert "human_approval" not in [e["event_type"] for e in events]
        api_events = c.get("/api/events", params={"ticket_id": 102, "limit": 1000}).json()["events"]
        assert any(e["event_type"] == "human_decline" for e in api_events)

        # Already decided: cannot be approved or declined again.
        again = c.post("/api/approvals", json={"request_id": rid, "approve": True,
                                               "approved_by": "Store Manager", "approved_amount": 2400})
        assert again.status_code == 409 and "declined" in again.json()["message"]
        assert _decline(c, rid).status_code == 409
        assert _snapshot(env.working_db) == before


def test_decline_validation_and_unknown_requests(env):
    with client(env, scripted_team(env, RENT_SCRIPT)) as c:
        rid = run_rent_ticket(c)["pending_approvals"][0]["request_id"]
        for bad in ({"decline": False}, {"declined_by": ""}, {"declined_by": "accounting"}, {"declined_by": "Boss"},
                    {"declined_by": "customer service"}, {"declined_by": " agent "}, {"reason": "x" * 501}):
            assert _decline(c, rid, **bad).status_code == 422, bad
        assert c.post("/api/approvals/decline", json={"decline": True, "declined_by": "Store Manager"}).status_code == 422
        assert c.post("/api/approvals/decline", json={"request_id": rid, "declined_by": "Store Manager"}).status_code == 422
        assert _decline(c, "f" * 32).status_code == 404
        # An amount sent with a decline is ignored; it never becomes authoritative.
        r = c.post("/api/approvals/decline", json={"request_id": rid, "decline": True,
                                                   "declined_by": "Store Manager", "approved_amount": 1})
        assert r.status_code == 200 and r.json()["payment"] is None
        assert c.get("/api/cash").json()["balance"] == 3400


def test_cannot_decline_after_approval_or_after_reset(env):
    with client(env, scripted_team(env, RENT_SCRIPT)) as c:
        rid = run_rent_ticket(c)["pending_approvals"][0]["request_id"]
        assert c.post("/api/approvals", json={"request_id": rid, "approve": True, "approved_by": "Store Manager",
                                              "approved_amount": 2400}).json()["status"] == "paid"
        r = _decline(c, rid)
        assert r.status_code == 409 and "approved" in r.json()["message"]
        assert c.get("/api/cash").json()["balance"] == 1000  # the earlier approval stands

    # A pending request made stale by a reset can't be declined either.
    shutil.copyfile(ORIGINAL_DB, env.working_db)
    with client(env, scripted_team(env, RENT_SCRIPT)) as c:
        rid = run_rent_ticket(c)["pending_approvals"][0]["request_id"]
        assert c.post("/api/reset", json={"confirm": True}).status_code == 200
        r = _decline(c, rid)
        assert r.status_code == 409 and "no longer current" in r.json()["message"]
        assert not [e for e in json.loads(env.audit_path.read_text(encoding="utf-8"))
                    if e["event_type"] == "human_decline" and e["data"].get("request_id") == rid]


TWO_PAYMENTS_SCRIPT = {
    "boss": [tool("delegate_to", agent="accounting", task="Prepare invoice 501 and the rent for lease 1 for approval."),
             final(ticket_id=101, problem="two bills", resolution_status="awaiting_human_approval",
                   resolution_reason="both prepared")],
    "accounting": [tool("prepare_payment_request", kind="invoice", ref_id=501),
                   tool("prepare_payment_request", kind="rent", ref_id=1),
                   specialist("accounting", "two requests prepared", status="needs_human")],
}


def test_ticket_with_a_declined_request_is_not_resolved_by_later_approval(env):
    with client(env, scripted_team(env, TWO_PAYMENTS_SCRIPT)) as c:
        run = c.post("/api/tickets/101/run").json()
        by_kind = {p["kind"]: p["request_id"] for p in run["pending_approvals"]}
        assert set(by_kind) == {"invoice", "rent"} and run["ticket_status"] == "awaiting_approval"

        d = _decline(c, by_kind["rent"])
        assert d.json()["ticket_status"] == "awaiting_approval"  # the invoice is still pending
        a = c.post("/api/approvals", json={"request_id": by_kind["invoice"], "approve": True,
                                           "approved_by": "Store Manager", "approved_amount": 840})
        assert a.json()["status"] == "paid" and a.json()["ticket_status"] == "in_progress"
        assert c.get("/api/tickets/101").json()["status"] == "in_progress"
        assert c.get("/api/cash").json()["balance"] == 2560  # only the approved invoice was paid
        assert q(env.working_db, "SELECT kind FROM payments") == [("invoice",)]
        assert q(env.working_db, "SELECT next_due FROM leases") == [("2026-09-02",)]  # rent untouched
        decisions = c.get("/api/approvals", params={"ticket_id": 101}).json()["decisions"]
        assert [(x["kind"], x["decision"]) for x in decisions] == [("rent", "declined"), ("invoice", "approved")]


def test_new_run_after_decline_yields_a_new_request_not_the_declined_one(env):
    twice = {k: list(v) + list(v) for k, v in RENT_SCRIPT.items()}  # the same scripted run, two times
    with client(env, scripted_team(env, twice)) as c:
        first = run_rent_ticket(c)["pending_approvals"][0]["request_id"]
        _decline(c, first)
        assert c.get("/api/approvals").json()["count"] == 0
        second = run_rent_ticket(c)["pending_approvals"]
        assert len(second) == 1 and second[0]["request_id"] != first
        assert [p["request_id"] for p in c.get("/api/approvals").json()["approvals"]] == [second[0]["request_id"]]
