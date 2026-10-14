import { useEffect, useMemo, useState } from "react";
import { AGENTS, contributions, describe, latestRunId, statusMeta, ticketLine, ticketType, time } from "../present";
import type { FeedItem } from "../present";
import type { AgentName, Ticket } from "../types";
import type { Desk, RunView } from "../useDesk";
import { StatusBadge } from "./TicketBoard";

export function AgentAvatar({ agent, size = "md" }: { agent: string | null; size?: "sm" | "md" }) {
  if (!agent || !(agent in AGENTS)) {
    return <span className={`avatar avatar-${size} agent-desk`} aria-hidden="true">◆</span>;
  }
  const a = AGENTS[agent as AgentName];
  return <span className={`avatar avatar-${size} ${a.cls}`} aria-hidden="true" title={a.name}>{a.initials}</span>;
}

function RunBanner({ run }: { run: RunView | undefined }) {
  if (!run) return null;
  if (run.phase === "running") {
    return (
      <div className="run-banner running" role="status" aria-live="polite">
        <span className="pulse" aria-hidden="true" />
        <div>
          <strong>The team is working on this ticket.</strong>
          <p>Live activity appears below as agents act. A full run can take a few minutes.</p>
        </div>
      </div>
    );
  }
  const r = run.result;
  const tone = run.phase === "completed" && r?.succeeded ? "done" : run.phase === "limit_reached" ? "warn" : "fail";
  const heading = tone === "done"
    ? "Run finished"
    : run.phase === "limit_reached" ? "Run stopped at a safety limit — not a complete decision" : "Run did not complete";
  return (
    <div className={`run-banner ${tone}`} role="status" aria-live="polite">
      <div>
        <strong>{heading}</strong>
        {r?.resolution_status && <p>Boss decision: <em>{r.resolution_status.replace(/_/g, " ")}</em></p>}
        {r?.summary && <p className="run-summary">{r.summary}</p>}
        {r?.ticket_status && <p>Ticket status set by the backend: <StatusBadge status={r.ticket_status} /></p>}
        {(run.error || r?.error) && <p className="error-text">{run.error ?? r?.error}</p>}
        {r && (
          <p className="muted small-text">
            {r.delegations} delegation(s) · {r.usage?.requests ?? "?"} model calls · {r.usage?.total_tokens ?? "?"} tokens
            {r.pending_approvals?.length ? ` · ${r.pending_approvals.length} payment request(s) waiting for you →` : ""}
          </p>
        )}
      </div>
    </div>
  );
}

function Contributions({ items }: { items: ReturnType<typeof contributions> }) {
  if (!items.length) return null;
  return (
    <section aria-labelledby="contrib-title">
      <h3 id="contrib-title" className="sub-title">Who did what (latest run)</h3>
      <ul className="contrib">
        {items.map((c) => (
          <li key={c.agent} className={AGENTS[c.agent].cls}>
            <AgentAvatar agent={c.agent} />
            <div>
              <p className="contrib-name">{AGENTS[c.agent].name}<span className="muted"> · {AGENTS[c.agent].role}</span></p>
              <p>{c.summary || <span className="muted">No final report recorded (still working, or stopped early).</span>}</p>
              <p className="muted small-text">
                {c.toolsUsed} shop-data check(s) · {c.handoffs} hand-off(s){c.status ? ` · ${c.status.replace(/_/g, " ")}` : ""}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function FeedRow({ item }: { item: FeedItem }) {
  return (
    <li className={`feed-row tone-${item.tone}`}>
      <AgentAvatar agent={item.agent} size="sm" />
      <div className="feed-body">
        <p className="feed-title">
          <span>{item.title}</span>
          <time dateTime={item.ts} className="feed-time">{time(item.ts)}</time>
        </p>
        {item.detail && <p className="feed-detail">{item.detail}</p>}
        <details className="feed-tech">
          <summary>Technical details</summary>
          <pre>{JSON.stringify({ event_type: item.event.event_type, run_id: item.event.run_id, chain: item.event.chain, step: item.event.step, data: item.event.data }, null, 2)}</pre>
        </details>
      </div>
    </li>
  );
}

export function ActivityFeed({ items, error, technical, setTechnical }: {
  items: FeedItem[]; error: string | null | undefined; technical: boolean; setTechnical: (v: boolean) => void;
}) {
  const visible = technical ? items : items.filter((i) => !i.technical);
  const MAX = 250;
  const shown = visible.slice(-MAX);
  return (
    <section className="feed" aria-labelledby="feed-title">
      <div className="section-head">
        <h3 id="feed-title" className="sub-title">Activity</h3>
        <label className="toggle">
          <input type="checkbox" checked={technical} onChange={(e) => setTechnical(e.target.checked)} />
          Show technical steps
        </label>
      </div>
      {error && <p className="error-text" role="alert">Activity unavailable: {error}</p>}
      {!error && visible.length === 0 && <p className="muted">No agent activity recorded for this ticket yet.</p>}
      {visible.length > MAX && <p className="muted small-text">Showing the latest {MAX} of {visible.length} entries.</p>}
      <ol className="feed-list" aria-live="polite" aria-relevant="additions">
        {shown.map((i) => <FeedRow key={i.id} item={i} />)}
      </ol>
    </section>
  );
}

export function TicketDetail({ desk, ticket }: { desk: Desk; ticket: Ticket }) {
  const [technical, setTechnical] = useState(false);
  const events = desk.feeds[ticket.id] ?? [];
  const { loadFeed } = desk;
  useEffect(() => { void loadFeed(ticket.id); }, [loadFeed, ticket.id]);
  const items = useMemo(() => events.map(describe), [events]);
  const runId = desk.runs[ticket.id]?.result?.run_id ?? latestRunId(events);
  const contrib = useMemo(() => contributions(events, runId), [events, runId]);
  const meta = statusMeta(ticket.status);
  const pending = (desk.approvals.data?.approvals ?? []).filter((a) => a.ticket_id === ticket.id);
  return (
    <section className="detail" aria-labelledby="detail-title">
      <div className="detail-head">
        <div>
          <p className="eyebrow">Ticket #{ticket.id} · {ticketType(ticket.type)}</p>
          <h2 id="detail-title">{ticket.subject}</h2>
          <p className="muted">From {ticket.requester} · {ticketLine(ticket)}</p>
        </div>
        <StatusBadge status={ticket.status} />
      </div>
      {ticket.notes && <blockquote className="notes">{ticket.notes}</blockquote>}
      <p className={`status-hint ${meta.cls}`}>
        {meta.hint}
        {ticket.status === "awaiting_approval" && pending.length > 0 && ` ${pending.length} request(s) are in the approvals queue.`}
      </p>
      <RunBanner run={desk.runs[ticket.id]} />
      <Contributions items={contrib} />
      <ActivityFeed items={items} error={desk.feedErrors[ticket.id]} technical={technical} setTechnical={setTechnical} />
    </section>
  );
}
