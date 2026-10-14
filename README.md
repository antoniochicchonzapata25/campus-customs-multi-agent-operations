# Campus Customs Multi-Agent Operations

MGT 409 AI Foundations, Homework 5. Five PydanticAI agents (**Boss, Inventory, Accounting, Facilities, Customer Service**) run a small campus shop's desk.

- **Shop data:** they read the shop through an **MCP server** (FastMCP over SQLite).
- **Backend:** a **FastAPI backend** runs the team.
- **Dashboard:** a **React + Vite + TypeScript** dashboard lets a person watch the agents, and approve or decline every payment.
- **Model:** every agent uses **`gpt-6-luna` through Portkey**.

```
MCP server (mcp_server/server.py) ◄── stdio ── FastAPI backend (backend/) ◄── HTTP ── React desk (frontend/)
        │                                            │
        ▼                                            ▼
data/campus_customs_new.db                 output/audit_trail.json (append-only)
```

## 1. Install

You need Python 3.12+ and Node.js 20+.

```bash
# from the project root
python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt

cd frontend
npm install
cd ..
```

## 2. Configure the Portkey key (never commit it)

```bash
cp .env.example .env        # Windows: copy .env.example .env
```

Open `.env` and set `PORTKEY_API_KEY=` to the course-provided Portkey key.

- **Never commit `.env`:** it is listed in `.gitignore`, and no key is stored anywhere in this repository.
- **No other setup:** the backend reads the key from the environment or `.env` only.
- **Without a key,** the read-only routes still work, but running the agents returns a "model not configured" error.

The dashboard's backend URL defaults to `http://localhost:8000`. To change it, copy `frontend/.env.example` to `frontend/.env`.

## 3. Start the MCP server

```bash
python mcp_server/server.py
```

- **You don't need to start it for the app.** The backend starts this same server itself over stdio.
- **Use it standalone** to test the tools, or connect it to Claude Code through `.mcp.json`. That file uses `.venv/Scripts/python.exe` (Windows); on macOS or Linux, change it to `.venv/bin/python`.
- **Database:** the server always uses the working database `data/campus_customs_new.db`, and refuses to start on the original.

## 4. Start the FastAPI backend

```bash
cd backend
uvicorn main:app --reload --port 8000
```

API docs are at http://localhost:8000/docs. The routes are listed in `output/harness.md`, section 10.

## 5. Start the React dashboard

```bash
cd frontend
npm run dev
```

Open http://localhost:5173.

- **Tickets:** pick a ticket and click **Run agent team**. Activity streams in while the agents work.
- **Approvals:** prepared payments appear under **Needs your decision**. Enter *your* name, then **Approve** or **Decline**. Agents can never pay on their own.

## 6. Reset the working database before a fresh three-ticket run

`data/campus_customs.db` is the untouched original. `data/campus_customs_new.db` is the working copy the agents change.

> **As committed,** the working database holds the final Problem 9 state: checking **$160.00**, 2 payments, and tickets 101/102 resolved, 103 in progress. Reset it before replaying the tickets.

There are two ways to reset:

- **From the dashboard (recommended):** click **Reset working database…**, type `RESET`, then **Reset now**. That calls `POST /api/reset`, which copies the original over the working file safely and refuses while a run is in progress.
- **Manually, with the backend stopped:**
  ```bash
  cp data/campus_customs.db data/campus_customs_new.db    # Windows: copy data\campus_customs.db data\campus_customs_new.db
  ```

The audit trail is never reset; new runs are appended to it.

## Tests (no model calls)

```bash
cd backend && python -m pytest tests -q   # mock model plus the real MCP server on temporary DB copies
cd frontend && npm test                    # dashboard against a mocked backend
```

## Repository map

| Path | What it is |
|---|---|
| `mcp_server/` | FastMCP server with 9 tools ([README](mcp_server/README.md)) |
| `backend/` | FastAPI app (`main.py`), the agent team (`agents.py`, `team.py`), data models (`models.py`), prompts (`prompts/*.md`) and tests ([README](backend/README.md)) |
| `frontend/` | React dashboard ([README](frontend/README.md)) |
| `data/` | `campus_customs.db` (original) and `campus_customs_new.db` (working copy) |
| `output/harness.md` | Technical reference: tables, tools, agents, routes, dashboard, safety, results |
| `output/mcp_smoke.json` | Problem 4 MCP tool tests |
| `output/desk_tickets.html` | Expected vs. Actual per ticket, Cash reconciliation, Reflection |
| `output/design.md` | Dashboard design |
| `output/resolved_tickets.json`, `output/resolved_board.html` | Problem 9 outcomes and real dashboard screenshots |
| `output/audit_trail.json` | Append-only log of every agent step and human decision |
| `AI_prompts.md` | The prompts used for each problem |

## Results (Problem 9)

| Ticket | Outcome | Cash |
|---|---|---|
| 101 · Bulldog tee | Invoice 501 approved and paid. Marked resolved, but the tee is not yet ordered | $3,400 → $2,560 |
| 102 · Rent due | Notice verified, rent approved and paid. Resolved | → $160 |
| 103 · Bulk hoodie discount | $264 restock declined: $160 available, $104 short. In progress | $160 |

The details are in `output/desk_tickets.html`.
