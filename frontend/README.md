# Campus Customs Desk (frontend)

A React + Vite + TypeScript dashboard for the FastAPI backend in `../backend`.

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # type-check (tsc -b) + production build into dist/
npm test           # Vitest + Testing Library, against a mocked backend
```

- **Backend URL:** set `VITE_API_BASE_URL` (see `.env.example`). The default is `http://localhost:8000`.
- **Start the backend first:** from `backend/`, run `uvicorn main:app --reload --port 8000`. The backend's CORS settings allow `http://localhost:5173`.

## Structure

| File | Role |
|---|---|
| `src/api.ts` | Thin API client and error normalisation (no business logic) |
| `src/types.ts` | TypeScript mirror of `backend/models.py` |
| `src/useDesk.ts` | All state: loading, refresh, runs (fire the run, poll `/api/events?after=`), approve / decline / reset |
| `src/present.ts` | Agent identities, status labels, events turned into plain language, de-duplication |
| `src/components/` | Header (till, health), TicketBoard, TicketDetail (run banner, contributions, activity), ApprovalsPanel |
| `src/test/` | Mocked backend and the tests |

The design rationale is in `../output/design.md`.
