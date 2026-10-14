import { statusMeta, ticketLine, ticketType } from "../present";
import type { Ticket } from "../types";
import type { Desk } from "../useDesk";

export function StatusBadge({ status }: { status: string }) {
  const m = statusMeta(status);
  return <span className={`badge ${m.cls}`}>{m.label}</span>;
}

function TicketCard({ t, selected, running, onSelect, onRun }: {
  t: Ticket; selected: boolean; running: boolean; onSelect: () => void; onRun: () => void;
}) {
  const busy = running || t.run_in_progress;
  return (
    <li className={`ticket ${statusMeta(t.status).cls} ${selected ? "selected" : ""}`}>
      <button className="ticket-main" onClick={onSelect} aria-pressed={selected} aria-label={`Ticket ${t.id}: ${t.subject}`}>
        <div className="ticket-head">
          <span className="ticket-id">#{t.id}</span>
          <StatusBadge status={t.status} />
        </div>
        <h3>{t.subject}</h3>
        <p className="ticket-type">{ticketType(t.type)} · from {t.requester}</p>
        {ticketLine(t) && <p className="ticket-line">{ticketLine(t)}</p>}
        {t.notes && <p className="ticket-notes">“{t.notes}”</p>}
      </button>
      <div className="ticket-actions">
        <button className="primary" onClick={onRun} disabled={busy} aria-busy={busy}>
          {busy ? <><span className="spinner" aria-hidden="true" /> Team working…</> : "Run agent team"}
        </button>
      </div>
    </li>
  );
}

export function TicketBoard({ desk, selected, onSelect }: { desk: Desk; selected: number | null; onSelect: (id: number) => void }) {
  const { data, loading, error } = desk.tickets;
  return (
    <section className="board" aria-labelledby="board-title">
      <div className="section-head">
        <h2 id="board-title" className="section-title">Tickets</h2>
        <button className="ghost small" onClick={desk.refreshTickets} aria-label="Refresh tickets">↻</button>
      </div>
      {error && <p className="error-text" role="alert">Could not load tickets: {error}</p>}
      {!data && loading && <p className="muted" aria-busy="true">Loading tickets…</p>}
      {data && data.length === 0 && <p className="muted">No tickets on the desk.</p>}
      {data && data.length > 0 && (
        <ul className="ticket-list">
          {data.map((t) => (
            <TicketCard
              key={t.id}
              t={t}
              selected={selected === t.id}
              running={desk.runs[t.id]?.phase === "running"}
              onSelect={() => onSelect(t.id)}
              onRun={() => { onSelect(t.id); void desk.startRun(t.id); }}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
