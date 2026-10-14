"""The five Campus Customs agents: model, prompts, outputs, and MCP tool access.

Every agent runs on gpt-6-luna through Portkey (no other model, no fallback).
Shop facts come only from the campus-customs MCP server (mcp_server/server.py)
over stdio; each agent sees just the MCP tools its role needs. The two write
tools are reserved for the backend's human-approval routes and are never
given to any agent.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastmcp.client import Client
from fastmcp.client.transports import StdioTransport
from openai import AsyncOpenAI
from pydantic_ai.mcp import MCPToolset, ProcessToolCallback
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

from models import AGENT_NAMES, AgentName, BossDecision, SpecialistReport

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
PROMPTS_DIR = BACKEND_DIR / "prompts"
MCP_SERVER_SCRIPT = PROJECT_ROOT / "mcp_server" / "server.py"

MODEL_NAME = "gpt-6-luna"  # the only model allowed in this project
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"
MODEL_TIMEOUT_SECONDS = 90

# MCP tools each agent may call. Everything not listed is hidden from that agent.
AGENT_TOOLS: dict[AgentName, frozenset[str]] = {
    "boss": frozenset({"get_tickets"}),
    "inventory": frozenset({"get_tickets", "get_product_stock_and_price", "list_vendors", "get_open_vendor_invoices"}),
    "accounting": frozenset(
        {"get_tickets", "get_cash_balance", "get_open_vendor_invoices", "get_product_stock_and_price", "prepare_payment_request"}
    ),
    "facilities": frozenset({"get_tickets", "get_lease_rent_status"}),
    "customer_service": frozenset({"get_tickets"}),
}
# Tools that change money or ticket state: backend-only, after a human approves.
BACKEND_ONLY_TOOLS = frozenset({"record_approved_payment", "update_ticket_status"})
assert not any(tools & BACKEND_ONLY_TOOLS for tools in AGENT_TOOLS.values())

AGENT_OUTPUT_TYPES: dict[AgentName, type] = {
    "boss": BossDecision,
    "inventory": SpecialistReport,
    "accounting": SpecialistReport,
    "facilities": SpecialistReport,
    "customer_service": SpecialistReport,
}

AGENT_DESCRIPTIONS: dict[AgentName, str] = {
    "boss": "Reads the ticket, picks who works on it, reviews findings, makes the final call.",
    "inventory": "Stock by SKU and size, shortfalls, which vendor can restock and when.",
    "accounting": "Cash, invoices, margins; prepares payments and purchase orders for human approval.",
    "facilities": "Leases and rent; verifies landlord notices against the lease on file.",
    "customer_service": "Drafts customer replies from verified facts; drafts are never sent.",
}


class ModelNotConfigured(RuntimeError):
    """PORTKEY_API_KEY is missing, so gpt-6-luna cannot be reached."""


def load_prompt(name: AgentName) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise RuntimeError(f"Prompt file {path} is empty")
    return text


def build_model() -> Model:
    """gpt-6-luna via the Portkey gateway. Fails loudly; never substitutes a model."""
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(PROJECT_ROOT.parents[1] / ".env")  # course-level .env (repo root)
    api_key = os.getenv("PORTKEY_API_KEY")
    if not api_key:
        raise ModelNotConfigured("PORTKEY_API_KEY is not set. Add it to .env (see .env.example).")
    client = AsyncOpenAI(
        api_key=api_key,
        base_url=PORTKEY_BASE_URL,
        default_headers={"x-portkey-provider": "openai"},
        timeout=MODEL_TIMEOUT_SECONDS,
        max_retries=1,
    )
    return OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))


def build_mcp_toolset(process_tool_call: ProcessToolCallback, db_path: Path | None = None) -> MCPToolset:
    """Connect to the campus-customs MCP server over stdio (same server as .mcp.json).

    `db_path` points the server at an isolated database copy (tests only); by
    default the server uses data/campus_customs_new.db. The Portkey key is not
    passed to the server process, which never needs it.
    """
    env = {k: v for k, v in os.environ.items() if k != "PORTKEY_API_KEY"}
    env.pop("CAMPUS_CUSTOMS_DB", None)
    if db_path is not None:
        env["CAMPUS_CUSTOMS_DB"] = str(Path(db_path).resolve())
    transport = StdioTransport(
        command=sys.executable,
        args=[str(MCP_SERVER_SCRIPT)],
        env=env,
        cwd=str(PROJECT_ROOT),
        # End the server process when the connection closes. FastMCP's default
        # (True) leaves it running in the background, which leaks processes and
        # can block event-loop shutdown.
        keep_alive=False,
    )
    return MCPToolset(
        Client(transport),
        id="campus-customs",
        max_retries=2,
        process_tool_call=process_tool_call,
    )
