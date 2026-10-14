import { useState } from "react";
import { money } from "../present";
import type { Desk } from "../useDesk";

export function CashCard({ cash, onRefresh }: { cash: Desk["cash"]; onRefresh: () => void }) {
  return (
    <section className="till" aria-labelledby="till-title">
      <div className="till-top">
        <h2 id="till-title">Checking account</h2>
        <button className="ghost small" onClick={onRefresh} aria-label="Refresh checking balance">↻</button>
      </div>
      {cash.error && !cash.data ? (
        <p className="till-error" role="alert">Balance unavailable: {cash.error}</p>
      ) : cash.data ? (
        <>
          <p className="till-amount" aria-live="polite" data-testid="cash-balance">{money(cash.data.balance)}</p>
          <p className="till-meta">
            Actual balance as of {cash.data.balance_as_of} · shop date {cash.data.shop_date}
            {cash.loading && <span className="spinner" aria-label="Refreshing" />}
          </p>
          {cash.error && <p className="till-error" role="alert">Last refresh failed: {cash.error}</p>}
        </>
      ) : (
        <p className="till-amount muted" aria-busy="true">Loading…</p>
      )}
      <p className="till-note">Only approved payments change this number. Prepared requests don’t.</p>
    </section>
  );
}

export function Header({ desk }: { desk: Desk }) {
  const h = desk.health;
  return (
    <header className="masthead">
      <div className="brand">
        <div className="logo" aria-hidden="true"><span>CC</span></div>
        <div>
          <h1>Campus Customs Desk</h1>
          <p className="tagline">Five agents, one shop, and you deciding where the money goes.</p>
        </div>
      </div>
      <div className="masthead-right">
        <div className={`health ${h ? (h.status === "ok" ? "ok" : "degraded") : "down"}`} role="status">
          <span className="dot" aria-hidden="true" />
          {h ? (
            <span>
              Backend {h.status === "ok" ? "ready" : "degraded"} · shop data {h.mcp_connected ? "connected" : "offline"} ·{" "}
              {h.model} {h.model_configured ? "configured" : "not configured"}
            </span>
          ) : (
            <span>Backend unreachable</span>
          )}
        </div>
        <CashCard cash={desk.cash} onRefresh={desk.refreshCash} />
      </div>
    </header>
  );
}

/** Reset is destructive for the working DB, so it needs a typed confirmation. */
export function ResetControl({ desk, busy }: { desk: Desk; busy: boolean }) {
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [working, setWorking] = useState(false);
  return (
    <section className="reset" aria-labelledby="reset-title">
      <h2 id="reset-title" className="section-title">Fresh start</h2>
      {!open ? (
        <button className="ghost" onClick={() => { setOpen(true); setResult(null); }} disabled={busy}>
          Reset working database…
        </button>
      ) : (
        <div className="reset-box">
          <p>Restores <code>campus_customs_new.db</code> from the untouched original. Payments and ticket statuses go back to the start. The audit trail is kept.</p>
          <label>
            Type <strong>RESET</strong> to confirm
            <input value={typed} onChange={(e) => setTyped(e.target.value)} aria-label="Type RESET to confirm" />
          </label>
          <div className="row">
            <button
              className="danger"
              disabled={typed !== "RESET" || working || busy}
              onClick={async () => {
                setWorking(true);
                setResult(await desk.reset());
                setWorking(false); setOpen(false); setTyped("");
              }}
            >{working ? "Resetting…" : "Reset now"}</button>
            <button className="ghost" onClick={() => { setOpen(false); setTyped(""); }}>Cancel</button>
          </div>
        </div>
      )}
      {busy && <p className="muted small-text">Reset is disabled while a team run is in progress.</p>}
      {result && <p className={result.ok ? "ok-text" : "error-text"} role="status">{result.message}</p>}
    </section>
  );
}
