import { useState } from "react";
import { agentName, approverProblem, kindLabel, money, time } from "../present";
import type { PendingApproval } from "../types";
import type { Desk } from "../useDesk";

type Outcome = { ok: boolean; message: string } | null;

function detailLine(p: PendingApproval): string {
  const d = p.details as Record<string, unknown>;
  if (p.kind === "invoice") return `Invoice #${d.invoice_id ?? p.ref_id}${d.description ? ` — ${d.description}` : ""}${d.due_date ? ` (due ${d.due_date})` : ""}`;
  if (p.kind === "rent") return `${d.space_name ?? `Lease #${p.ref_id}`} rent for ${d.for_due_date ?? "the current month"}`;
  if (p.kind === "purchase_order") return `${d.qty} × ${d.sku} size ${d.size}${d.expected_arrival ? `, expected ${d.expected_arrival}` : ""}`;
  return "";
}

function PendingCard({ p, name, desk }: { p: PendingApproval; name: string; desk: Desk }) {
  const [mode, setMode] = useState<"idle" | "decline">("idle");
  const [reason, setReason] = useState("");
  const [working, setWorking] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>(null);
  const nameProblem = approverProblem(name);

  const act = async (action: "approve" | "decline") => {
    setWorking(true);
    setOutcome(null);
    const r = await desk.decide(action, { request_id: p.request_id, name, amount: p.amount, reason, ticket_id: p.ticket_id });
    setWorking(false);
    setOutcome({ ok: r.ok, message: r.message });
  };

  return (
    <li className="slip" aria-label={`${kindLabel(p.kind)} to ${p.payee}, ${money(p.amount)}`}>
      <div className="slip-stamp" aria-hidden="true">NOT PAID</div>
      <p className="eyebrow">Ticket #{p.ticket_id ?? "—"} · prepared by {agentName(p.prepared_by)} · {time(p.proposed_at)}</p>
      <h3>{kindLabel(p.kind)} → {p.payee ?? "—"}</h3>
      <p className="slip-amount">{money(p.amount)}</p>
      <p className="slip-detail">{detailLine(p)}</p>
      <dl className="slip-math">
        <div><dt>Checking now</dt><dd>{money(p.balance_before)}</dd></div>
        <div><dt>After paying</dt><dd className={p.balance_after < 0 ? "neg" : ""}>{money(p.balance_after)}</dd></div>
      </dl>
      {!p.sufficient_funds && (
        <p className="warn-text" role="note">Checking doesn’t cover this. The backend will refuse an approval; declining is still possible.</p>
      )}
      {mode === "idle" ? (
        <div className="row">
          <button className="approve" disabled={working || !!nameProblem} onClick={() => act("approve")}>
            {working ? "Sending…" : `Approve & pay ${money(p.amount)}`}
          </button>
          <button className="ghost" disabled={working || !!nameProblem} onClick={() => setMode("decline")}>Decline…</button>
        </div>
      ) : (
        <div className="decline-box">
          <label>
            Reason (optional)
            <textarea maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} rows={2} />
          </label>
          <div className="row">
            <button className="danger" disabled={working || !!nameProblem} onClick={() => act("decline")}>
              {working ? "Sending…" : "Confirm decline"}
            </button>
            <button className="ghost" onClick={() => setMode("idle")} disabled={working}>Back</button>
          </div>
        </div>
      )}
      {outcome && <p className={outcome.ok ? "ok-text" : "error-text"} role={outcome.ok ? "status" : "alert"}>{outcome.message}</p>}
    </li>
  );
}

export function ApprovalsPanel({ desk }: { desk: Desk }) {
  const [name, setName] = useState(() => localStorage.getItem("cc-approver") ?? "");
  const { data, loading, error } = desk.approvals;
  const problem = approverProblem(name);
  const pending = data?.approvals ?? [];
  const decisions = [...(data?.decisions ?? [])].reverse();
  return (
    <section className="approvals" aria-labelledby="approvals-title">
      <div className="section-head">
        <h2 id="approvals-title" className="section-title">Needs your decision</h2>
        <button className="ghost small" onClick={desk.refreshApprovals} aria-label="Refresh approvals">↻</button>
      </div>
      <p className="muted small-text">Agents can only prepare payments. Nothing is paid until a person approves it here.</p>
      <label className="approver">
        Your name (recorded with every decision)
        <input
          value={name}
          onChange={(e) => { setName(e.target.value); localStorage.setItem("cc-approver", e.target.value); }}
          placeholder="e.g. Store Manager"
          aria-invalid={!!problem && name.length > 0}
          aria-describedby="approver-help"
        />
      </label>
      <p id="approver-help" className={problem && name ? "error-text small-text" : "muted small-text"}>
        {problem && name ? problem : "Required before you can approve or decline."}
      </p>
      {error && <p className="error-text" role="alert">Could not load approvals: {error}</p>}
      {!data && loading && <p className="muted" aria-busy="true">Loading approvals…</p>}
      {data && pending.length === 0 && <p className="empty">Nothing is waiting for approval.</p>}
      <ul className="slips">
        {pending.map((p) => <PendingCard key={p.request_id} p={p} name={name} desk={desk} />)}
      </ul>

      <h3 className="sub-title">Decision log</h3>
      {data && decisions.length === 0 && <p className="muted small-text">No approvals or declines since the last reset.</p>}
      <ul className="decisions">
        {decisions.map((d) => (
          <li key={d.request_id} className={`decision ${d.decision}`}>
            <span className={`stamp ${d.decision}`}>{d.decision === "approved" ? "PAID" : "DECLINED"}</span>
            <div>
              <p><strong>{kindLabel(d.kind)}</strong> {d.ref_id !== null ? `#${d.ref_id}` : ""} · {money(d.amount)} · ticket #{d.ticket_id ?? "—"}</p>
              <p className="muted small-text">{d.decision === "approved" ? "Approved" : "Declined"} by {d.decided_by} · {time(d.decided_at)}</p>
              {d.reason && <p className="small-text">“{d.reason}”</p>}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
