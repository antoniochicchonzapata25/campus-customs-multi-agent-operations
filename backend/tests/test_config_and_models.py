"""Offline configuration and data-model tests (no API calls, no MCP)."""

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

import agents
from agents import AGENT_OUTPUT_TYPES, AGENT_TOOLS, BACKEND_ONLY_TOOLS, MODEL_NAME, PROMPTS_DIR, load_prompt
from models import (
    AGENT_NAMES, BossDecision, CustomerMessageDraft, DelegationRequest, ProposedAction, RunLimits, SpecialistReport,
    TicketContext,
)


def test_five_agents_with_prompts_outputs_and_tools():
    assert set(AGENT_NAMES) == {"boss", "inventory", "accounting", "facilities", "customer_service"}
    prompts = {}
    for name in AGENT_NAMES:
        path = PROMPTS_DIR / f"{name}.md"
        assert path.exists(), path
        prompts[name] = load_prompt(name)
        assert len(prompts[name]) > 2000, f"{name} prompt is too thin"
        assert name in AGENT_TOOLS and name in AGENT_OUTPUT_TYPES
    assert len(set(prompts.values())) == 5
    assert AGENT_OUTPUT_TYPES["boss"] is BossDecision
    assert not any(t & BACKEND_ONLY_TOOLS for t in AGENT_TOOLS.values())
    assert "prepare_payment_request" in AGENT_TOOLS["accounting"]
    assert all("prepare_payment_request" not in AGENT_TOOLS[a] for a in AGENT_NAMES if a != "accounting")


def test_each_agent_receives_its_own_prompt_file(iso_db, audit_path):
    """MOCK model + real MCP: the instructions each agent sends to the model contain its prompt file."""
    import asyncio
    from audit import AuditTrail
    from scripted_model import ScriptedLLM, final, specialist, tool
    from team import CampusCustomsTeam
    script = {a: [specialist(a, "ok")] for a in AGENT_NAMES if a != "boss"}
    script["boss"] = [tool("delegate_to", agent=a, task=f"Prompt test for {a}: report ok.") for a in script] + [
        final(ticket_id=None, problem="x", resolution_status="unresolved", resolution_reason="x")]
    llm = ScriptedLLM(script)
    team = CampusCustomsTeam(llm.model(), audit=AuditTrail(audit_path), db_path=iso_db)
    asyncio.run(team.run("boss", "prompt test", run_type="test"))
    for name in AGENT_NAMES:
        assert load_prompt(name) in llm.instructions_seen[name]
        assert f"You are: {name}." in llm.instructions_seen[name]
        for other in AGENT_NAMES:
            if other != name:
                assert load_prompt(other) not in llm.instructions_seen[name]


def test_every_agent_uses_gpt_6_luna_through_portkey(monkeypatch):
    monkeypatch.setenv("PORTKEY_API_KEY", "dummy-key-for-offline-test")
    model = agents.build_model()
    assert MODEL_NAME == "gpt-6-luna"
    assert model.model_name == "gpt-6-luna"
    assert "portkey.ai" in str(model.client.base_url)


def test_missing_key_fails_loudly_without_fallback(monkeypatch):
    monkeypatch.delenv("PORTKEY_API_KEY", raising=False)
    monkeypatch.setattr(agents, "load_dotenv", lambda *a, **k: None)
    with pytest.raises(agents.ModelNotConfigured):
        agents.build_model()


def test_no_other_model_name_in_application_code():
    backend = Path(agents.__file__).parent
    pattern = re.compile(r"(gpt-[\w.\-]+|claude[\w.\-]*|gemini[\w.\-]*|o\d-mini|llama[\w.\-]*)", re.I)
    for path in [*backend.glob("*.py"), *(backend / "prompts").glob("*.md")]:
        for hit in pattern.findall(path.read_text(encoding="utf-8")):
            assert hit == "gpt-6-luna", f"{path.name}: {hit}"


def test_models_validate_representative_data():
    TicketContext(id=101, type="customer_order", requester="Tauhid Zaman", subject="Bulldog tee", sku="CC-TEE-WHITE",
                  size="S", qty=1, invoice_id=501, status="open", notes="Needs a tee in size S.",
                  created_at="2026-08-31T09:00:00-04:00")
    DelegationRequest(from_agent="inventory", to_agent="accounting", task="Prepare invoice 501 for approval.", depth=2)
    report = SpecialistReport(agent="accounting", status="needs_human", summary="prepared",
                              proposed_actions=[ProposedAction(action_type="payment", description="pay 501",
                                                               kind="invoice", ref_id=501, amount=840, payee="Bulldog Print Co")])
    assert report.proposed_actions[0].approval_status == "pending_human_approval"
    BossDecision(ticket_id=102, problem="rent", resolution_status="awaiting_human_approval", resolution_reason="x",
                 customer_message=None)
    assert RunLimits().max_delegation_depth == 3


@pytest.mark.parametrize("bad", [
    lambda: DelegationRequest(from_agent="boss", to_agent="janitor", task="clean the shop floor", depth=1),
    lambda: DelegationRequest(from_agent="boss", to_agent="inventory", task="hi", depth=1),
    lambda: ProposedAction(action_type="payment", description="x", amount=-5),
    lambda: CustomerMessageDraft(to="a", subject="b", body="c", is_draft=False),
    lambda: SpecialistReport(agent="inventory", status="done", summary="x"),
    lambda: BossDecision(ticket_id=1, problem="x", resolution_status="paid", resolution_reason="x"),
])
def test_models_reject_invalid_data(bad):
    with pytest.raises(ValidationError):
        bad()
