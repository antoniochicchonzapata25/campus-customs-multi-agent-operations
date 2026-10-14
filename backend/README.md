# Campus Customs backend

This folder holds the FastAPI backend and the five PydanticAI agents (Boss, Inventory, Accounting, Facilities, Customer Service).

## Setup

```bash
pip install -r requirements.txt     # from the project root
cp .env.example .env                # then set PORTKEY_API_KEY
```

- **Model:** every agent uses `gpt-6-luna` through Portkey. Without `PORTKEY_API_KEY`, the read routes still work, but the run route returns 503.
- **No separate MCP startup:** the backend starts `mcp_server/server.py` itself over stdio (the same server `.mcp.json` registers for Claude Code). It points at `data/campus_customs_new.db`, so you don't need to start the MCP server separately.

## Run

```bash
cd backend
uvicorn main:app --reload --port 8000
```

Open `http://localhost:8000/docs` for the interactive route list. CORS allows the Vite dev server at `http://localhost:5173`.

## Files

| File | Role |
|---|---|
| `main.py` | FastAPI routes (see `output/harness.md`, section 10) |
| `shop.py` | Backend client for the MCP server. All shop reads and writes go through it; there is no SQL here. |
| `approvals.py` | Pending requests (rebuilt from the audit trail and re-priced through MCP) and human approval |
| `db_reset.py` | Safe, atomic reset of the working DB from the original |
| `team.py`, `agents.py`, `prompts/` | The agent team: delegation, limits, audit logging |
| `models.py` | Pydantic types for agents, audit events and API responses |
| `audit.py` | Append-only `output/audit_trail.json` |

## Fresh run

1. Reset with `POST /api/reset` and body `{"confirm": true}`. That copies the original DB over the working DB.
2. Run tickets with `POST /api/tickets/{id}/run`.
3. Approve prepared payments with `POST /api/approvals`.

## Tests

```bash
cd backend
python -m pytest tests -q
```

The tests use temporary databases and a temporary audit trail only, plus a scripted mock model (no live API calls). `tests/live_smoke.py` is a separate opt-in live check.
