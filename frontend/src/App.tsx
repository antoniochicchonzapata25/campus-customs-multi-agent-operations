import { useEffect, useState } from "react";
import { ApprovalsPanel } from "./components/ApprovalsPanel";
import { Header, ResetControl } from "./components/Header";
import { TicketBoard } from "./components/TicketBoard";
import { TicketDetail } from "./components/TicketDetail";
import { useDesk } from "./useDesk";

export default function App({ pollMs = 1500 }: { pollMs?: number }) {
  const desk = useDesk({ pollMs });
  const [selected, setSelected] = useState<number | null>(null);
  const tickets = desk.tickets.data ?? [];

  // Select the first ticket once tickets arrive.
  useEffect(() => {
    if (selected === null && tickets.length) setSelected(tickets[0].id);
  }, [selected, tickets]);

  const ticket = tickets.find((t) => t.id === selected) ?? null;
  const anyRunning = Object.values(desk.runs).some((r) => r.phase === "running") || tickets.some((t) => t.run_in_progress);

  return (
    <div className="app">
      <a className="skip" href="#workspace">Skip to ticket workspace</a>
      <Header desk={desk} />
      <main className="layout">
        <aside className="col col-left">
          <TicketBoard desk={desk} selected={selected} onSelect={setSelected} />
          <ResetControl desk={desk} busy={anyRunning} />
        </aside>
        <div className="col col-center" id="workspace">
          {ticket ? (
            <TicketDetail desk={desk} ticket={ticket} />
          ) : (
            <section className="detail empty-state">
              <p className="muted">{desk.tickets.loading ? "Loading the desk…" : "Pick a ticket to see its details and activity."}</p>
            </section>
          )}
        </div>
        <aside className="col col-right">
          <ApprovalsPanel desk={desk} />
        </aside>
      </main>
      <footer className="foot">
        Agents run on gpt-6-luna through the Campus Customs MCP server. Every action shown here comes from the backend’s audit trail.
      </footer>
    </div>
  );
}
